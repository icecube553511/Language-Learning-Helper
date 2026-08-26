# LexiTrack 词程 Windows 客户端

Windows 客户端使用 Python 3.10+ 标准库与 Tkinter，核心学习完全离线。内置词库从仓库根目录的 `shared/content/catalog.json` 加载；文件缺失或损坏时应用会以空库正常启动，用户仍可导入自定义词库。

## 安装预发布版

在 GitHub [Releases](https://github.com/icecube553511/Language-Learning-Helper/releases) 下载 `LexiTrack.exe` 与同包的 `SHA256SUMS.txt`。当前预发布包支持 Windows 10/11 x64，是无需安装的便携 EXE；双击即可运行。该文件尚未进行 Authenticode 签名，Windows 可能显示“未知发布者”或 SmartScreen 提示，请只使用本仓库 Release 中附带校验和的文件。

升级时直接替换 EXE。删除 EXE 即可卸载程序，但不会自动删除 `%LOCALAPPDATA%\LexiTrack` 中的学习记录、`Words_Learnt` 和设置；确认不再需要后可手动删除该目录。

## 运行

在仓库根目录执行：

```powershell
python .\windows\main.py
```

学习记录和设置默认保存在 `%LOCALAPPDATA%\LexiTrack\learning-state.json`，已学词与权重保存在同目录的 `Words_Learnt.json`。测试或便携运行可以指定目录：

```powershell
python .\windows\main.py --data-dir D:\LexiTrackData
```

也可以设置环境变量 `LEXITRACK_DATA_DIR`。

## 功能

- 总览：待复习、未学习、今日完成、可学习词条与 7 天负载。
- 学习卡与复习卡：单词、音标和释义位于顶部中央，忘记、模糊、认识、很熟四档大按钮固定在卡片底部；整页不滚动，学习卡的例句位于固定宽高、不可拉伸的边框视口中，可用鼠标滚轮或右侧滚动条上下查看。
- 复习：侧栏可主动开始一轮复习，按 `100% / 80% / 20% / 5%` 相对权重从已学词中无放回抽取；应用运行期间每分钟检查到期排期并提醒。
- 学习提醒：应用运行期间按设定间隔弹出固定长宽、不可拉伸的置顶单词卡片；仅双语例句区域响应鼠标滚轮并提供纵向滚动条，间隔支持 `0.5` 到 `120` min 的浮点数，可独立多选提醒词汇组并立即预览，不提供延后选项。
- 学习顺序与范围：默认随机，可切换为字母排序；学习、复习和提醒分别多选四级、六级和自定义词汇组。
- 学习与复习卡：三组双语例句按自然高度紧凑排列，例句字号随显示比例同步调整；复习卡保持直接排列。
- 词库：按单词、释义和标签搜索，显示词书与下次复习时间；导入时批量填写标签，也可多选自定义词条批量修改。
- CSV v1：逐行导入并报告成功、跳过、失败和标准错误码。
- 记忆分析：查看未来 7/30 天到期量与平均遗忘曲线。
- 设置：字体可在 90% 至 140% 间调整；每轮复习数量可在 1 到已学词总数之间调整并持久化。

## CSV v1 格式

文件必须为 UTF-8 或 UTF-8 BOM，并遵循 RFC 4180。解析器支持带逗号的字段、双引号字段和双引号转义。

必填列：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

选填列：

```text
phonetic,level,tags,mnemonic
```

`level` 只能包含 `CET4`、`CET6` 或 `custom`，留空时为 `custom`；多个词汇组和多个 `tags` 均使用竖线 `|` 分隔。`word`、`meaning` 和三组英文/中文例句均不得为空，三条英文例句必须不同。`word` 最长 100 字符，其他单字段最长 2000 字符。

```csv
word,meaning,phonetic,level,tags,mnemonic,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
negotiate,"v. 谈判,协商",/nɪˈɡəʊʃieɪt/,CET6,business|meeting,go + tiate,"They negotiated a better contract.","他们谈成了一份更好的合同。","We need to negotiate with the supplier.","我们需要与供应商协商。","""Negotiate clearly,"" the manager said.","经理说：""要清楚地协商。"""
```

同文件重复或与现有词条重复时会跳过，不覆盖原词条或学习进度。完整契约见仓库根目录 `shared/contracts/csv-import-v1.md`。

## 架构

```text
domain/           词条、复习状态、lexi-sm2-v1 与仓储端口
application/      总览、抽卡、评分、搜索、导入与预测用例
infrastructure/   共享目录、JSON 持久化与 CSV 适配器
presentation/     Tkinter 页面、图表、矢量图标与字体系统
main.py           组合根和命令行入口
```

依赖方向为 `presentation -> application -> domain`，基础设施只实现向内层声明的端口。领域调度器不读取系统时钟，所有复习时间由应用层显式传入 UTC epoch seconds。

## 测试与打包

```powershell
python -m pip install -r .\windows\requirements-build.txt
python -m unittest discover -s .\windows\tests -v
python .\windows\main.py --smoke-test --data-dir .\windows\.smoke-data
powershell -ExecutionPolicy Bypass -File .\windows\build.ps1
```

`requirements-build.txt` 固定 CI 使用的 PyInstaller 版本。`build.ps1` 会先运行测试，再生成带 `0.2.0` 版本资源的 `windows/dist/LexiTrack.exe`，并将当前共享词库和许可证一起打包。
