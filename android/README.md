# 词程 LexiTrack Android

Android 8.0 及以上的本地英语学习应用。内置四六级词库，提供学习卡、独立加权复习、四档评分、词库搜索、CSV 导入、记忆保持率与未来七天复习负载。学习卡与复习卡将单词、音标、释义和三组双语例句逐组居中排列，四档大按钮固定在卡片底部，页面不响应纵向滚动。学习进度、`Words_Learnt`、导入词条和偏好都保存在设备本地。

设置页可开启单词提醒，间隔以分钟为单位并支持 `0.5` 到 `120` 的浮点数。前台显示完整卡片；后台由 `AlarmManager` 触发高优先级系统通知，点击通知打开对应完整卡片。Android 13+ 需要用户授予通知权限，实际显示时刻和横幅样式受 Doze、厂商省电策略及通知频道设置影响。提醒不提供延后选项。

学习默认随机抽取，也可在设置中切换为字母顺序。学习、复习和单词提醒分别多选四级、六级和自定义词汇组，三个筛选互不影响。导入时可批量填写 `level`/`tags`，词库中可对内置或导入词条勾选并添加/删除程序已有标签，修改保存为本地覆盖。

默写页面以翻书动画进入，可按词库随机或手选词条；随机模式可打开所选词书检查候选词，并从当前词书直接切换手选。页面支持 Word/PDF 多选、A4 页面、8 到 24 pt 字号、缺失字段、首字母和例句，先生成共享 `DictationDocument` 并预览，再通过 Android 系统文件选择器分别保存 Word/PDF；导出成功后按设置询问是否添加 `evaluated` 标签。

## 安装预发布版

在 GitHub [Releases](https://github.com/icecube553511/Language-Learning-Helper/releases) 下载已发布版本的 `app-debug.apk` 与同包的 `SHA256SUMS.txt`。仓库源码中的 `versionName` 是当前开发目标，不保证已有同名 Release。预览 APK 使用 Android Debug 证书签名且包含可调试标记，不是应用商店正式包。设备需允许浏览器或文件管理器“安装未知应用”；也可使用下方 ADB 命令安装。

后续 CI 生成的 debug 包可能使用不同证书，若覆盖安装提示签名不一致，需要先卸载旧版。卸载会删除应用本地学习记录。默认构建不配置跨设备服务，所有学习数据和默写草稿仅保存在本机；组合根可选择注入 HTTPS 默写草稿同步适配器，该适配器不上传词库、学习进度或导出文件。

## 工程结构

工程采用洋葱架构，依赖只从外层指向内层：

```text
app              Activity、SAF 文件选择与依赖装配
presentation     Compose 页面、主题、ViewModel
infrastructure   catalog/CSV、SharedPreferences、Keystore、导出、提醒与同步适配器
application      用例与仓储端口
domain           词条约束、lexi-sm2-v1 调度器
```

`domain` 和 `application` 不依赖 Android。`presentation` 不访问持久化实现；`app` 是前台组合模块，后台通知则由 infrastructure 中的 `ReminderReceiver` 作为无界面平台入口装配所需用例。内置词库从仓库根目录的 `shared/content/catalog.json` 合并进 APK；该文件不存在时应用显示空词库，并仍允许 CSV 导入。

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35。工程包含 Gradle Wrapper，并校验 Gradle 8.10.2 分发包的 SHA-256。从仓库根目录运行：

```powershell
$env:JAVA_HOME='C:\path\to\jdk-17'
$env:ANDROID_SDK_ROOT='C:\path\to\Android\Sdk'
.\android\gradlew.bat -p .\android test lintDebug assembleDebug
```

调试 APK 位于：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

安装到已连接设备：

```powershell
adb install -r .\android\app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n com.lexitrack.learning/.MainActivity
```

## CSV 导入格式

文件必须使用 UTF-8 或 UTF-8 BOM，并遵循 RFC 4180。含逗号、双引号或换行的字段必须按 CSV 规则使用双引号包围，字段内双引号写成两个连续双引号。

必填列：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

选填列：`phonetic,level,tags,mnemonic`。`level` 只能包含 `CET4`、`CET6` 或 `custom`，默认 `custom`；多个词汇组和多个标签均使用 `|` 分隔。

```csv
word,meaning,phonetic,level,tags,mnemonic,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
negotiate,"v. 谈判,协商",/nɪˈɡəʊʃieɪt/,CET6,business|meeting,go + tiate,"They negotiated a better contract.","他们谈成了一份更好的合同。","We need to negotiate with the supplier.","我们需要与供应商协商。","Negotiate clearly before signing.","签署前要清楚地协商。"
```

每行的单词、释义和三组双语例句都必须非空，三条英文例句必须互不相同。单词最多 100 个字符，其他单字段最多 2000 个字符。重复词条会跳过，不覆盖已有内容和学习进度；其他无效行不会进入学习队列，导入完成后会按行显示成功、跳过和错误原因。

## 记忆调度

Android 端实现根目录 `shared/contracts/scheduler-v1.md` 定义的 `lexi-sm2-v1`，所有调度时间以 UTC epoch seconds 保存。领域测试直接回放 `shared/contracts/scheduler-golden-v1.json`，确保与 Windows 端保持一致。

学习页只展示未学习词，首次评分会把词条写入应用私有的 `Words_Learnt` SharedPreferences store。复习页按共享 `weighted-review-v1` 契约进行加权无放回抽样；“忘记/模糊”保持原权重，“认识/很熟”分别调整为 `20%/5%`。应用运行期间每分钟检查到期排期并显示复习提醒。
