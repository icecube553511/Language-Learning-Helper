# 新手上路指南：LexiTrack 词程

## 概述

LexiTrack 是一个离线优先的 CET-4/CET-6 英语学习 monorepo，同时交付 Windows 桌面端和 Android 客户端。学习词库、CSV 导入规则、记忆调度算法与功能清单由 `shared/` 统一约束；学习进度和设置分别保存在本机。

## 技术栈

| 层级 | Windows | Android |
|---|---|---|
| 语言与 UI | Python 3.10+、Tkinter | Kotlin/JVM 17、Jetpack Compose |
| 应用结构 | 手工组合根 + Protocol 端口 | Gradle 多模块 + 手工组合根 |
| 持久化 | JSON 文件、独立 `Words_Learnt.json` | SharedPreferences、应用私有 JSON |
| 内容与契约 | `shared/content`、`shared/contracts` | 构建时作为 assets 引入 |
| 测试 | `unittest` | Kotlin/JUnit、Robolectric |
| CI | GitHub Actions Windows runner | GitHub Actions Ubuntu runner |

## 架构

~~~text
                    shared/contracts + shared/content
                         /                     \
                        /                       \
Windows main.py -> presentation -> application -> domain
       \                  ^             ^             ^
        \                 |             |             |
         +---- infrastructure  implements ports -----+

Android app (composition root) -> presentation -> application -> domain
             \                         ^             ^             ^
              +------ infrastructure --+-------------+
~~~

这是洋葱架构：依赖只能由外向内。`domain` 不依赖 UI、文件系统、Android SDK 或 Tkinter；`application` 只编排用例和端口；`infrastructure` 负责 JSON/SharedPreferences、词库、CSV 与系统文件选择器；`presentation` 负责交互和展示；`windows/main.py` 与 Android `AppContainer` 是组合根。

## 关键入口点

- **Windows 组合根**：`windows/main.py`；创建词库加载器、仓储、CSV 适配器和 `LearningService`。
- **Windows 领域**：`windows/domain/models.py`、`windows/domain/scheduler.py`、`windows/domain/ports.py`。
- **Windows 用例**：`windows/application/services.py`。
- **Windows UI**：`windows/presentation/app.py`、`windows/presentation/widgets.py`。
- **Android 组合根**：`android/app/src/main/kotlin/com/lexitrack/learning/AppContainer.kt`；Activity 只处理生命周期和 SAF 文件选择。
- **Android 领域/用例**：`android/domain/`、`android/application/`。
- **Android 适配器**：`android/infrastructure/`；Compose UI 和 ViewModel 位于 `android/presentation/`。
- **共享单一事实来源**：`shared/contracts/parity.json`、调度/复习/CSV 契约及 `shared/content/catalog.json`。

## 目录结构

~~~text
shared/contracts/       双端数据、算法、CSV 与能力契约及 golden vectors
shared/content/         版本化 CET-4/CET-6 词库与许可声明
shared/assets/branding/ 双端共用的品牌源资产
tools/                  词库生成和双端同步校验
windows/domain/         领域模型、调度器和端口
windows/application/    用例服务
windows/infrastructure/ JSON、词库和 CSV 适配器
windows/presentation/   Tkinter 页面与弹窗
android/domain/         无 Android 依赖的领域模块
android/application/    无 Android 依赖的用例模块
android/infrastructure/ 平台持久化、assets、CSV
android/presentation/   Compose 页面与 ViewModel
android/app/            Activity、SAF 与唯一 Android 组合根
~~~

## 典型数据流

学习卡请求从 UI/ViewModel 进入应用用例，应用层通过仓储端口取得词条和学习状态，领域层验证/调度后由基础设施保存；UI 只接收结果。CSV 导入则由平台文件选择器取得字节/路径，经基础设施解析和逐行校验，应用层写入词库仓储，再由 UI 展示统一的成功、跳过、失败报告。

## 约定

- Python 文件使用 snake_case，Kotlin 类型使用 PascalCase，测试按被测模块组织。
- 领域时间使用 UTC epoch seconds；系统时钟通过端口注入。
- 输入错误返回稳定错误码或用户可见错误消息，不静默覆盖已有词条和学习进度。
- VocabularyEntry 的稳定 ID、membership、标签、例句最低要求必须与共享契约一致。
- Windows、Android 和共享契约必须在同一功能提交中同步；能力只有双端测试通过后才能标记 ready。
- 提交信息沿用短前缀风格，例如 feat、fix、test、build。

## 常用命令

~~~powershell
python tools/verify_sync.py
python -m unittest discover -s .\\windows\\tests -v
python .\\windows\\main.py --smoke-test --data-dir .\\windows\\.smoke-data
.\\android\\gradlew.bat test lintDebug assembleDebug
~~~

Android 构建需要 JDK 17、Android SDK 35；Windows 打包还需要 windows/requirements-build.txt 中的 PyInstaller。CI 配置在 .github/workflows/ci.yml。

## 查找位置

| 我想…… | 查看…… |
|---|---|
| 添加跨端规则 | shared/contracts/ 和 parity.json |
| 改学习/复习业务 | 两端 application 与 domain，再补两端测试 |
| 改本地存储 | 各端 infrastructure，保持端口不变 |
| 改页面交互 | 对应 presentation；Android 文件选择仍留在 app |
| 添加回归测试 | windows/tests/ 或 Android 各模块 src/test |
| 发布前检查 | tools/verify_sync.py、CI 和双端构建 |

## 当前架构审查提示

共享 JSON 和 Android 使用可多选的 memberships 集合；Windows 为兼容旧状态仍持久化 `level` 字符串，但领域模型通过 `VocabularyEntry.levels` 暴露集合语义。筛选和新增功能必须使用集合接口，不得直接按单个字符串比较。
