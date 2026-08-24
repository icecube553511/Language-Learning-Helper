# lexi-sm2-v1 调度契约

所有时间以 UTC epoch seconds 持久化。每日统计才按设备本地时区分组。领域算法接收显式 `reviewedAtUtc`，不得直接读取系统时钟。

初始状态：`intervalDays=0`、`ease=2.5`、`repetitions=0`、`lapses=0`、`state=new`。

| 评分 | 新间隔 | ease 变化 | 状态 |
| --- | --- | --- | --- |
| Again | `10 / 1440` 天 | `max(1.3, ease - 0.20)` | `relearning`，repetitions 归零，lapses + 1 |
| Hard | 首次为 1 天，否则 `max(1, interval * 1.2)` | `max(1.3, ease - 0.15)` | 首次 `learning`，其后 `review` |
| Good | 首次为 3 天，否则 `interval * ease` | 不变 | `review` |
| Easy | 首次为 7 天，否则 `interval * ease * 1.3` | `min(3.0, ease + 0.15)` | `review` |

`dueAtUtc = reviewedAtUtc + intervalDays * 86400`。浮点计算使用 IEEE-754 double，不在领域层截断；展示层可按本地日期格式化。

记忆保持率展示使用 `retention = exp(-elapsedDays / max(intervalDays, 1/144))`。未来负载以每个词的 `dueAtUtc` 落入本地日期桶计算。

