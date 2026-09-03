<p align="center">
  <img src="shared/assets/branding/app_image.png" width="180" alt="LexiTrack 词程应用图标">
</p>

<h1 align="center">LexiTrack 词程</h1>

<p align="center">离线优先、Windows 与 Android 同步演进的英语学习工具</p>

<p align="center">
  <a href="https://github.com/icecube553511/Language-Learning-Helper/actions/workflows/ci.yml"><img src="https://github.com/icecube553511/Language-Learning-Helper/actions/workflows/ci.yml/badge.svg" alt="dual-platform-ci"></a>
  <a href="https://github.com/icecube553511/Language-Learning-Helper/releases">Releases</a>
</p>

LexiTrack 面向 CET-4/CET-6 及自定义词库学习，同时交付 Python/Tkinter Windows
客户端和 Kotlin/Compose Android 客户端。两端分别实现相同的词库、CSV、记忆
调度、默写和陪伴宠物语义，并用版本化契约与 golden tests 保持一致。

核心学习不依赖账号或云服务。学习进度、设置、导入词条和本地标签都留在设备上；
可选的默写草稿同步只有在显式配置安全端点与凭据后才会启用。

## 功能概览

- 学习卡与四档评分复习，使用 `lexi-sm2-v1` 排期。
- 按掌握权重无放回抽取复习词，学习/复习/提醒范围彼此独立。
- CET-4、CET-6、中考、高考与自定义词书分组浏览、搜索和本地标签覆盖。
- UTF-8 / RFC 4180 CSV 导入，逐行返回成功、跳过与稳定错误码。
- A4 默写 worksheet 预览，支持 DOCX/PDF、多字段挖空、随机或手选词条。
- 英文例句中的递归词语气泡，展示中文释义和至少三组双语例句。
- 冰子桌面/页面陪伴、拖放物理、成长状态与评分奖励效果。
- Windows 运行时置顶学习提醒；Android 前台卡片与后台高优先级通知。

## 下载与版本

正式提供给用户的构建只以 GitHub [Releases](https://github.com/icecube553511/Language-Learning-Helper/releases)
页面为准。仓库清单中的 `releaseVersion` / 应用 `versionName` 是当前源码目标，
不代表同名 Release 已经发布。

GitHub Actions 会为每个 PR 与 `main` push 的成功 workflow run 生成短期 Windows
EXE 和 Android debug APK artifact；它们用于验证，不等同于 Release。当前
Windows 构建未做 Authenticode 签名，Android 预览构建使用 debug 证书。升级、
卸载和本地数据位置分别见
[Windows 说明](windows/README.md) 与 [Android 说明](android/README.md)。

## 架构

`shared/` 不包含跨端运行时代码。它保存详细行为契约、golden vectors、生成词库和
canonical 资产；Windows 与 Android 各自实现这些规则。

```text
                    shared/contracts + golden vectors
                              |
             +----------------+----------------+
             v                                 v
       Windows client                    Android client

       Composition roots / platform entry points
                         |
            +------------+------------+
            v                         v
       Presentation              Infrastructure
            |                         |
            +----------> Application <+
                              |
                              v
                            Domain
```

依赖只向内。Domain 不依赖 UI、文件系统或平台 SDK；Application 编排用例与端口；
Infrastructure 实现存储、CSV、导出、加密和平台 adapters；Presentation 负责
交互、UI state 与渲染，持久化变更必须经 application 端口；composition roots
装配具体实现。Windows 现有文件 IO/直接 repository 查询例外列在架构债务中，
不得作为新代码先例。

完整设计、状态归属、数据流与已知架构债务见
[ARCHITECTURE.md](ARCHITECTURE.md)。

### Agent 与贡献者入口

任何 agent 在检查、修改、生成、测试或提交仓库内容前，必须先完整阅读
[AGENTS.md](AGENTS.md) 和 [ARCHITECTURE.md](ARCHITECTURE.md)，再阅读任务涉及的
共享契约。快速代码导航见 [CODEBASE_ONBOARDING.md](CODEBASE_ONBOARDING.md)，
执行摘要见 [CLAUDE.md](CLAUDE.md)。

## 仓库结构

```text
windows/                 Python + Tkinter Windows 客户端
android/                 Kotlin + Compose Android 多模块工程
shared/contracts/        行为规范、golden vectors、parity manifest
shared/content/          生成的只读词库与许可证
shared/assets/           canonical 品牌源资产与生成的运行资源
tools/                   内容/资源生成器和双端同步门禁
docs/                    专题决策与协作文档
.github/workflows/       双端 CI
```

## 本地运行

### Windows

需要 Python 3.10+。从仓库根目录执行：

```powershell
python -m pip install -r .\windows\requirements-export.txt
python .\windows\main.py
```

需要指定隔离数据目录时：

```powershell
python .\windows\main.py --data-dir D:\LexiTrackData
```

打包便携 EXE：

```powershell
python -m pip install -r .\windows\requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

### Android

需要 JDK 17、Android SDK Platform 35 与 Build Tools 35。从仓库根目录执行：

```powershell
$env:JAVA_HOME = '<JDK 17 path>'
$env:ANDROID_SDK_ROOT = "$env:LOCALAPPDATA\Android\Sdk"
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

APK 输出到 `android/app/build/outputs/apk/debug/app-debug.apk`。

## 完整验证

文档改动至少运行同步门禁；行为改动在交付前必须执行以下完整矩阵：

```powershell
python -m pip install -r .\tools\requirements-content.txt
python .\tools\verify_sync.py
python -m pip install -r .\windows\requirements-build.txt
python -m unittest discover -s .\windows\tests -v
python .\windows\main.py --smoke-test --data-dir .\windows\.smoke-data
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

CI 还会构建并 smoke-test 打包后的 Windows EXE、生成 debug APK、计算 SHA-256，
并上传 30 天 artifact。`verify_sync.py` 校验契约、内容、资产和三份 manifest；它
不能替代平台测试、lint、build 或 smoke test。

## CSV 导入

CSV 使用 UTF-8 或 UTF-8 BOM 并遵循 RFC 4180。必填列：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

选填列为 `phonetic,level,tags,mnemonic`。`level` 和 `tags` 可用 `|` 分隔多个值；
三条英文例句必须不同，且每条都有简体中文翻译。重复或无效词条不会覆盖已有内容
和学习进度。完整字段、边界和错误码见
[csv-import-v1.md](shared/contracts/csv-import-v1.md)。

## 数据与隐私

- Windows 默认写入 `%LOCALAPPDATA%\LexiTrack`；核心状态与 `Words_Learnt.json`
  分开保存。
- Android 使用应用私有 SharedPreferences；没有 Room/SQLite 或广泛存储权限。
- 两端默写草稿和同步元数据在本机加密，且加密失败时不回退为明文。
- Android CSV 与导出文件通过 Storage Access Framework 选择。
- 可选草稿同步只传版本化草稿、revision 与删除墓碑，不上传词库、学习进度或
  导出文件。

Windows 可选同步通过 `LEXITRACK_SYNC_ENDPOINT`、
`LEXITRACK_SYNC_ACCOUNT_ID`、`LEXITRACK_SYNC_TOKEN` 注入；配置不完整或 endpoint
不是 HTTPS 时保持本地模式。

## 生成内容与资产

生成文件不能手改：

```powershell
# 安装 catalog 与图片生成工具依赖
python -m pip install -r .\tools\requirements-content.txt

# 生成 shared/content/catalog.json 与 catalog-manifest.json
python .\tools\build_catalog.py

# 从 canonical 源图生成冰子左右运行 sprite
python .\tools\prepare_pet_asset.py

# 校验并生成可选冰子形象状态资源与 manifest
python .\tools\prepare_pet_appearance_assets.py
```

词库生成器默认读取 `.cache/ecdict.csv` 与仓库同级
`..\单词记忆1\data\cet4_words.json`；若环境不同，请显式指定输入：

```powershell
python .\tools\build_catalog.py --ecdict <ecdict.csv> --reference <reference.json>
```

品牌源资产位于 `shared/assets/branding/`，运行资源位于 `shared/assets/pets/`。

## 双端同步纪律

- 详细语义以 `shared/contracts/*-v1.md` 和 golden vectors 为准。
- `shared/contracts/parity.json` 汇总版本、共享参数与 capability；两端
  `platform-contract.json` 必须同步。
- 行为变化先改共享契约，再在同一 branch/PR 实现 Windows、Android 和双端测试；
  单平台例外必须由需求明确授权。
- 提交前运行完整门禁，推送分支并通过 GitHub PR 留下实现与验证记录。

## 数据来源

释义与四六级标签来自 MIT 许可的 ECDICT。参考项目“单词记忆1”中的 Tatoeba、
WordNet、Brown Corpus 与 Project Gutenberg 内容只在满足许可和质量门禁时复用。
完整署名见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与
`shared/content/licenses/`。
