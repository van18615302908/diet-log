---
name: diet-log
description: 用户的饮食记录系统（项目目录 $DIET_LOG_DIR，默认 ~/Desktop/diet-log）。用户说吃了什么、发餐食照片/营养成分表/体脂秤截图、报体重饮水睡眠、说做了什么运动，或者问「今天吃得怎么样 / 蛋白质够吗 / 明天吃什么练什么 / 最近体重趋势」时触发。由 Claude 拆分食物、估算 15 项营养素、给照片命名归档、点评每一餐、写第二天的饮食和训练建议，并更新本地看板。Trigger when the user logs food, body metrics, exercise or meal photos, or asks about their diet.
---

# 饮食记录

项目目录 ROOT = `$DIET_LOG_DIR`，没设就用 `~/Desktop/diet-log`。

**第一步永远是读 `ROOT/CLAUDE.md`**，那里有完整规则：记录饮食、运动、身体指标、照片归档、点评、明日建议、回答问题。
再读 `ROOT/profile.json` 的 `about` 字段，了解用户的情况和目标。

所有命令都在 ROOT 下运行：`cd "$ROOT" && python3 diet.py ...`

| 用户说的 | 做什么 |
|---|---|
| 吃了什么 / 发餐食照片 | 看图 → `diet.py meal` 录入（15 项营养素）→ `diet.py photo` 归档 → `diet.py review` 点评 |
| 营养成分表照片 | 以标签数据为准（`src: "label"`），照片按 `--kind label` 归档 |
| 体脂秤截图 / 报体重 | `diet.py body`（截图上有日期就记到那天）→ 照片按 `--kind body` 归档 |
| 做了什么运动 | `diet.py exercise --met/--kcal --parts` |
| 当天最后一餐录完 | `diet.py advice` 写明天的训练和饮食建议 |
| 问问题 | 先 `diet.py show` / `diet.py stats --days 7` 读真实数据再回答 |

如果 ROOT 不存在，说明这台机器还没装，告诉用户先 clone 仓库，别自己凭空建文件。
