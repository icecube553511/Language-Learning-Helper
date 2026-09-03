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
- `includeExampleChinese=true` 且 `includeExample=true` 时，renderer 将选中例句的中文翻译作为该行的一部分输出，格式为 `e.g. {example}（{chinese}）`；为 `false` 时保持仅英文。`includeExampleChinese` 只影响 renderer 的例句行，不影响例句的英文选择、挖空或计数。中文翻译取自该词条对应双语例句的中文部分；自填 `customExample` 无中文时，该行保持纯英文。
- 若词条存在 trim 后非空的 `customExample`，优先使用它作为唯一例句，并覆盖 catalog examples；空白 `customExample` 视为不存在。
- 没有有效 `customExample` 时，按 catalog 原顺序扫描双语 examples，仅取第一条英文文本 trim 后非空且包含目标词完整匹配的例句。若没有任何一条包含目标词完整匹配，则回退到 catalog 原顺序中的第一条非空英文例句。若没有非空英文例句，则该词条不输出例句。
- catalog example 是双语结构时仅取英文文本，中文翻译不得进入 worksheet。
- 当 `word` 不在 `missingFields` 中时，英文例句保持原文。`showFirstLetter` 只影响 worksheet 的 `word` 字段，不影响词性、中文、未缺失的 word 或例句。
- 当 `word` 在 `missingFields` 中时，英文例句内所有目标词都必须替换。匹配大小写不敏感，目标词按 literal 匹配；匹配片段前后若存在 ASCII 字母或数字，则不构成完整词边界。
- 例句中的每个匹配始终替换为 `blankCount(word)` 个 ASCII `_`，不显示首字母。
- 替换不得改变未匹配文本、标点、空白或例句顺序。

## 候选池与选择

- 候选词条的词书归属与分组顺序由 `vocabulary-groups-v1` 定义。默写范围浏览支持单个或多个 group key；规范 key 为 `all`、`cet4`、`cet6`、`zk`、`gk`、`custom`，也允许该契约定义的额外规范化 membership group key。`all` 只是浏览入口，不会自动勾选词条。
- `excludeEvaluated=true` 时，先从可浏览、可随机及可手选的候选池中排除有效本地 tags 包含 `evaluated` 的词条；为 false 时不排除。词书计数、只读预览与手选表必须使用相同的过滤结果。
- 随机模式先完成 group/evaluated 过滤，再处理随机候选子集：若跨分组勾选集合非空，候选池是勾选 ID 与过滤后池的交集；若勾选集合为空，则回退到当前范围的全部候选。随后 shuffle/sample，无放回取 `min(requestedCount, candidateCount)` 个词条。同一文档内不得重复词条；契约不规定 Python/Kotlin 在相同 seed 下产生相同顺序。
- 随机候选 ID、每个分组的勾选、锚点、终点、展开分组和滚动偏移均属于默写草稿状态。未知、重复或不属于当前过滤池的 ID 被忽略；明确的空勾选集合表示未启用子集，而不是空文档。
- 手选模式只使用用户明确选择且仍满足 evaluated 过滤条件的词条，不得自动补充；当前打开的 group 只限制浏览表，不清除或限制从其他 group 已选的词条。所选数量为零时禁止导出。
- 手选数量大于零但少于 `requestedCount` 时，必须显示以下精确确认文案模板；花括号参数以十进制整数替换，不保留花括号：

```text
当前仅选择了{selectedCount}/{requestedCount}，是否确定选择
```

按钮文案固定为 `确定选择` 和 `返回选择`。选择 `返回选择` 时不得写文件或更新 tags。

### 范围选择与草稿

- 每个分组维护独立的有序候选序列。顺序为 `word_id` 经 Unicode NFKC、trim、casefold 后升序；区间首尾均包含，支持向上和向下。
- 用户正向勾选一行（复选框、整行点击或拖拽）时，该词成为该分组的锚点；取消勾选不按普通点击更新锚点。
- 只有存在有效锚点时才显示逐行 `选取到这里` 操作、青色细线和箭头。点击后把锚点到终点的完整闭区间加入已选集合，区间外选择保持不变，终点成为新的锚点。区间只在同一分组内计算，不依赖可见/已组合行。
- 取消勾选后，锚点迁移到距离最近一次有效终点最近的剩余已选词；没有终点时以被取消词原位置为参照，距离相同取排序更靠前者；无剩余选择则清除锚点和终点。
- `结束范围选择` 清除锚点、终点和标记但保留勾选。切换分组、清空选择或失效 ID 也清除该分组的范围标记。
- 页面提供 `保存选择` 与应用内 `Ctrl+S`。保存快照包含模式、数量、过滤、导出配置、跨组选择、每组锚点/终点/滚动偏移、展开分组和同步元数据；预览/下载不隐式保存。
- 离开页面、返回、窗口关闭或退出时，存在未保存变化则显示 `保存`、`不保存`、`继续编辑`。`不保存` 删除当前本地快照；再次进入时为空。再次进入时自动恢复最近显式保存快照，失效 ID 丢弃、滚动位置夹到新列表范围。

### 在线同步草稿（可选）

- 草稿同步使用独立的 `dictation-draft-v1` 版本化 JSON REST 载荷，仅包含草稿和 revision 元数据，不包含词库全文、学习进度或导出文件。
- 服务地址、账号和 Bearer 凭据未配置时同步禁用，本地保存仍可用。配置后保存先本地落盘，再异步推送；启动、进入默写纸和回到前台拉取。
- 服务端 revision 使用乐观并发控制；冲突必须让用户选择本机或远端版本，并在覆盖前把未选信封加入本机加密备份（最新优先、规范化内容去重、最多三份，含删除墓碑）。备份失败时冲突保持未解决。删除通过 revision 墓碑同步。
- 传输强制 HTTPS，凭据只进平台安全存储；日志不得记录令牌、词条 ID 或草稿正文。规范化 JSON 超过 `1 MiB` 时暂停同步但不阻止本地保存。

### 进入页面的加载动画

- 每次从其他主页面进入“默写纸”时，先显示 presentation-only 的阻塞加载层，持续时间从 `1000..2000 ms`（含边界）按 `100 ms` 步长随机选择；离开页面必须取消计时与后续动画帧。
- 加载层中央必须是可辨识的打开书本，并持续显示书页从右页翻到左页再开始下一页的运动。动画帧必须实际改变书页外缘、阴影或可见页宽，不能退化为静态书本或圆环 spinner。
- 加载层结束后才展示默写设置与词书选择器。动画只属于瞬态 presentation 状态，不得写入设置、词库或学习记录。

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
- 该表格必须支持“点击整行任意位置即选择/取消该词条”，不得要求用户只点复选框。复选框与整行点击动作保持一致。
- 该表格必须支持按住左键（或长按）拖动跨越相邻行来多选/多取消词条；拖动经过的行按起始行的选中状态批量应用。

## evaluated 与 tags

标记偏好枚举固定为 `ASK`、`ALWAYS`、`NEVER`，默认 `ASK`。至少一个所选格式成功写出后，才对本次实际写出的词条执行偏好；全部格式失败时不得更新 tags。

- `ASK`：显示 `是否将本次导出的词条标记为 evaluated？`，按钮为 `标记`、`不标记`，并显示默认未勾选的复选框 `不再提示`。本次选择立即生效；未勾选时偏好保持 `ASK`。勾选后，选择 `标记` 必须持久化为 `ALWAYS`，选择 `不标记` 必须持久化为 `NEVER`。
- `ALWAYS`：直接添加 `evaluated`。
- `NEVER`：不添加 `evaluated`。

`evaluated` 必须写入本地 tag override，不能写回 catalog。UI 可增删的 tags 固定为 `cet4`、`cet6`、`gk`、`zk`、`evaluated`，比较大小写不敏感并以小写持久化；UI 不得提供创建任意 tag 的能力。catalog 中其他既有 tag 保持只读，不得因本规则被删除或改写。内置 catalog 始终只读，导出、自填例句和 tag override 都不得修改它。

## Golden tests 与版本

`dictation-export-golden-v1.json` 是 Python/Kotlin 测试共同读取的 UTF-8 JSON，覆盖中英文、词性、例句完整边界、全部替换、自填例句覆盖和 Unicode 下划线。所有数量均为十进制 JSON number，所有预期文本均为精确字符串。

契约版本固定为 `dictation-export-v1`。字段、默认值、边界、文案或处理算法发生不兼容变化时必须提升契约版本，并在同一功能提交中同步 Windows、Android、共享契约和测试。
