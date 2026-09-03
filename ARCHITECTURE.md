# LexiTrack 架构设计（Agent 必读）

> 本文件是仓库的权威架构说明。任何 agent 在检查、修改、生成、测试或提交
> 仓库内容之前，都必须完整阅读本文件；随后再阅读任务涉及的
> `shared/contracts/` 契约与存在的 golden vectors。`CODEBASE_ONBOARDING.md` 只
> 负责导航，不能替代本文件。

## 1. 系统边界

LexiTrack 是一个离线优先的 monorepo，同时交付 Windows 桌面端与 Android
客户端。两个客户端不共享运行时代码，而是分别实现同一组版本化行为。仓库中的
`shared/` 提供契约、测试向量、只读内容与源资产，不是第三个平台实现。

```text
shared/{contracts, content, assets}
                 |
                 +--------------------> Windows
                 |
                 +--------------------> Android
```

其中 contracts 提供行为/wire format/测试向量，content 提供生成的只读 catalog，
assets 提供 canonical 源资产与生成的运行资源；两端都会消费这三类输入。

核心学习默认完全离线。唯一可选的网络边界是默写草稿同步；只有组合入口收到完整
HTTPS endpoint、账号标识与 bearer token 时才启用，否则必须装配 no-network
adapter。词库、学习进度和导出文件不得进入该同步端口。

## 2. 事实来源

发生冲突时，按以下顺序修正外层工件，而不是让两端各自定义行为：

1. `shared/contracts/*-v1.md` 定义详细语义；存在配套 `*-golden-v1.json` 时，它提供
   可执行测试向量。CSV 目前只有 fixtures，learning reminder 与 dictation draft
   没有独立 golden 文件。
2. `shared/contracts/parity.json` 汇总发布、schema、算法、内容版本、共享参数和
   capability 状态。它不是所有行为细节的替代品。
3. `windows/platform-contract.json` 与 `android/platform-contract.json` 镜像共享
   parity 清单。
4. 两端实现、平台测试和 `tools/verify_sync.py` 共同提供其覆盖范围内的实现证据。

`schemaVersion` 当前只是三份聚合清单中的同步字段，尚未自动绑定每个 Windows
存储常量或 Android wire schema；变更存储格式时仍需逐个检查迁移与兼容测试。

新增或修改跨端行为时，先改契约，再改三份清单、双端实现和双端测试。只有两端
完成且门禁通过后，capability 才能标记为 `ready`。

## 3. 分层与依赖方向

每个平台都使用向内依赖的分层结构。Presentation 与 Infrastructure 是并列外层；
Infrastructure 实现内层声明的端口，组合入口负责选择具体适配器。

```text
                         +-------------------+
                         | Composition roots |
                         +---------+---------+
                                   |
                    +--------------+--------------+
                    v                             v
             Presentation                 Infrastructure
                    |                        |          |
                    +----------+-------------+          |
                               v                        |
                         Application <------------------+
                               |
                               v
                            Domain
```

允许外层直接消费更内层的不可变值类型，但禁止任何向外反向依赖。

| 层 | 负责 | 禁止 |
|---|---|---|
| Domain | 词条与复习模型、规范化、调度、默写文档、气泡栈、分组、宠物运动/成长/形象纯规则 | UI toolkit、Android SDK、文件系统、具体仓储、平台资源句柄 |
| Application | 用例编排、端口、查询结果、跨仓储补偿、导入/导出/同步流程 | Tkinter、Android SDK、具体 JSON/SharedPreferences 类 |
| Infrastructure | catalog/CSV adapter、本地存储、加密、DOCX/PDF writer、可选 HTTPS transport、Android 通知适配器 | 页面状态和交互规则 |
| Presentation | Tkinter/Compose 页面、ViewModel/UI state、预览渲染、动画、手势、无障碍语义 | 直接读取 catalog/持久化文件、创建具体仓储、复制领域规则 |
| Composition root | 进程入口、平台生命周期、权限/文件选择、具体依赖装配 | 业务规则 |

### Windows

```text
windows/main.py
  -> CatalogLoader + JSON repositories + CSV/export/sync adapters
  -> LearningService
  -> LexiTrackApp
```

- `windows/main.py` 是 GUI/CLI 入口、主要组合根和 DPI 平台边界。
- `windows/application/services.py` 中的 `LearningService` 是主要用例门面。
- `windows/domain/ports.py` 与 `windows/application/ports.py` 声明内层端口。
- `windows/infrastructure/` 实现 catalog、CSV、JSON 存储、DPAPI 加密、导出和
  可选 HTTPS 草稿同步。
- `windows/presentation/` 实现 Tkinter 页面、词语气泡、冰子窗口协调和评分特效。

### Android

```text
:app (MainActivity + AppContainer)
  +-> :presentation -> :application -> :domain
  +-> :infrastructure -> :application -> :domain

ReminderReceiver (headless platform entry)
  -> repositories + GetReminderCardUseCase + notification adapter
```

- `:domain` 与 `:application` 是纯 JVM 模块；不得引用 Android SDK。
- `:presentation` 与 `:infrastructure` 是 Android library；`:app` 是前台组合模块。
- `MainActivity` 处理生命周期、通知权限、SAF 输入/输出、提醒调度和 deep link；
  `AppContainer` 装配前台用例。
- `ReminderReceiver` 是后台通知的第二个、无界面的平台入口，不是页面层。

## 4. 状态所有权

| 状态 | Windows | Android | 规则 |
|---|---|---|---|
| 内置 catalog | 打包的 `shared/content/catalog.json` | 构建期并入 assets | 只读，只能由生成器更新 |
| 用户词条、排期、活动、设置、tag override | `learning-state.json` | 多组私有 SharedPreferences | 只经 repository 端口访问 |
| 已学词权重、恢复标记、宠物成长 | `Words_Learnt.json` | `Words_Learnt` SharedPreferences | 与排期存储保持物理隔离 |
| 默写草稿、同步元数据、最后同步 envelope、冲突备份 | DPAPI 加密后写入本地状态 | Android Keystore AES-GCM 后写入专用 preferences | 禁止明文降级；最多三份冲突备份 |
| 导航/搜索、未保存的页面选择、气泡栈、宠物位置/速度/目标、翻页帧、光球/拖尾/爆点 | Presentation 内存 | Presentation 内存 | 瞬态，不得持久化；可恢复的默写选择只能进入上方版本化草稿 |

一次评分会同时更新复习排期和已学词/成长状态。Application 在第二次写入失败时
使用 review savepoint 补偿第一次写入；这只是进程内补偿，不是跨文件、跨
SharedPreferences 或跨崩溃的原子事务。

## 5. 关键数据流

### 学习与评分

```text
UI -> Service/UseCase -> repository ports -> domain scheduler/reward reducer
   -> review store -> learnt-word/vitals store -> refreshed UI state
```

时间统一使用 UTC epoch seconds。调度计算必须接收显式时间；新增领域规则不得直接
读取系统时钟。

### CSV 导入

```text
platform picker -> bytes/path -> UI boundary -> application import use case
  -> CSV/repository ports -> infrastructure parser/storage -> import report -> UI
```

UTF-8、RFC 4180、字段长度、membership、三组双语例句、重复与错误码由
`csv-import-v1.md` 定义。导入不得覆盖已有词条或学习进度。

### 默写预览与导出

```text
UI selection -> application -> domain DictationDocument
  +-> presentation preview
  +-> infrastructure DOCX/PDF bytes -> platform save picker -> user file
```

Preview 与 writer 消费同一个平台无关 `Document`；preview 属于 Presentation，
DOCX/PDF 编码属于 Infrastructure，文件选择和最终写出应属于平台边界。Windows
当前仍在 presentation 完成 picker/最终写出，属于第 8 节记录的历史例外。至少一个
格式成功写出后，才能按设置写入本地 `evaluated` tag override。

## 6. 契约索引

| 领域 | 必读契约 | 自动化载体 |
|---|---|---|
| 调度与复习 | `scheduler-v1.md`、`weighted-review-v1.md` | 两份同名 golden JSON |
| 导入、词书与提醒 | `csv-import-v1.md`、`vocabulary-groups-v1.md`、`learning-reminder-v1.md` | CSV fixtures；groups golden；reminder 无独立 golden |
| 默写 | `dictation-export-v1.md`、`dictation-draft-v1.md` | export golden；draft 无独立 golden |
| 递归词语气泡 | `word-bubble-v1.md` | 同名 golden JSON |
| 冰子 | `pet-companion-v1.md`、`pet-vitals-v1.md`、`pet-appearance-v1.md` | 三份同名 golden JSON |

契约中已有的阈值、排序、文案和交互语义不要复制到本文件；修改时直接更新契约和
golden vectors，避免架构文档随功能细节漂移。

## 7. 生成物边界

以下文件不得手工编辑：

- `shared/content/catalog.json` 与 `catalog-manifest.json`：由
  `python tools/build_catalog.py` 生成。默认输入是 `.cache/ecdict.csv` 和仓库同级
  `../单词记忆1/data/cet4_words.json`，因此默认生成流程不是完全自包含的。
- `shared/assets/pets/bingzi.png` 与 `bingzi-left.png`：由
  `python tools/prepare_pet_asset.py` 从 canonical `pet_image.png` 生成。
- `shared/assets/pets/states/` 中的状态 PNG 与 `manifest.json`：由
  `python tools/prepare_pet_appearance_assets.py` 从
  `shared/assets/branding/pet_states/` 生成。目录中的 `README.md` 仍由人工维护。

`shared/assets/branding/app_image.png` 是 canonical 应用图源。目前仓库尚无统一的
平台图标生成工具；新增平台图标流水线时应补可重现性校验。

## 8. 已知架构债务

这些是现状说明，不是可复制的先例：

- Windows `presentation/app.py` 仍直接打开导入/保存对话框、写导出文件，并有两处
  通过 `LearningService.repository` 查询状态。新代码应补 application query/use
  case，不得增加 presentation 到存储的直连。
- Android 默写草稿同步仍有部分编排位于 `MainViewModel`。新流程应下沉到
  application use case。
- Windows `domain/dictation_sync.py` 的兼容 helper 在未传时间时会读取系统时钟。
  新领域 API 必须显式注入时间。
- `windows/presentation/app.py` 和 `windows/application/services.py` 是大型热点文件；
  修改应局部、配套测试，避免继续扩大跨层职责。
- `tools/verify_sync.py` 是契约/内容/资产/parity 门禁，不是完整架构 linter；脚本
  通过不代表分层必然合规。
- Android 当前没有 Activity、Receiver、真实 Compose 交互或设备级 SAF 自动化
  测试；相关改动需要额外人工/设备验证。

## 9. 交付门禁

从仓库根目录执行：

```powershell
python -m pip install -r .\tools\requirements-content.txt
python .\tools\verify_sync.py
python -m pip install -r .\windows\requirements-build.txt
python -m unittest discover -s .\windows\tests -v
python .\windows\main.py --smoke-test --data-dir .\windows\.smoke-data
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

Android 必须使用 JDK 17 与 SDK 35。CI 还会打包并 smoke-test Windows EXE、构建
debug APK、生成 SHA-256 并上传 Actions artifacts。`verify_sync.py` 不能替代双端
测试、lint、build 或 smoke test。

每项行为变更都必须在同一 branch/PR 中包含 Windows、Android、共享契约、三份
清单和风险相称的双端测试，除非请求明确声明单平台例外。交付前保留无关工作区
修改，提交并推送分支，创建 GitHub pull request，并记录实际执行的验证命令。
