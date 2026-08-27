# Dictation worksheet export v1

本契约定义“默写”可打印 worksheet 的跨端语义。它不是交互答题功能。导出流程必须先生成平台无关的 `Document` 模型，preview、DOCX writer 和 PDF writer 均消费该模型，不得各自重新解释业务规则。

## 输出与版式

- 页面固定为 A4 portrait，宽 `210 mm`、高 `297 mm`，不得输出 landscape。
- DOCX 与 PDF 是可独立多选的输出格式；至少选择一种格式才能导出。
- 预览确认后提供“下载文档”动作；每个选中的格式都必须通过平台文件选择器由用户自选保存路径，不能静默写入固定目录。
- worksheet 正文字号默认 `12 pt`（小四），允许 `8..24 pt`，含边界，持久化为整数 point。标题、页眉和页脚可使用实现定义的字号，但题目字段不得小于所选 worksheet 字号。
- `Document` 至少包含 `pageSize=A4`、`orientation=portrait`、`fontSizePt`、非空 `formats`、有序 `entries`，以及每个 entry 已解析的显示字段。格式 writer 只负责渲染。

## 缺失字段与下划线

可选择的缺失答案字段固定为 `word`、`partOfSpeech`、`meaning`。`missingFields` 必须是这三个值的非空子集，支持多选和全选。未选择的字段显示最终解析值；选择的字段只显示该值对应的下划线。

长度按 Unicode code point 计数，不按 UTF-16 code unit、UTF-8 byte 或 grapheme cluster 计数。计算前只移除字段值首尾的 Unicode whitespace，保留内部字符和空白。下划线为 ASCII `_`：

```text
blankCount(text) = ceil(codePointLength(text) * 1.8)
```

当 `showFirstLetter=true` 且 `word` 在 `missingFields` 中时，只保留 trim 后 `word` 的第一个 Unicode code point，下划线按剩余长度计算：

```text
blankCountAfterFirst(word) = ceil(max(codePointLength(word) - 1, 0) * 1.8)
```

剩余长度大于零时渲染为“第一个 code point + 一个 ASCII space + 下划线串”；单 code point 词只渲染首 code point。`showFirstLetter` 对 `partOfSpeech`、`meaning` 和未缺失的 `word` 无效。

## 词性 extraction 与中文释义

词性 token allowlist 固定为：

```text
n,v,vt,vi,adj,adv,prep,pron,conj,interj,aux,num,art,abbr,a
```

处理算法如下：

1. 在原始 meaning 中从左到右扫描 ASCII token。token 两侧不得是 ASCII 字母或数字；token 后允许有零个或一个紧邻的 `.`，匹配时一并消费该点。
2. 与 allowlist 大小写不敏感比较，以 allowlist 中的小写、无点形式输出；按首次出现顺序去重。
3. `partOfSpeech` 使用 ` / ` 连接提取结果；没有匹配时为空字符串。
4. meaning 删除每次匹配到的 token 及其紧随的单个 `.`，将连续 Unicode whitespace 折叠为一个 ASCII space，再 trim；其他字符、标点和顺序保持不变。

例如 `VT. 放弃, 抛弃 n. 放任 vt. 舍弃` 得到 `partOfSpeech="vt / n"`，清理后的 meaning 为 `放弃, 抛弃 放任 舍弃`。

## 例句

- `includeExample=true` 时，每个词条最多输出一条英文例句，绝不输出三条或多条；renderer 将它输出为单独一行 `e.g. {example}`。`includeExample=false` 时不输出例句。
- 若词条存在 trim 后非空的 `customExample`，优先使用它作为唯一例句，并覆盖 catalog examples；空白 `customExample` 视为不存在。
- 没有有效 `customExample` 时，按 catalog 原顺序扫描双语 examples，仅取第一条英文文本 trim 后非空且包含目标词完整匹配的例句。若没有任何一条包含目标词完整匹配，则回退到 catalog 原顺序中的第一条非空英文例句。若没有非空英文例句，则该词条不输出例句。
- catalog example 是双语结构时仅取英文文本，中文翻译不得进入 worksheet。
- 当 `word` 不在 `missingFields` 中时，英文例句保持原文。`showFirstLetter` 只影响 worksheet 的 `word` 字段，不影响词性、中文、未缺失的 word 或例句。
- 当 `word` 在 `missingFields` 中时，英文例句内所有目标词都必须替换。匹配大小写不敏感，目标词按 literal 匹配；匹配片段前后若存在 ASCII 字母或数字，则不构成完整词边界。
- 例句中的每个匹配始终替换为 `blankCount(word)` 个 ASCII `_`，不显示首字母。
- 替换不得改变未匹配文本、标点、空白或例句顺序。

## 候选池与选择

- 候选词条按 catalog `memberships` 过滤，筛选支持多选。空选择表示全部支持的 memberships；支持值为 `CET4`、`CET6`、`CUSTOM`，比较大小写不敏感。tags 中的 `cet4`/`cet6` 不得替代 memberships。
- `excludeEvaluated=true` 时，排除有效本地 tags 包含 `evaluated` 的词条；为 false 时不排除。
- 随机模式只能在完成 memberships 和 evaluated 过滤后的候选池上 shuffle/sample，然后无放回取 `min(requestedCount, candidateCount)` 个词条。同一文档内不得重复词条；契约不规定 Python/Kotlin 在相同 seed 下产生相同顺序。
- 手选模式只使用用户明确选择且仍满足过滤条件的词条，不得自动补充。所选数量为零时禁止导出。
- 手选数量大于零但少于 `requestedCount` 时，必须显示以下精确确认文案模板；花括号参数以十进制整数替换，不保留花括号：

```text
当前仅选择了{selectedCount}/{requestedCount}，是否确定选择
```

按钮文案固定为 `确定选择` 和 `返回选择`。选择 `返回选择` 时不得写文件或更新 tags。

### 手选词条表格

Windows 与 Android 的手选词条 UI 必须按以下固定顺序展示列：`word`、
`meaning`、`tags`、`evaluationStatus`、`selected`，对应文案为“单词”、
“中文释义”、“标签”、“考察状态”、“选择”。

- `meaning` 显示词条的完整中文释义。表格可视宽度不足时必须允许横向滚动，
  不得通过永久截断隐藏其余列或释义内容。
- `tags` 显示词条有效 tags 的稳定、小写、字典序列表，以 ` / ` 分隔；
  `evaluated` 不在该列重复展示。没有其他 tag 时显示 `-`。
- 有效 tags 包含 `evaluated` 时，`evaluationStatus` 显示“已考察”并使用黑色；
  否则显示“未考察”并使用红色。
- `selected` 必须使用逐行复选框，勾选状态与手选 ID 集合双向同步。
- 表头与每一行必须保持相同列宽，纵向浏览不得破坏横向对齐。

## evaluated 与 tags

标记偏好枚举固定为 `ASK`、`ALWAYS`、`NEVER`，默认 `ASK`。至少一个所选格式成功写出后，才对本次实际写出的词条执行偏好；全部格式失败时不得更新 tags。

- `ASK`：显示 `是否将本次导出的词条标记为 evaluated？`，按钮为 `标记`、`不标记`，并显示默认未勾选的复选框 `不再提示`。本次选择立即生效；未勾选时偏好保持 `ASK`。勾选后，选择 `标记` 必须持久化为 `ALWAYS`，选择 `不标记` 必须持久化为 `NEVER`。
- `ALWAYS`：直接添加 `evaluated`。
- `NEVER`：不添加 `evaluated`。

`evaluated` 必须写入本地 tag override，不能写回 catalog。UI 可增删的 tags 固定为 `cet4`、`cet6`、`gk`、`zk`、`evaluated`，比较大小写不敏感并以小写持久化；UI 不得提供创建任意 tag 的能力。catalog 中其他既有 tag 保持只读，不得因本规则被删除或改写。内置 catalog 始终只读，导出、自填例句和 tag override 都不得修改它。

## Golden tests 与版本

`dictation-export-golden-v1.json` 是 Python/Kotlin 测试共同读取的 UTF-8 JSON，覆盖中英文、词性、例句完整边界、全部替换、自填例句覆盖和 Unicode 下划线。所有数量均为十进制 JSON number，所有预期文本均为精确字符串。

契约版本固定为 `dictation-export-v1`。字段、默认值、边界、文案或处理算法发生不兼容变化时必须提升契约版本，并在同一功能提交中同步 Windows、Android、共享契约和测试。
