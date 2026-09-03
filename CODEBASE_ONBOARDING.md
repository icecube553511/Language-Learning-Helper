# LexiTrack Agent 两分钟入门

本文件是代码导航，不是架构规范。开始任何仓库工作前，先完整阅读
`ARCHITECTURE.md`；随后用本指南定位入口，并阅读任务涉及的
`shared/contracts/` 契约与配套 golden vectors（如有）。

## 项目是什么

LexiTrack 是同时交付 Windows 与 Android 的离线英语学习 monorepo。两端分别
实现词库、学习/复习、提醒、默写导出、递归词语气泡与冰子陪伴功能；共享的是
版本化契约、测试向量、生成内容和源资产，而不是 UI 或运行时代码。

## 技术栈

| | Windows | Android |
|---|---|---|
| 语言/UI | Python 3.10+、Tkinter | Kotlin 2.1.0、Jetpack Compose |
| 构建 | PyInstaller 6.21.0 | Gradle 8.10.2、AGP 8.8.2、JDK 17 |
| 平台 | Windows 10/11 x64 | minSdk 26、target/compileSdk 35 |
| 持久化 | JSON 文件、Windows DPAPI | SharedPreferences、Android Keystore |
| 测试 | `unittest` + GUI smoke | Kotlin/JUnit + Robolectric |
| CI | GitHub Actions / Python 3.13 | GitHub Actions / Temurin 17 |

DOCX/PDF 分别使用 `python-docx`、ReportLab 或平台 writer。Android 当前没有
Room/SQLite；SharedPreferences 中保存 JSON 或标量。

## 一眼看懂目录

```text
shared/contracts/       行为规范、golden vectors、parity manifest
shared/content/         生成的只读 catalog 与许可证
shared/assets/          canonical 源资产和生成的运行资源
tools/                  catalog/资源生成器与跨端同步门禁
windows/domain/         平台无关领域模型与纯规则
windows/application/    LearningService、用例和端口
windows/infrastructure/ JSON/CSV/导出/加密/可选 HTTPS adapters
windows/presentation/   Tkinter UI、气泡、宠物与视觉效果
android/domain/         纯 JVM 领域模块
android/application/    纯 JVM 用例与端口
android/infrastructure/ Android 存储、CSV、导出、提醒与同步 adapters
android/presentation/   Compose UI、ViewModel 与视觉状态
android/app/            Activity、SAF 和前台 composition root
```

依赖只向内：`presentation -> application -> domain`；`infrastructure` 实现
application/domain 端口；`main.py`、`:app` 与后台 `ReminderReceiver` 在平台边缘
装配具体实现。完整规则与已知例外见 `ARCHITECTURE.md`。

## 关键入口

| 想理解什么 | 从这里开始 |
|---|---|
| Windows 启动与依赖装配 | `windows/main.py` 的 `build_app` |
| Windows 业务用例 | `windows/application/services.py` 的 `LearningService` |
| Windows UI | `windows/presentation/app.py` 的 `LexiTrackApp` |
| Android 前台装配 | `android/app/.../AppContainer.kt`、`MainActivity.kt` |
| Android 页面状态 | `android/presentation/.../MainViewModel.kt` |
| Android UI | `android/presentation/.../LexiTrackApp.kt` |
| Android 用例 | `android/application/.../LearningUseCases.kt`、`DictationUseCases.kt` |
| Android 后台提醒 | `android/infrastructure/.../ReminderReceiver.kt` |
| 跨端版本/capability | `shared/contracts/parity.json` 与两端 `platform-contract.json` |
| CI | `.github/workflows/ci.yml` |

Android 表中的 `...` 均从 `src/main/kotlin/com/lexitrack/learning/` 继续。

## 两条主数据流

```text
学习/评分
UI -> Service/UseCase -> repository ports -> domain scheduler/reward rules
   -> review store + learnt-word/vitals store -> UI state

默写
UI selection -> application -> domain DictationDocument
   -> presentation preview
   -> infrastructure DOCX/PDF bytes -> platform picker -> user file
```

评分涉及两个物理存储，失败时只有进程内 savepoint 补偿，不是 crash-atomic
事务。Preview 属于 presentation，writer 属于 infrastructure，文件选择应属于平台
入口；Windows 当前 picker/最终写出仍是已记录的历史例外。CSV 导入采用类似路径：
picker -> UI boundary -> use case -> CSV/repository ports -> parser/storage -> 逐行报告。

## 按任务找位置

| 任务 | 必看/通常修改 |
|---|---|
| 改调度、复习或字段语义 | 对应 shared contract/golden -> 双端 domain/application -> 双端测试 |
| 改页面交互 | 双端 presentation；先确认状态是否必须保持瞬态 |
| 改本地存储 | 双端 application port + infrastructure，保留 wire 兼容 |
| 改 CSV/默写/气泡/冰子 | 先读对应 `*-v1.md` 和存在的 golden/fixtures |
| 改 capability 或共享参数 | parity + 两端 platform manifest + `verify_sync.py` |
| 更新词库 | `tools/build_catalog.py`，不要手改 `shared/content/*.json` |
| 更新冰子资源 | `tools/prepare_pet_asset.py` 或 `prepare_pet_appearance_assets.py` |
| 添加测试 | `windows/tests/` 或 Android 各模块 `src/test/` |

## 工作协议

1. 先读 `ARCHITECTURE.md` 与相关契约，确认改动属于哪一层、哪些状态可持久化。
2. 行为变化先更新 shared 语义，再同时实现 Windows 与 Android；单平台例外必须由
   请求明确授权。
3. 更新一份 shared parity 与两份 platform manifest；可自动检查的同步规则写入
   `tools/verify_sync.py`。
4. 添加两端风险相称的测试，运行完整门禁。
5. 保留无关改动，提交并推送同一分支，创建 GitHub PR 并记录验证结果。

## 完整验证

从仓库根目录运行：

```powershell
python -m pip install -r .\tools\requirements-content.txt
python .\tools\verify_sync.py
python -m pip install -r .\windows\requirements-build.txt
python -m unittest discover -s .\windows\tests -v
python .\windows\main.py --smoke-test --data-dir .\windows\.smoke-data
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

Windows 打包运行 `powershell -ExecutionPolicy Bypass -File .\windows\build.ps1`；
Android debug APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。

## 容易踩错的地方

- `verify_sync.py` 是契约、内容、资产和 manifest 门禁，不是完整架构 linter，也
  不能替代双端测试/build/smoke。
- Windows presentation 仍有历史文件 IO 和直接 repository 查询；不要继续复制。
- Android `ReminderReceiver` 是合法的后台平台入口；草稿同步编排仍有一部分留在
  ViewModel，新增流程应进入 application。
- Windows 兼容旧数据时仍写 `level` 字符串，但领域视图的 membership 是集合。
- Python 模块使用以 `windows/` 为根的顶层导入，应从仓库根按文档命令运行。
- Kotlin 通常使用 PascalCase/camelCase；宠物 parity 代码保留少量明确标注的
  snake_case alias，不要把它推广到新 API。
