# LexiTrack 词程

LexiTrack 是一个离线优先的 CET-4/CET-6 英语学习软件 monorepo，同时交付 Windows 与 Android 客户端。两个客户端使用相同的词库版本、CSV 契约、记忆曲线版本和功能清单，并在同一提交中推进。

## 目录

```text
windows/                 Windows 桌面客户端（Python + Tkinter）
android/                 Android 客户端（Kotlin + Jetpack Compose）
shared/contracts/        双端共享的数据、算法和功能契约
shared/content/          经过质量门禁的 CET-4/CET-6 内容
tools/                   数据生成、质量检查和双端同步检查
```

两个客户端均采用洋葱架构。领域层不依赖 UI、文件系统或平台 SDK；应用层编排用例；基础设施层实现持久化和 CSV 导入；表现层只处理交互与展示。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 本地运行

Windows 需要 Python 3.10+：

```powershell
python .\windows\main.py
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

以下列为选填：

```text
phonetic,level,tags,mnemonic
```

完整字段约束、带逗号和引号的示例、重复规则及错误报告格式见 [shared/contracts/csv-import-v1.md](shared/contracts/csv-import-v1.md)。不满足三组双语例句要求的行不会进入学习队列。

## 双端同步纪律

- `shared/contracts/parity.json` 是功能、schema、算法和内容版本的唯一清单。
- 一项功能只有在两个客户端实现并通过对应测试后，才能标记为 `ready`。
- 每个功能切片在同一个 Git commit 中更新 Windows、Android 与共享契约，并立即推送 GitHub。
- 学习记录默认保存在各自设备本地；“双端同步”指功能与契约同步，不代表未经配置的跨设备云同步。

## 数据来源

释义与四六级标签来自 MIT 许可的 ECDICT。参考项目“单词记忆1”的 Tatoeba、WordNet、Brown Corpus 与 Project Gutenberg 例句会在满足许可和质量门禁时复用。具体署名随内容清单与 `THIRD_PARTY_NOTICES.md` 一同发布。

