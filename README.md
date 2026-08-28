# LexiTrack 词程

LexiTrack 是一个离线优先的 CET-4/CET-6 英语学习软件 monorepo，同时交付 Windows 与 Android 客户端。两个客户端使用相同的词库版本、CSV 契约、记忆曲线版本和功能清单，并在同一提交中推进。

学习评分过的词会写入本地 `Words_Learnt`，主动复习按掌握权重无放回抽取。双端默认随机学习，也可按字母排序；学习、复习与弹窗提醒可分别多选四级、六级和自定义词汇组。Android 在后台通过系统高优先级通知展示学习卡，Windows 在应用运行期间显示置顶卡片。两端都支持按词库生成 A4 默写 worksheet，预览后可分别导出 Word/PDF，并按偏好给词条添加本地 `evaluated` 标签。

## 目录

```text
windows/                 Windows 桌面客户端（Python + Tkinter）
android/                 Android 客户端（Kotlin + Jetpack Compose）
shared/contracts/        双端共享的数据、算法和功能契约
shared/content/          经过质量门禁的 CET-4/CET-6 内容
shared/assets/branding/  Windows 与 Android 共用的品牌源资产
tools/                   数据生成、质量检查和双端同步检查
```

两个客户端均采用洋葱架构。领域层不依赖 UI、文件系统或平台 SDK；应用层编排用例；基础设施层实现持久化和 CSV 导入；表现层只处理交互与展示。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 下载预发布版

GitHub [Releases](https://github.com/icecube553511/Language-Learning-Helper/releases) 同时提供 Windows x64 便携 EXE 和 Android 8.0+ APK。`v0.2.0` 是开发预览版：Windows EXE 尚未进行 Authenticode 签名，Android APK 使用 Android Debug 证书签名，不用于 Microsoft Store 或应用商店分发。每个下载包都附带由同一 GitHub Actions run 生成的 `SHA256SUMS.txt`。

两端学习进度均只保存在本机，升级或卸载前请阅读各客户端 README 的数据说明。

## 本地运行

Windows 需要 Python 3.10+：

```powershell
python .\windows\main.py
```

从源码生成 EXE 前安装已锁定的构建依赖：

```powershell
python -m pip install -r .\windows\requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

Android 需要 JDK 17 与 Android SDK 35：

```powershell
$env:JAVA_HOME = '<JDK 17 path>'
$env:ANDROID_SDK_ROOT = "$env:LOCALAPPDATA\Android\Sdk"
.\android\gradlew.bat -p .\android test assembleDebug
```

## CSV 导入格式

CSV 必须使用 UTF-8 或 UTF-8 BOM，遵循 RFC 4180。以下列为必填：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

以下列为选填；`level` 可用 `|` 分隔多个词汇组，`tags` 可用 `|` 分隔多个标签：

```text
phonetic,level,tags,mnemonic
```

完整字段约束、带逗号和引号的示例、重复规则及错误报告格式见 [shared/contracts/csv-import-v1.md](shared/contracts/csv-import-v1.md)。不满足三组双语例句要求的行不会进入学习队列。

## 默写 worksheet

在“默写”页面选择词库、数量、随机或手选模式、Word/PDF（可多选）、字号和要挖空的单词/词性/中文字段。默认字号为 12 pt（小四），页面固定 A4 portrait；例句可以从词库提取或用本次自填内容覆盖，目标单词按共享契约挖空。预览确认后，Windows 使用保存对话框，Android 使用系统文件选择器分别保存选中的格式。导出成功后可选择是否将本次词条标记为 `evaluated`，偏好可在设置中切换为默认标记、默认不标记或每次询问。

词库标签编辑只提供程序已有的 `cet4`、`cet6`、`gk`、`zk`、`evaluated`，添加/删除均保存为本地覆盖，不会改写共享内置词库。

## 双端同步纪律

- `shared/contracts/parity.json` 是功能、schema、算法和内容版本的唯一清单。
- 一项功能只有在两个客户端实现并通过对应测试后，才能标记为 `ready`。
- 每个功能切片在同一个 Git commit 中更新 Windows、Android 与共享契约，并立即推送 GitHub。
- 学习记录默认保存在各自设备本地；“双端同步”指功能与契约同步，不代表未经配置的跨设备云同步。

## 数据来源

释义与四六级标签来自 MIT 许可的 ECDICT。参考项目“单词记忆1”的 Tatoeba、WordNet、Brown Corpus 与 Project Gutenberg 例句会在满足许可和质量门禁时复用。具体署名随内容清单与 `THIRD_PARTY_NOTICES.md` 一同发布。

内置例句的中文翻译统一为简体中文。重新生成词库前需安装 `tools/requirements-content.txt`，生成器和双端同步校验会使用同一套 `t2s` 规则阻止繁体译文回流。
