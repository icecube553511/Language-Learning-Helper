# weighted-review-v1 复习契约

`Words_Learnt` 是独立于词库和 `lexi-sm2-v1` 排期的本地已学词数据库。用户在“学习”中首次完成四档评分后，词条才进入该数据库；“学习”只展示尚未进入 `Words_Learnt` 的词条，“复习”只展示其中的词条。

## 权重

权重是复习会话的相对抽样权重，使用 IEEE-754 double 持久化：

| 评分 | 学习后的初始权重 | 复习后的权重 |
| --- | ---: | ---: |
| `again`（忘记） | `1.00` | 保持原值 |
| `hard`（模糊） | `0.80` | 保持原值 |
| `good`（认识） | `0.20` | `0.20` |
| `easy`（很熟） | `0.05` | `0.05` |

权重与 `lexi-sm2-v1` 的 interval/ease 分开保存。四档评分仍按 `scheduler-v1.md` 更新 `dueAtUtc`；权重只控制主动复习会话的入选频率，不修改调度算法。

## 会话与提醒

- 主动复习从全部已学词中按权重无放回抽样；同一会话内一个词最多出现一次。
- 到期提醒聚合 `dueAtUtc <= nowUtc` 的已学词，并在应用运行期间每分钟刷新；提醒不会自动开始或消费复习会话。
- 设置项 `reviewBatchSize` 默认 `20`。存在已学词时，有效值夹在 `1..learntCount`；没有已学词时开始按钮和数量控件禁用，持久值仍至少为 `1`。
- 新增数据库每条记录至少包含 `wordId`、`weight`、`learntAtUtc`、`lastReviewedAtUtc` 和 `reviewCount`。
- 从旧版本迁移已有排期但没有 `Words_Learnt` 记录的词时，使用中性权重 `0.20`，以免丢失既有学习进度。

## 持久化标识

- Windows：应用数据目录中的 `Words_Learnt.json`。
- Android：应用私有 `SharedPreferences` 数据库 `Words_Learnt`。
