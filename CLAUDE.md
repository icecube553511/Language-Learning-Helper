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
- shared/content/：生成的内置词库，不手工编辑大 JSON；使用 tools/build_catalog.py 更新。
- shared/assets/branding/：Windows 与 Android 共用的 canonical 品牌源资产，平台图标资源由此派生。
- windows/{domain,application,infrastructure,presentation}/：Windows 四层。
- android/{domain,application,infrastructure,presentation}/：Android 四层；android/app 是组合根。
- .github/workflows/ci.yml：双端 CI 和可追踪构建产物。

## Git 工作流

沿用短前缀提交信息（feat、fix、test、docs、build）。提交前运行同步校验和两端测试；功能提交应包含两端及共享契约，并推送到 GitHub 以保留审计记录。
