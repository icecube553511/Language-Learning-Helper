# LexiTrack 项目说明

## 技术栈

- Windows：Python 3.10+、Tkinter、JSON 本地仓储。
- Android：Kotlin/JVM 17、Gradle 多模块、Jetpack Compose、SharedPreferences。
- 共享：shared/contracts 的版本化契约与 shared/content/catalog.json。

## 架构规则

- 遵循洋葱架构：presentation -> application -> domain；infrastructure 只实现内层端口；组合根负责装配。
- 默写 worksheet exporter、DOCX/PDF writer 属于 infrastructure；Windows file dialog 与 Android SAF/file picker 属于 composition root。
- domain 和 application 不得导入 Tkinter、Android SDK、文件系统或具体持久化类。
- Windows 与 Android 的业务语义、数据字段、默认值、边界和错误码必须同步；共享契约是单一事实来源。
- 每个功能切片同时更新 Windows、Android、共享契约和测试，并在同一提交中留下记录。
- 学习顺序默认 `random`，可选 `alphabetical`；学习、复习和提醒词汇组是三个独立的多选设置。
- 内置词条 memberships 只读；CSV 导入和批量标签编辑可更新用户词条，程序标签编辑对内置词条也只写本地 tag override。
- 默写是可打印 worksheet，不是交互答题；preview 必须与 DOCX/PDF 输出共享同一 `Document` model。`dictation-export-v1` 中的 A4 portrait、字段挖空、词性、例句边界替换、随机无放回选择和 evaluated 规则是单一事实来源。
- 例句英文词语气泡遵循 `word-bubble-v1`：token 归一化、词性/中文解析、九层栈、祖先保留和外部点击关闭由共享契约约束；栈状态仅存在 presentation，不得持久化。
- 导出后的 `evaluated` 只能作为本地 tag override；UI 仅允许 `cet4`、`cet6`、`gk`、`zk`、`evaluated`，不得创建其他 tag，且不得修改内置 catalog。
- Android 后台提醒由 AlarmManager/Receiver/Notification 外层适配器负责，application/domain 不得依赖 Android SDK。
- 保留工作区中已有的用户修改；不要使用破坏性还原命令覆盖它们。

## 代码风格

- Python 使用 snake_case、类型注解和标准库；Kotlin 使用 PascalCase 类型与 camelCase 成员。
- 时间统一使用 UTC epoch seconds，并通过时间端口注入以便测试。
- 词条 ID 使用 Unicode NFKC + trim + casefold/lowercase 规范化。
- 导入不得覆盖重复词条或学习进度；异常应转换为稳定的逐行错误报告或明确用户消息。

## 测试与构建

~~~powershell
python tools/verify_sync.py
python -m unittest discover -s .\\windows\\tests -v
python .\\windows\\main.py --smoke-test --data-dir .\\windows\\.smoke-data
.\\android\\gradlew.bat -p .\\android test lintDebug assembleDebug
~~~

Android 构建使用 JDK 17 与 SDK 35；Windows 打包前安装 windows/requirements-build.txt。

## 关键目录

- shared/contracts/：跨端 schema、算法、CSV 和能力门禁。
- shared/contracts/dictation-export-v1.md 与 dictation-export-golden-v1.json：可打印默写 worksheet 的格式和 golden vectors。
- shared/contracts/word-bubble-v1.md 与 word-bubble-golden-v1.json：例句递归词语气泡的共享交互语义。
- shared/content/：生成的内置词库，不手工编辑大 JSON；使用 tools/build_catalog.py 更新。
- shared/assets/branding/：Windows 与 Android 共用的 canonical 品牌源资产，平台图标资源由此派生。
- windows/{domain,application,infrastructure,presentation}/：Windows 四层。
- android/{domain,application,infrastructure,presentation}/：Android 四层；android/app 是组合根。
- .github/workflows/ci.yml：双端 CI 和可追踪构建产物。

## Git 工作流

沿用短前缀提交信息（feat、fix、test、docs、build）。提交前运行同步校验和两端测试；功能提交应包含两端及共享契约，并推送到 GitHub 以保留审计记录。

## 跨端协作与同步约束（新增）

跨端功能由 Windows 与 Android 两个互不重叠的实现并发完成，共享契约、`tools/verify_sync.py` 与编目/品牌源资产只读。任何行为变更必须同时落地 Windows 与 Android（除非明确声明仅限单端），并：

- 共享逻辑优先放入 `shared/contracts/`，再同步更新三个平台清单；可自动化的对齐点写入 `tools/verify_sync.py`。
- 领域规则保持平台无关，瞬态 UI 状态不进入持久化；presentation 不得直接读取 catalog 或存储文件。
- 改动须附带两端回归测试，并在同一提交/PR 中推送到 GitHub 留痕。当前已确认的跨端行为：复习完成后“总览”复习提醒自动消失、复习开始按钮居中放大、默写手选支持整行点选与拖拽范围多选、默写预览支持滚轮上下翻页。
- 单词气泡（`word-bubble-v1`）必须同步：已知词弹窗同时展示中文释义与至少三组双语例句；例句必须是“英文+简体中文”双语搭配，缺少简体中文时以“（暂无中文释义）”占位补全；弹窗尺寸恰好足以完整展示单词、音标、词性和全部双语例句（不得过大或裁剪）；关闭按钮或标题栏叉号关闭“当前气泡及其子级”而非保持打开。团队结构与职责见 `docs/agent-team.md`。
- 词库分组浏览器（`vocabulary-groups-v1`）必须同步：进入“词库”先展示词书分组（全部、CET-4（四级）、CET-6（六级）、中考/zk、高考/gk、自定义），点击分组后查看该组单词；分组由词书/标签归一化后推导，`custom` 仅由 `CUSTOM` 词书决定；分组顺序固定且空分组仍显示；分组选择为瞬态 presentation 状态不持久化；搜索在分组内过滤，未选分组时始终全局搜索；保留现有词库搜索、CSV 导入、批量标签、下次复习列与 1000 条上限。默写纸移除顶部“四级/六级/自定义”勾选行，分组浏览器作为随机与手选的统一范围选择器：随机模式点击分组（或“全部”）设置取样范围，手选模式点击分组后在该组内勾选且已勾选词条跨分组保留。
