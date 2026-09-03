# LexiTrack 项目说明

> **Agent 启动门禁（2026-09 更新）**：任何检查、修改、生成、测试或提交之前，
> 必须完整阅读 `ARCHITECTURE.md`，再阅读 `CODEBASE_ONBOARDING.md` 和任务涉及的
> `shared/contracts/` 契约及存在的 golden vectors。以下内容是执行摘要，不能替代
> 架构设计。

## 技术栈

- Windows：Python 3.10+、Tkinter、JSON 本地仓储、DPAPI、PyInstaller。
- Android：Kotlin 2.1.0/JVM 17、Gradle 多模块、Jetpack Compose、
  SharedPreferences、Android Keystore。
- 共享：版本化契约/golden vectors、生成的 catalog、canonical 品牌资产和
  parity manifest。

## 不可破坏的架构规则

- 依赖只向内：presentation -> application -> domain；infrastructure 实现内层
  端口；平台 API、权限和文件选择留在平台入口/adapter。
- Domain 不得依赖 Tkinter、Android SDK、文件系统、具体仓储或平台资源。
  Application 不得创建具体持久化、UI 或平台对象。
- Presentation 不得读取 catalog/存储文件或创建 repository。Windows 当前存在的
  filedialog/直接写文件和 repository 查询是历史债务，不是新代码先例。
- Android `MainActivity` + `AppContainer` 是前台入口；`ReminderReceiver` 是后台
  通知入口。两者都只能在边缘装配/调用用例。
- 导航、搜索、未保存的页面选择、气泡栈、宠物运动、翻页帧和评分光球保持瞬态。
  只有契约定义的可恢复默写选择可进入加密草稿；复习排期、设置、已学词权重、
  恢复标记和宠物成长经端口持久化。
- 排期与 `Words_Learnt` 是两个物理存储；savepoint 只提供进程内补偿，不得描述为
  跨文件或跨崩溃事务。
- 默写 preview 与 DOCX/PDF writer 共享同一 domain `Document`；preview 属于
  presentation，writer 属于 infrastructure，保存 picker 属于平台入口。
- 可选草稿同步默认禁用，只允许 HTTPS 并由组合入口注入配置；词库、学习进度和
  导出文件永不进入同步端口。

## 跨端契约

- 行为细节以 `shared/contracts/*-v1.md` 及存在的配套 golden JSON 为准。
- `shared/contracts/parity.json` 汇总版本、参数和 capability；
  `windows/platform-contract.json` 与 `android/platform-contract.json` 必须同步。
- 行为变化先更新 shared 语义，再在同一 branch/PR 完成 Windows、Android 和双端
  测试。只有请求明确声明时才允许单平台例外。
- 可自动化的 parity 必须扩展 `tools/verify_sync.py`；脚本通过不代表完整分层合规。

## 生成文件

- 不手改 `shared/content/catalog.json` 或 `catalog-manifest.json`；使用
  `python tools/build_catalog.py`。
- 不手改 `shared/assets/pets/bingzi*.png`；使用
  `python tools/prepare_pet_asset.py`。
- 冰子形象源 PNG 只放 `shared/assets/branding/pet_states/`，再运行
  `python tools/prepare_pet_appearance_assets.py` 生成 runtime 目录。
- 生成物、版本、三份 manifest 和相关测试必须一起提交。

## 代码约定

- Python 使用 snake_case、PascalCase 类型、类型注解；Kotlin 使用 PascalCase
  类型与 camelCase 成员。宠物 parity 中既有 snake_case alias 仅为兼容。
- 词条 ID 使用 Unicode NFKC + trim + casefold/lowercase；membership 使用集合
  语义，Windows 旧 wire shape 的 `level` 字符串只是兼容层。
- 时间使用 UTC epoch seconds。新领域 API 必须显式接收时间，不直接读取系统钟。
- 导入不得覆盖重复词条或学习进度；边界失败转为稳定错误码或明确用户消息。
- 保留工作区已有修改，不使用破坏性还原命令。

## 验证与构建

从仓库根目录执行：

```powershell
python -m pip install -r .\tools\requirements-content.txt
python .\tools\verify_sync.py
python -m pip install -r .\windows\requirements-build.txt
python -m unittest discover -s .\windows\tests -v
python .\windows\main.py --smoke-test --data-dir .\windows\.smoke-data
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

Android 使用 JDK 17 与 SDK 35。Windows 打包运行
`powershell -ExecutionPolicy Bypass -File .\windows\build.ps1`。

## Git 交付

沿用 `feat:`、`fix:`、`test:`、`docs:`、`build:` 等短前缀。提交前运行完整门禁；
提交并推送功能分支，创建 GitHub PR，在 PR 中记录架构影响、平台范围和实际验证
结果。不要交付未推送的 feature work。
