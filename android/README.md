# 词程 LexiTrack Android

Android 8.0 及以上的本地英语学习应用。内置四六级词库，提供学习卡、四档复习评分、词库搜索、CSV 导入、记忆保持率与未来七天复习负载。学习卡将“查看答案”和四档评分固定在单词下方，三组双语例句位于其下，页面不响应纵向滚动。学习进度、导入词条和字号偏好保存在设备本地。

## 安装预发布版

在 GitHub [Releases](https://github.com/icecube553511/Language-Learning-Helper/releases) 下载 `app-debug.apk` 与同包的 `SHA256SUMS.txt`。当前 `v0.1.0` 是面向 Android 8.0+ 的开发预览包，使用 Android Debug 证书签名且包含可调试标记，不是应用商店正式包。设备需允许浏览器或文件管理器“安装未知应用”；也可使用下方 ADB 命令安装。

后续 CI 生成的 debug 包可能使用不同证书，若覆盖安装提示签名不一致，需要先卸载旧版。卸载会删除应用本地学习记录；本版本没有跨设备云同步或应用内备份功能。

## 工程结构

工程采用洋葱架构，依赖只从外层指向内层：

```text
app              Activity、SAF 文件选择与依赖装配
presentation     Compose 页面、主题、ViewModel
infrastructure   catalog assets、CSV、SharedPreferences 适配器
application      用例与仓储端口
domain           词条约束、lexi-sm2-v1 调度器
```

`domain` 和 `application` 不依赖 Android。`presentation` 不访问持久化实现，`app` 是唯一组合入口。内置词库从仓库根目录的 `shared/content/catalog.json` 合并进 APK；该文件不存在时应用显示空词库，并仍允许 CSV 导入。

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35。工程包含 Gradle Wrapper，并校验 Gradle 8.10.2 分发包的 SHA-256：

```powershell
$env:JAVA_HOME='C:\path\to\jdk-17'
$env:ANDROID_SDK_ROOT='C:\path\to\Android\Sdk'
./gradlew.bat test lintDebug assembleDebug
```

调试 APK 位于：

```text
app/build/outputs/apk/debug/app-debug.apk
```

安装到已连接设备：

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n com.lexitrack.learning/.MainActivity
```

## CSV 导入格式

文件必须使用 UTF-8 或 UTF-8 BOM，并遵循 RFC 4180。含逗号、双引号或换行的字段必须按 CSV 规则使用双引号包围，字段内双引号写成两个连续双引号。

必填列：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

选填列：`phonetic,level,tags,mnemonic`。`level` 只能是 `CET4`、`CET6` 或 `custom`，默认 `custom`；多个标签使用 `|` 分隔。

```csv
word,meaning,phonetic,level,tags,mnemonic,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
negotiate,"v. 谈判,协商",/nɪˈɡəʊʃieɪt/,CET6,business|meeting,go + tiate,"They negotiated a better contract.","他们谈成了一份更好的合同。","We need to negotiate with the supplier.","我们需要与供应商协商。","Negotiate clearly before signing.","签署前要清楚地协商。"
```

每行的单词、释义和三组双语例句都必须非空，三条英文例句必须互不相同。单词最多 100 个字符，其他单字段最多 2000 个字符。重复词条会跳过，不覆盖已有内容和学习进度；其他无效行不会进入学习队列，导入完成后会按行显示成功、跳过和错误原因。

## 记忆调度

Android 端实现根目录 `shared/contracts/scheduler-v1.md` 定义的 `lexi-sm2-v1`，所有调度时间以 UTC epoch seconds 保存。领域测试直接回放 `shared/contracts/scheduler-golden-v1.json`，确保与 Windows 端保持一致。
