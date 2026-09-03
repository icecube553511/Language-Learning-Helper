# 冰子形象状态契约 v1

`pet-appearance-v1` 定义冰子新增形象的纯业务选择规则。它与
`pet-companion-v1` 的运动 reducer、`pet-vitals-v1` 的持久化成长状态相邻但
独立：位置、速度、滞空/静止计时、双击事件和当前形象选择都是瞬态状态，不得
写入词库、学习进度或设置。

## 洋葱边界

- `domain` 只接收落地冲击速度、滞空时长、静止时长、运动状态、可选饱食度和
  已判定的双击事件，并返回形象 key。它不读取文件、不调用 `listdir`、Tkinter
  或 Android SDK。
- `application` 在未来接入 `pet-vitals-v1` 时提供饱食度事实；它不负责选择
  图片文件。
- `infrastructure`/构建工具发现并校验源素材，生成稳定的运行资源清单。
- `presentation` 负责手势、计时、真实落地事件和将形象 key 映射为 Tkinter/
  Compose 资源。当前资源清单不完整，因此 presentation 必须继续渲染现有正常
  冰子，不启用新增形象触发器。

源素材只放在 `shared/assets/branding/pet_states/`；工具生成的运行资源位于
`shared/assets/pets/states/`。平台不能把源目录直接当作运行时资源目录。

## 触发事实

形象选择器接收以下瞬态事实：

1. `landingImpactSpeed >= 437.5` 逻辑单位/秒表示较大落地速度，触发 `pain`。
   该阈值复用现有 `pet-companion-v1` 的 hard landing 阈值；落地事件必须由
   运动 reducer 的真实连续碰撞速度产生，不能使用落地后的弹跳速度倒推。
2. `airborneSeconds >= 3.0` 触发 `scared`。滞空包含 `dragging`、`fall`、
   `fling` 以及长时间下落，计时在合法承载面稳定接触后清零。
3. `moving == false` 且 `stationarySeconds >= 30.0` 触发 `sleep`。它不复用
   现有约 384 ms 的 `idleTicks` 停留计时。
4. `moving == false` 且收到快速双击事件触发 `happy`。快速窗口暂定为两次
   点击间隔不超过 `300 ms`；happy 文件按 `happy<number>.png` 的数字后缀升序
   形成完整组，选择索引由外层随机源注入，domain 不扫描目录。
5. 当可选的 `satiety` 已提供且 `satiety <= 0.0` 时触发 `hungry`。这条是对
   用户“饱食度为 0”的严格解释，不等同于 `pet-vitals-v1` 的派生 hunger
   `hungryBelow=30.0`。

实现应将非有限计时/速度视为不满足条件；饱食度由 `pet-vitals-v1` 的边界值
保证，若未接入该数据源则不评估 hungry 条件。

## 优先级

推荐的确定性顺序是：

```text
pain > scared > hungry > sleep > happy > normal
```

这满足用户明确给出的“第 1、2 条大于第 5 条大于其他条”。用户没有规定第 1
条与第 2 条的相互顺序，本版本采用 `pain > scared` 作为推荐决策并已写入
golden vectors；在启用真实资源前需要用户确认这一点。若未来新增形象状态而未
定义优先级，必须先在本契约和 golden vectors 中补充优先级，不得由单端自行决定。

当高优先级状态对应文件缺失时，选择器跳过该选择并继续检查较低优先级；如果
没有任何可用的新形象文件，则返回 `normal`。整体功能只有四个固定状态文件和
至少一个 happy 文件都存在、资源工具生成清单、两端 manifest 同步且
`pain`/`scared` 的优先级得到确认后才可标记为 enabled。当前清单为空且优先级
尚未确认，能力为 disabled。

## 资源清单

开发者添加 PNG 后运行：

```powershell
python tools/prepare_pet_appearance_assets.py
```

工具负责校验 PNG 签名、按数字后缀排序 happy 组、复制运行资源并写入
`shared/assets/pets/states/manifest.json`。三端构建只能消费运行目录/清单。
生成资源 manifest 的 `enabled` 只有完整资源组才为 `true`；它不代表产品优先级已经确认。
启用行为还必须确认 `priorityConfirmed`，并同步更新
`shared/contracts/parity.json`、`windows/platform-contract.json`、
`android/platform-contract.json`、两端 presentation 资源映射和测试。

完整的边界、优先级、缺失资源和 disabled vectors 见
`pet-appearance-golden-v1.json`。
