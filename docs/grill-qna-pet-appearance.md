# 冰子形象状态 Grill Q&A

本清单按 `grill-me`/`grilling` 的要求整理为一次完整的自问自答。答案以
仓库现有代码、`ARCHITECTURE.md`、`CLAUDE.md` 和双端实现为依据；“推荐答案”
是当前实现采用的默认值，“理由”记录选择原因。没有 PNG 时，本清单描述的是
可审计的契约和禁用状态，不代表新增形象已经显示在客户端中。

## Q&A

### Q1：这次交付的真实目标是什么？

**推荐答案：** 先建立跨 Windows/Android 的形象状态契约、领域选择器、资源
源目录、生成工具、构建接入和自动门禁；在素材齐全并确认优先级前，客户端继续
显示现有 normal 冰子。

**理由：** 需求明确说明当前没有 `pain.png`、`sleep.png` 等文件。先完成可
验证的边界，避免空资源或单端临时实现改变现有 UI。

### Q2：新增代码应该放在哪一层？

**推荐答案：** 选择规则放在 `windows/domain/pet_appearance.py` 和
`android/domain/.../PetAppearance.kt`；素材发现和 PNG 校验放在
`tools/prepare_pet_appearance_assets.py`；未来的资源映射、计时、手势和渲染
放在各端 presentation；application 只在未来接入饱食度端口时传递事实。

**理由：** 这保持 `presentation -> application -> domain` 的依赖方向，且
domain 不依赖 Tkinter、Android SDK、文件系统或图片对象。

### Q3：开发者应该把 PNG 放在哪里？

**推荐答案：** 只放在 `shared/assets/branding/pet_states/`，其中固定状态文件
在目录根部，happy 组放在 `happy/` 子目录。

**理由：** 该目录是跨端 canonical 源素材目录，符合现有品牌源资产理念；平台
代码不直接读取它。

### Q4：客户端和构建系统使用哪个目录？

**推荐答案：** 运行时只使用工具生成的 `shared/assets/pets/states/`，不能把
源素材目录当作运行目录。工具同时生成 `manifest.json`。

**理由：** 源资产与派生资源分离，Windows 打包和 Android Gradle 构建都能消费
稳定、已校验的产物，避免两端各自扫描目录。

### Q5：固定资源文件名是什么？

**推荐答案：** 使用 `pain.png`、`scared.png`、`sleep.png`、`hungry.png`，
以及 `happy/happy1.png`、`happy2.png` 等正整数后缀命名的 happy 组。

**理由：** 文件名是契约键，工具可以拒绝拼写错误，并按数字而不是字典序排序
`happy2` 与 `happy10`。

### Q6：高速落地如何定义？

**推荐答案：** 使用运动 reducer 真实连续碰撞产生的落地冲击速度；速度大于或
等于 `437.5` 逻辑单位/秒时选择 `pain`。

**理由：** `437.5` 已是 `pet-companion-v1` 的 hard landing 阈值，复用它可
避免从落地后的弹跳速度倒推，且边界行为能在两端保持一致。

### Q7：滞空如何定义？

**推荐答案：** `airborneSeconds >= 3.0` 时选择 `scared`。拖拽、`fall`、
`fling` 和持续下落均属于滞空；在合法承载面稳定接触后清零。

**理由：** 需求明确把长按拖拽至空中和长时间下落算作滞空，不能只检查一个
`PetMode`。

### Q8：静止和现有 idle 停顿是否相同？

**推荐答案：** 不同。`moving == false` 且连续静止达到 `30.0s` 才选择 `sleep`；
现有约 `384ms` 的 `idleTicks` 只服务落地后的运动状态转换。

**理由：** 复用 `idleTicks` 会让睡眠几乎立即触发，改变现有物理行为。

### Q9：快速双击如何处理？

**推荐答案：** 只有不在运动状态且两次点击间隔不超过 `300ms` 时产生
`rapidDoubleTap` 事实，选择 `happy`；双击识别属于 presentation，domain 只
接收已经判定的事件。

**理由：** 输入设备和时钟是平台边界，领域规则不应直接调用 Tkinter 或 Android
事件 API。

### Q10：happy 组如何随机切换？

**推荐答案：** 资源工具扫描并按数字后缀升序生成完整列表，随机索引由外层
注入，domain 只按索引选取。索引以组长度取模，负索引也保持确定性。

**理由：** 这满足“需要 listdir 获取完整组”的提示，同时把文件系统访问留在
工具/平台边缘，测试可以注入固定索引而不依赖随机数。

### Q11：饱食度为多少时触发 hungry？

**推荐答案：** 严格使用已提供且有限的 `satiety <= 0.0`；没有接入饱食度时不
评估 hungry。它不等同于 `pet-vitals-v1` 的派生 `hungryBelow = 30.0`。

**理由：** 需求写的是“饱食度为 0”，扩大为低于 30 会把成长系统的派生状态
误当成形象触发条件。

### Q12：冲突时的优先级是什么？

**推荐答案：** 当前采用 `pain > scared > hungry > sleep > happy > normal`。

**理由：** 这满足“第 1、2 条大于第 5 条大于其他条”，并为可执行的选择器提供
确定顺序。

### Q13：哪一项仍需产品确认？

**推荐答案：** 需要确认第 1 条与第 2 条的相互顺序，即 `pain` 是否确实高于
`scared`。本版本记录为推荐值 `pain > scared`，在真实素材启用前确认。

**理由：** 用户只规定了两者都高于第 5 条，没有明确两者之间的关系；静默猜测
会让单端行为产生不可见分歧。

### Q14：缺少某一个文件时是否关闭全部功能？

**推荐答案：** 选择器逐项跳过缺失文件并继续检查低优先级；但整体新形象能力
只有四个固定状态文件和至少一个 happy 文件都存在、且 `pain`/`scared` 顺序已
确认时才允许整体能力标记 `enabled`。当前全部缺失且顺序未确认，所以能力为
`disabled`，渲染回退到现有 normal 资源。

**理由：** 领域选择器可以独立测试，产品开关又不会在资源不完整时显示半成品。

### Q15：新状态是否持久化？

**推荐答案：** 不持久化。位置、速度、落地冲击、滞空计时、静止计时、双击事件
和当前形象都是瞬态；饱食度若接入则仍由 `pet-vitals-v1` 的既有持久化模型管理。

**理由：** 表情是渲染结果，不应写入学习进度、词库、设置或 `VocabularyEntry.tags`。

### Q16：Windows 和 Android 是否可以先后实现？

**推荐答案：** 不可以。共享契约、Windows domain/test、Android domain/test、
三份 manifest、资源工具和构建接入在同一分支、同一提交和同一 PR 中完成；平台
实现可由 agent team 并行审计，但不能形成平台孤岛。

**理由：** 仓库工作协议要求每个行为变更双端同步，并通过共享 golden vectors
和 `verify_sync.py` 阻止漂移。

### Q17：如何确保 domain 不读取资源目录？

**推荐答案：** `PetAppearanceAssets` 只接收已经发现的文件名集合；工具或平台
边缘负责 `listdir`/清单解析，domain 不导入路径库、Tkinter 或 Android 类。

**理由：** 资源发现是 infrastructure/工具职责，纯选择器可以在两端用同一组事实
回放而不依赖运行环境。

### Q18：素材添加后的操作顺序是什么？

**推荐答案：** 开发者把 PNG 放入源目录，运行
`python tools/prepare_pet_appearance_assets.py`，检查 manifest，再同步更新
golden/三份 manifest、presentation 映射和双端测试，最后运行全部门禁。

**理由：** 运行资源是生成物，不能手工维护；启用行为必须经过资源、契约、代码
和测试的同一 PR 审查。

### Q19：哪些测试必须通过？

**推荐答案：** 至少包括共享同步校验、Windows 全量 unit test 与 smoke test、
Android `test lintDebug assembleDebug`，以及两端形象 domain 对 golden vectors
的回放。

**理由：** 这同时覆盖跨端语义、平台编译资源和现有客户端不回归；Android 使用
JDK 17。

### Q20：每次操作如何在 GitHub 留痕？

**推荐答案：** 变更写入短前缀 Git commit，推送 feature branch，并在 GitHub PR
中记录基线、契约版本、资源是否启用、测试命令和结果；不交付未推送的功能代码。

**理由：** PR 是 Windows/Android 同步和未来素材启用的审计入口，也能避免本地
工作树成为唯一事实来源。

### Q21：未来加入未定义优先级的新形象怎么办？

**推荐答案：** 先暂停启用，在 `pet-appearance-v1` 契约、golden vectors、
三份 manifest 和本 Q&A 中补充排序及冲突规则，再实现两端映射与测试。

**理由：** 未定义优先级时由单端自行决定会破坏跨端一致性；本条是明确的漂移
门禁。

## 锁定范围

### Reframe

这次不是把几个图片文件直接挂到宠物身上，而是先把“瞬态事实 -> 领域决策 ->
生成资源 -> 双端渲染”的边界固定下来，让未来的形象扩展不会反向污染学习数据。

### Goal

建立可审计的 `pet-appearance-v1` 跨端形象状态基础设施；在 PNG 素材和
`pain > scared` 顺序确认前保持新形象能力 disabled。

### Decisions locked

- 源素材目录为 `shared/assets/branding/pet_states/`。
- 生成运行资源目录为 `shared/assets/pets/states/`，由工具维护 manifest。
- 高速落地阈值为 `437.5`，滞空阈值为 `3.0s`，静止阈值为 `30.0s`，双击窗口为 `300ms`。
- hungry 使用严格 `satiety <= 0.0`，不使用 `hungryBelow = 30.0`。
- 推荐优先级为 `pain > scared > hungry > sleep > happy > normal`。
- 资源不完整时逐项回退，但整体 capability 为 `disabled`；当前仍显示 normal。
- 领域只消费注入的资源名和瞬态事实，不扫描文件、不持久化表情状态。
- Windows 与 Android 必须同分支、同提交、同 PR，并通过 GitHub 留痕。

### Decisions open

- 需要产品确认 `pain` 是否高于 `scared`，并把 `priorityConfirmed` 改为 `true`。
  在确认前不能把 capability 改为
  `ready`，也不能声称新形象已启用。

### What we are NOT doing

- 当前不制作、伪造或提交任何 PNG 形象文件。
- 当前不把新形象接入现有 Tkinter/Compose 渲染触发器。
- 当前不新增饱食度模型、喂食入口或存储字段。
- 当前不把瞬态计时、表情 key 或事件写入学习数据和设置。
- 当前不由任一平台单独决定优先级或直接扫描 canonical 源目录。

### Steps

1. 更新共享契约、golden vectors 和三份 parity/platform manifest。
2. 建立资源源目录、生成工具、运行 manifest 和 Android 构建资源接入。
3. 在 Windows/Android domain 实现纯选择器，并让两端测试回放同一 golden 文件。
4. 更新架构、入门、agent team 和本 Q&A 文档。
5. 运行同步校验、Windows 测试/烟测和 Android JDK 17 检查。
6. 提交、推送 feature branch，并创建记录验证结果的 GitHub PR。

### Checkpoints

- 共享契约 checkpoint：审查阈值、优先级、资源路径和 disabled 条件。
- 平台 checkpoint：确认两端 domain 测试都回放相同 vectors，且 presentation 没有
  直接读取源素材。
- 交付 checkpoint：确认工作树只包含本功能及必要文档，所有检查通过后才创建 PR。

### Branches

- 若 PNG 仍不完整：保持 manifest/capability disabled，只交付脚手架和门禁。
- 若 PNG 完整但优先级未确认：保持 disabled，提交资源审查结果，不启用触发器。
- 若 PNG 完整且优先级确认：另一个双端行为变更接入 presentation 计时、手势、
  落地事件和资源映射，并增加 UI/迁移测试。

### Drift triggers

- 任一平台出现独有阈值、优先级、默认值或资源文件名。
- domain 导入 Tkinter、Android SDK、文件系统或直接加载图片。
- presentation 直接读取 catalog、持久化文件或 canonical 源素材。
- 资源工具生成 manifest 与运行 PNG 不一致，或 `verify_sync.py` 未覆盖新字段。
- 未确认优先级却把 `petAppearanceStates` 改为 `ready`。
- Windows 与 Android 不在同一提交/PR，或代码未推送到 GitHub。
