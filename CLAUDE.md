# 饮食记录 diet-log — 规则

用户每天把「吃了什么 / 身体指标 / 照片」丢给 Claude，**由 Claude 负责结构化、估算、命名、归档**。
用户不需要手动写任何文件。看板：双击 `index.html`（每次改完数据要跑 `python3 diet.py build`）。

## 目录

```
diet-log/
├── CLAUDE.md          ← 本规则
├── profile.json       ← 个人资料（不进 git）：身高/年龄/性别/活动量/目标/about → 算每日目标
├── profile.example.json ← 模板，首次使用复制成 profile.json
├── skill/diet-log/SKILL.md ← Claude Code skill，在任何目录都能触发本流程
├── diet.py            ← CLI：记餐、记指标、归档照片、生成看板数据
├── index.html         ← 可视化看板（读 web/data.js）
├── data/days/YYYY-MM-DD.json   ← 每天一个文件，唯一数据源
├── photos/YYYY-MM/    ← 归档后的照片
└── inbox/             ← 用户可以把照片直接丢这里，Claude 归档后清空
```

## 1. 记录饮食

用户说「中午吃了一碗牛肉面加个卤蛋」这种口语 → Claude：

1. 拆成条目，补全合理份量（没说就按常见一人份，`amount` 里写明假设，如「1碗(约400g)」）。
2. 每条都要估**全部 15 个营养素**（缺字段会被看板标「数据不全」）：
   `kcal protein carb fat sat_fat fiber sugar_added`（g）· `sodium potassium calcium iron magnesium vit_c`（mg）· `vit_d vit_a`（mcg，A 用 RAE）
   不含某营养素就写 0，不要省略。整数或一位小数即可，不要假装精确。
   `sugar_added` 只算添加糖，水果/牛奶里的天然糖不算。
   用户说「一锅/一批做了多少」时，要确认吃了多少；没说就按全吃完算，并在 note 里写明。
   - 有营养成分表照片 / 包装 / 外卖标注 → 以它为准，`src: "label"`
   - 自己估的 → `src: "est"`
3. 餐次 `type` 只用：`早餐 / 午餐 / 晚餐 / 加餐 / 饮料`。没说时间就按餐次给默认（08:00/12:30/18:30），并在 note 里注明「时间估计」。
4. 写入：
   ```bash
   python3 diet.py meal --date 2026-10-05 --time 12:30 --type 午餐 \
     --items '[{"name":"牛肉面","amount":"1碗(约400g)","kcal":550,"protein":28,"carb":75,"fat":14,"src":"est"}]' \
     --note "外卖"
   ```
   同一餐补充内容 → `--append` 加到该日同 type 同 time 的那一餐。
   改错 → 直接编辑 `data/days/<date>.json`，再 build。
5. **每餐都写点评**（录完这一餐就写，不用等用户要）：
   ```bash
   python3 diet.py review --type 午餐 --score 3 \
     --good "做得好的点" --fix "下次具体怎么改：换成什么、减到多少克，并说明原因和数字"
   ```
   score 1–5。fix 必须**可执行**，比如「面饼只吃一半」「调料减到 5g」，不要写「注意少油少盐」这种空话；每条都带上原因数字（多少钠、多少饱和脂肪）。
6. 回复用户时简短报：这一餐 kcal + 三大营养素、今日累计 vs 目标、蛋白质还差多少。**不说教**。

「今天」「昨天」按用户本地时区推算日期。

## 2. 运动

```bash
python3 diet.py exercise --name 排球（主攻） --minutes 180 --met 4.5 --note "..."
```
净消耗按 (MET−1)×体重×小时 自动算，或直接 `--kcal`（有手表数据时用手表的）。
**当天热量目标 = BMR×1.2（久坐）+ 当天运动 − 500**，所以训练日目标高、休息日低（系数和缺口在 profile.json 里调）。
记录时用 `--parts 腿,肩,核心` 标出练到的部位（排球 = 腿、肩、核心），第二天的训练建议要靠这个排开。
常用 MET：排球训练/比赛 4.5（纯比赛 6）、力量训练 5、跑步 8–10、篮球 6.5。

### 给明天的建议（每天最后一餐录完后写）
```bash
python3 diet.py advice --summary "一两句总结今天" \
  --training "具体动作 组×次" --training "..." --diet "热量/蛋白目标" --diet "早餐：具体食物和克数" ...
```
- 训练：看最近 2–3 天 `exercise.parts`，避开连续练同一部位。结合 profile `about` 里的运动项目安排保养（比如排球主攻肩膀压力大，要常练肩袖和后束）。
  如果今天运动量确实少，就直说并安排练什么；运动量大就安排恢复或练没练到的部位。
- 饮食：针对今天超标或不足的营养素来定，三餐 + 加餐写到具体食物和克数，并给出明天的热量目标估算。
- 看板会在当天显示「给明天的建议」，在第二天那页显示「今天的计划（昨天定的）」。

## 3. 身体指标

```bash
python3 diet.py body --date 2026-10-05 --weight 68.2 --fat 18.5 --waist 80 --sleep 7.5 --steps 9000 --water 2000
```
只传用户给了的字段。体脂秤的其他读数用 `--set key=value`（可多次），已用的 key：`bmi visceral_fat skeletal_muscle_kg lean_mass_kg bmr_scale water_pct protein_pct bone_kg waist_hip_ratio heart_rate body_age`，看板会自动显示。
体脂秤截图上有测量日期的，记到**那一天**，不是今天。单位统一：kg / % / cm / 小时 / 步 / ml。用户说「斤」→ ÷2 换成 kg；说 lb → ×0.4536。
体重以**早上空腹**为准；若用户一天报多次，保留早上的，其他写进 note。

## 4. 照片归档

用户发来照片（拖进对话的路径、或丢在 `inbox/`）→ Claude **先看图**判断类型和内容，再：

```bash
python3 diet.py photo <源文件> --date 2026-10-05 --kind meal --desc 牛肉面 [--meal 午餐] [--time 12:30]
```

命名规则（脚本自动生成，不要手改）：
```
photos/2026-10/2026-10-05_1230_午餐_牛肉面.jpg
         └月份┘ └日期──┘ └时间┘ └餐次/类别┘ └描述┘
```
- `--kind`：`meal`(餐食，文件名用餐次) / `body`(体重秤、体脂秤、身材照) / `label`(营养成分表、包装) / `other`
- 时间优先读照片 EXIF 拍摄时间，没有才用 `--time` 或当前时间
- HEIC/PNG 自动转 jpg；重名自动加 `-2`
- 照片会挂到当天对应餐（同餐次）的 `photos` 里；body/label 类挂在当天 `photos` 里
- 照片里能读出数据的（体脂秤读数、营养成分表）→ 顺手用第 1/3 步录进去
- `inbox/` 或项目根目录里的源文件归档成功后删除；对话里拖进来的外部文件**只复制不删**

## 5. 回答问题

用户问「这周蛋白质够吗」「最近体重趋势」「晚上吃什么好」→ 先读 `data/days/` 里的真实数据再答，
可用 `python3 diet.py stats --days 7` 拿汇总。给建议要基于用户的 profile 目标和实际记录，具体到食物和克数。
不是医生，涉及疾病/药物/极端节食时直说去问医生。

用户的个人情况和目标写在 `profile.json` 的 `about` 字段里，每次给建议前先读。
用户补充了新信息（运动习惯、饮食偏好、过敏、目标变化）→ 更新 `about` 和对应参数。
每天记完报：热量 vs 当天目标，**以及哪些营养素超标或不足**（重点看蛋白质、脂肪、饱和脂肪、钠、纤维）。

## 6. 每次改完

```bash
python3 diet.py build     # 重新生成 web/data.js，看板刷新即可
```
