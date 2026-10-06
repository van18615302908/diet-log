#!/usr/bin/env python3
"""diet-log CLI —— 记餐 / 记身体指标 / 归档照片 / 生成看板数据。规则见 CLAUDE.md。"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAYS = ROOT / "data" / "days"
PHOTOS = ROOT / "photos"
INBOX = ROOT / "inbox"
PROFILE = ROOT / "profile.json"
PROFILE_EXAMPLE = ROOT / "profile.example.json"
WEB_DATA = ROOT / "web" / "data.js"

MEAL_TYPES = ["早餐", "午餐", "晚餐", "加餐", "饮料"]
DEFAULT_TIME = {"早餐": "08:00", "午餐": "12:30", "晚餐": "18:30", "加餐": "15:30", "饮料": "15:00"}
KIND_LABEL = {"body": "身体", "label": "成分表", "other": "其他"}
BODY_FIELDS = {"weight": "weight_kg", "fat": "body_fat_pct", "waist": "waist_cm",
               "sleep": "sleep_h", "steps": "steps", "water": "water_ml"}
ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}


# ---------- 存取 ----------

def day_path(date: str) -> Path:
    return DAYS / f"{date}.json"


def load_day(date: str) -> dict:
    p = day_path(date)
    if p.exists():
        return json.loads(p.read_text())
    return {"date": date, "body": {}, "meals": [], "photos": [], "note": ""}


def save_day(day: dict) -> None:
    DAYS.mkdir(parents=True, exist_ok=True)
    day["meals"].sort(key=lambda m: m["time"])
    day_path(day["date"]).write_text(json.dumps(day, ensure_ascii=False, indent=2) + "\n")


def load_profile() -> dict:
    """第一次运行时从模板复制出 profile.json（个人资料，不进 git）。"""
    if not PROFILE.exists() and PROFILE_EXAMPLE.exists():
        shutil.copy(PROFILE_EXAMPLE, PROFILE)
    return json.loads(PROFILE.read_text()) if PROFILE.exists() else {}


def today() -> str:
    return dt.date.today().isoformat()


# ---------- 计算 ----------

# (key, 中文名, 单位)。条目里没写的字段视为「没数据」，不是 0
NUTRIENTS = [
    ("kcal", "热量", "kcal"), ("protein", "蛋白质", "g"), ("carb", "碳水", "g"), ("fat", "脂肪", "g"),
    ("sat_fat", "饱和脂肪", "g"), ("fiber", "膳食纤维", "g"), ("sugar_added", "添加糖", "g"),
    ("sodium", "钠", "mg"), ("potassium", "钾", "mg"), ("calcium", "钙", "mg"), ("iron", "铁", "mg"),
    ("magnesium", "镁", "mg"), ("vit_c", "维生素C", "mg"), ("vit_d", "维生素D", "mcg"), ("vit_a", "维生素A", "mcg"),
]
NKEYS = [k for k, _, _ in NUTRIENTS]


def sum_items(items: list) -> dict:
    t = {k: 0 for k in NKEYS}
    for it in items:
        for k in NKEYS:
            t[k] += it.get(k) or 0
    return {k: round(v, 1) if v % 1 else int(v) for k, v in t.items()}


def meal_totals(meal: dict) -> dict:
    return sum_items(meal["items"])


def day_totals(day: dict) -> dict:
    return sum_items([it for m in day["meals"] for it in m["items"]])


def coverage(day: dict) -> dict:
    """每个营养素：有数据的条目占当天热量的比例。低于 0.9 看板标「数据不全」。"""
    items = [it for m in day["meals"] for it in m["items"] if (it.get("kcal") or 0) > 0]
    total = sum(it["kcal"] for it in items) or 1
    return {k: round(sum(it["kcal"] for it in items if k in it) / total, 2) for k in NKEYS}


def exercise_kcal(day: dict) -> int:
    return round(sum(e.get("kcal") or 0 for e in day.get("exercise", [])))


def day_targets(profile: dict, day: dict) -> dict:
    """当天目标：BMR(Mifflin-St Jeor) × 日常活动系数 + 当天运动消耗 − 减脂缺口。
    返回 {key: {"min"/"max": 数}} 加上 bmr/base/exercise 说明字段。"""
    w = latest_weight(day["date"]) or profile.get("weight_kg")
    h, sex, birth = profile.get("height_cm"), profile.get("sex"), profile.get("birth_year")
    out = {k: dict(v) for k, v in profile.get("nutrient_targets", {}).items()}
    out["_info"] = {"bmr": None, "base": None, "exercise": exercise_kcal(day), "deficit": 0}
    if not (w and h and sex and birth):
        return out
    age = int(day["date"][:4]) - birth
    bmr = 10 * w + 6.25 * h - 5 * age + (5 if sex == "male" else -161)
    base = bmr * ACTIVITY.get(profile.get("activity", "sedentary"), 1.2)
    deficit = {"lose": profile.get("deficit_kcal", 500), "gain": -300}.get(profile.get("goal"), 0)
    kcal = round(profile.get("target_kcal") or base + out["_info"]["exercise"] - deficit)
    protein = profile.get("target_protein_g") or round(w * profile.get("protein_g_per_kg", 1.8))
    fat_min, fat_max = profile.get("fat_g_range", [round(w * 0.6), round(w * 0.9)])
    out["_info"].update(bmr=round(bmr), base=round(base), deficit=deficit)
    out["kcal"] = {"min": round(kcal * 0.85), "max": kcal, "goal": kcal}
    out["protein"] = {"min": protein}
    out["fat"] = {"min": fat_min, "max": fat_max}
    out["carb"] = {"max": max(0, round((kcal - protein * 4 - fat_min * 9) / 4))}
    out["sat_fat"] = {"max": round(kcal * 0.10 / 9)}
    return out


def status(val: float, tg: dict | None, cov: float = 1) -> str:
    if not tg:
        return ""
    if cov == 0:
        return "无数据"
    if "max" in tg and val > tg["max"] * (1.05 if "min" in tg else 1):
        return "超标"
    if "min" in tg and val < tg["min"]:
        return "接近" if val >= tg["min"] * 0.8 else "不足"
    return "达标"


def latest_weight(upto: str | None = None) -> float | None:
    for p in sorted(DAYS.glob("*.json"), reverse=True):
        if upto and p.stem > upto:
            continue
        w = json.loads(p.read_text()).get("body", {}).get("weight_kg")
        if w:
            return w
    return None


# ---------- 命令 ----------

def cmd_meal(a: argparse.Namespace) -> None:
    if a.type not in MEAL_TYPES:
        sys.exit(f"type 只能是 {MEAL_TYPES}")
    items = json.loads(a.items)
    day = load_day(a.date)
    time = a.time or DEFAULT_TIME[a.type]
    target = None
    if a.append:
        target = next((m for m in day["meals"] if m["type"] == a.type and (not a.time or m["time"] == a.time)), None)
    if target:
        target["items"].extend(items)
        if a.note:
            target["note"] = (target.get("note", "") + "；" + a.note).strip("；")
    else:
        day["meals"].append({"time": time, "type": a.type, "items": items, "photos": [], "note": a.note or ""})
    save_day(day)
    print_day(day)


def cmd_body(a: argparse.Namespace) -> None:
    day = load_day(a.date)
    for flag, key in BODY_FIELDS.items():
        v = getattr(a, flag)
        if v is not None:
            day["body"][key] = v
    for kv in a.set or []:
        k, v = kv.split("=", 1)
        try:
            v = float(v)
        except ValueError:
            pass
        day["body"][k] = v
    if a.note:
        day["body"]["note"] = a.note
    save_day(day)
    print_day(day)


def cmd_exercise(a: argparse.Namespace) -> None:
    """--kcal 直接给；否则按 MET 估净消耗 = (MET−1) × 体重 × 小时（扣掉本来就会消耗的静息量）。"""
    day = load_day(a.date)
    kcal = a.kcal
    if kcal is None:
        w = latest_weight(a.date) or load_profile().get("weight_kg")
        if not (a.met and w):
            sys.exit("需要 --kcal，或 --met 加已知体重")
        kcal = round((a.met - 1) * w * a.minutes / 60)
    day.setdefault("exercise", []).append(
        {"name": a.name, "minutes": a.minutes, "kcal": kcal, "met": a.met,
         "parts": [x.strip() for x in (a.parts or "").split(",") if x.strip()], "note": a.note or ""})
    save_day(day)
    print_day(day)


def cmd_review(a: argparse.Namespace) -> None:
    """给某一餐写点评：score 1-5，good 做得好的，fix 下次怎么改（都可多条）。"""
    day = load_day(a.date)
    meal = next((m for m in day["meals"] if m["type"] == a.type and (not a.time or m["time"] == a.time)), None)
    if meal is None:
        sys.exit(f"{a.date} 没有 {a.type}")
    meal["review"] = {"score": a.score, "good": a.good or [], "fix": a.fix or []}
    save_day(day)
    print(f"已点评 {a.date} {a.type}")


def cmd_advice(a: argparse.Namespace) -> None:
    """写在今天的文件里，内容是给「明天」的建议；看板在明天那页也会显示。"""
    day = load_day(a.date)
    day["advice"] = {"summary": a.summary or "", "training": a.training or [], "diet": a.diet or []}
    save_day(day)
    print(f"已写入 {a.date} 给明天的建议")


def exif_time(src: Path) -> dt.datetime | None:
    """只信 EXIF 拍摄时间（sips 的 creation）；微信/截图转存的图没有，返回 None。"""
    try:
        out = subprocess.run(["sips", "-g", "creation", str(src)], capture_output=True, text=True).stdout
        raw = out.strip().splitlines()[-1].split("creation:")[1].strip()
        return dt.datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def cmd_photo(a: argparse.Namespace) -> None:
    src = Path(a.src).expanduser()
    if not src.exists():
        sys.exit(f"找不到 {src}")
    shot = exif_time(src)
    date = a.date or (shot.date().isoformat() if shot else today())
    hhmm = (a.time or (shot.strftime("%H:%M") if shot else dt.datetime.now().strftime("%H:%M"))).replace(":", "")
    if a.kind == "meal":
        if a.meal not in MEAL_TYPES:
            sys.exit("meal 照片需要 --meal " + "/".join(MEAL_TYPES))
        cat = a.meal
    else:
        cat = KIND_LABEL[a.kind]
    desc = re.sub(r"[\s/\\:*?\"<>|]+", "-", a.desc).strip("-")
    folder = PHOTOS / date[:7]
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{date}_{hhmm}_{cat}_{desc}"
    dest, n = folder / f"{stem}.jpg", 2
    while dest.exists():
        dest, n = folder / f"{stem}-{n}.jpg", n + 1

    if src.suffix.lower() in (".jpg", ".jpeg"):
        shutil.copy2(src, dest)
    else:  # HEIC / PNG / WEBP → jpg，顺便限制长边
        subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "2400", str(src), "--out", str(dest)],
                       check=True, capture_output=True)

    rel = str(dest.relative_to(ROOT))
    day = load_day(date)
    meal = None
    if a.kind == "meal":
        meal = next((m for m in day["meals"] if m["type"] == a.meal), None)
        if meal is None:
            meal = {"time": f"{hhmm[:2]}:{hhmm[2:]}", "type": a.meal, "items": [], "photos": [], "note": ""}
            day["meals"].append(meal)
        meal["photos"].append(rel)
    else:
        day["photos"].append({"path": rel, "kind": a.kind, "desc": a.desc})
    save_day(day)
    if src.resolve().parent in (INBOX.resolve(), ROOT):
        src.unlink()
    print(f"已归档 → {rel}")


def print_day(day: dict) -> None:
    tg = day_targets(load_profile(), day)
    t, cov = day_totals(day), coverage(day)
    print(f"[{day['date']}]")
    for m in day["meals"]:
        mt = meal_totals(m)
        names = "、".join(i["name"] for i in m["items"]) or "(只有照片)"
        print(f"  {m['time']} {m['type']}  {names}  {mt['kcal']} kcal  P{mt['protein']} C{mt['carb']} F{mt['fat']}")
    for e in day.get("exercise", []):
        print(f"  运动 {e['name']} {e.get('minutes', '?')}min  约 {e.get('kcal', '?')} kcal")
    info = tg["_info"]
    if info["bmr"]:
        print(f"  目标 = 日常 {info['base']} + 运动 {info['exercise']} − 缺口 {info['deficit']} = {tg['kcal']['goal']} kcal")
    for k, name, unit in NUTRIENTS:
        rng = tg.get(k, {})
        goal = "–".join(str(rng[x]) for x in ("min", "max") if x in rng) if k != "kcal" else str(rng.get("goal", ""))
        flag = status(t[k], rng, cov[k]) + ("(数据不全)" if t[k] and cov[k] < 0.9 else "")
        print(f"  {name:<6}{t[k]:>7} {unit:<4} 目标 {goal or '–':<10} {flag}")
    if day["body"]:
        print("  身体 " + "  ".join(f"{k}={v}" for k, v in day["body"].items()))


def cmd_show(a: argparse.Namespace) -> None:
    print_day(load_day(a.date))


def cmd_stats(a: argparse.Namespace) -> None:
    end = dt.date.fromisoformat(a.date)
    rows = []
    for i in range(a.days - 1, -1, -1):
        d = (end - dt.timedelta(days=i)).isoformat()
        if day_path(d).exists():
            day = load_day(d)
            rows.append((d, day_totals(day), day["body"].get("weight_kg"), len(day["meals"])))
    if not rows:
        print("没有记录")
        return
    logged = [r for r in rows if r[3]]
    print(f"{a.days} 天内有记录 {len(logged)} 天")
    for d, t, w, n in rows:
        print(f"  {d}  {t['kcal']:>5} kcal  P{t['protein']:>4} C{t['carb']:>4} F{t['fat']:>4}  {w or '':>6}  {n}餐")
    if logged:
        avg = {k: round(sum(r[1][k] for r in logged) / len(logged)) for k in ("kcal", "protein", "carb", "fat")}
        print(f"  日均 {avg['kcal']} kcal  P{avg['protein']} C{avg['carb']} F{avg['fat']}")
    ws = [(d, w) for d, _, w, _ in rows if w]
    if len(ws) >= 2:
        print(f"  体重 {ws[0][1]} → {ws[-1][1]} kg ({ws[-1][1] - ws[0][1]:+.1f})")


def cmd_build(_: argparse.Namespace) -> None:
    prof = load_profile()
    days = [json.loads(p.read_text()) for p in sorted(DAYS.glob("*.json"))]
    for d in days:
        d["totals"], d["coverage"], d["targets"] = day_totals(d), coverage(d), day_targets(prof, d)
        d["status"] = {k: status(d["totals"][k], d["targets"].get(k), d["coverage"][k]) for k in NKEYS}
        for m in d["meals"]:
            m["totals"] = meal_totals(m)
    data = {"profile": prof, "nutrients": NUTRIENTS, "days": days,
            "built_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    WEB_DATA.parent.mkdir(exist_ok=True)
    WEB_DATA.write_text("window.DIET_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")
    print(f"看板数据已更新：{len(days)} 天 → web/data.js")


def main() -> None:
    p = argparse.ArgumentParser(description="diet-log")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("meal")
    s.add_argument("--date", default=today())
    s.add_argument("--time")
    s.add_argument("--type", required=True)
    s.add_argument("--items", required=True, help="JSON 数组")
    s.add_argument("--note")
    s.add_argument("--append", action="store_true")
    s.set_defaults(fn=cmd_meal)

    s = sub.add_parser("body")
    s.add_argument("--date", default=today())
    for flag in BODY_FIELDS:
        s.add_argument(f"--{flag}", type=float)
    s.add_argument("--set", action="append", help="其他指标 key=value，可多次")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_body)

    s = sub.add_parser("exercise")
    s.add_argument("--date", default=today())
    s.add_argument("--name", required=True)
    s.add_argument("--minutes", type=float, required=True)
    s.add_argument("--met", type=float)
    s.add_argument("--kcal", type=float)
    s.add_argument("--parts", help="练到的部位，逗号分隔，如 腿,肩,核心")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_exercise)

    s = sub.add_parser("review")
    s.add_argument("--date", default=today())
    s.add_argument("--type", required=True)
    s.add_argument("--time")
    s.add_argument("--score", type=int, choices=range(1, 6))
    s.add_argument("--good", action="append")
    s.add_argument("--fix", action="append")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("advice")
    s.add_argument("--date", default=today())
    s.add_argument("--summary")
    s.add_argument("--training", action="append")
    s.add_argument("--diet", action="append")
    s.set_defaults(fn=cmd_advice)

    s = sub.add_parser("photo")
    s.add_argument("src")
    s.add_argument("--date")
    s.add_argument("--time")
    s.add_argument("--kind", choices=["meal", "body", "label", "other"], required=True)
    s.add_argument("--meal")
    s.add_argument("--desc", required=True)
    s.set_defaults(fn=cmd_photo)

    s = sub.add_parser("show")
    s.add_argument("date", nargs="?", default=today())
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("stats")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--date", default=today())
    s.set_defaults(fn=cmd_stats)

    sub.add_parser("build").set_defaults(fn=cmd_build)

    a = p.parse_args()
    a.fn(a)
    if a.cmd in ("meal", "body", "photo", "exercise", "review", "advice"):
        cmd_build(a)


if __name__ == "__main__":
    main()
