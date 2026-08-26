# BlueSea 架构与产品对比分析

## 分析范围

- 分析日期：2026-08-26。
- BlueSea 上游：`https://github.com/jiangqizheng/BlueSea`。
- 本地克隆：`C:\Users\12254\Desktop\projects\BlueSea`。
- 默认分支基线：`main@e7f2af8`，最后提交于 2020-12-24。
- 对比项目基线：LexiTrack `main@e5d04af`。
- 方法：完整 Git 克隆、目录与配置侦察、关键数据流静态追踪、Git 历史检查、Manifest 解析和主要 JavaScript 语法检查。

BlueSea 的 `v2` 远端分支比 `main` 多 4 个提交，最后更新于 2021-06-30，包含 React 17、Webpack 5、TypeScript 配置和 NLP/API 目录，但最新提交名为“临时保存”，且不是默认分支。本文以默认分支的实际产品为主，只把 `v2` 视为未完成的现代化尝试。

`v2` 也没有解决发布与质量问题：它仍是 Manifest V2，申请了 cookies、`webRequestBlocking` 和全网址等更广权限；API 客户端硬编码 `http://localhost:3001`，部分类型声明残留作者机器路径，本地写入与远程失败之间缺少可靠回滚，仍没有测试或 CI。因此，标签、账号 API 和 NLP 只能列为设计线索，不能写成 BlueSea 已交付能力。

## 结论摘要

BlueSea 最有价值的不是背词算法，而是“在真实网页中采集生词，再在真实网页中再次遇见并复习”的产品闭环。划词翻译、来源 URL、全页高亮、按页面统计词频和弹幕复习，把学习嵌入了用户原本的阅读行为，这是 LexiTrack 当前没有覆盖的场景。

工程层面则相反：BlueSea 是一个 Manifest V2 扩展，`logic.js` 同时承担存储、业务规则、Chrome API 和 UI hooks，不是洋葱架构；仓库没有自动测试、CI、现代构建流程或明确许可证，并存在可能删除已完成词记录的数据完整性问题。它适合做产品研究，不适合直接复制代码。

建议保留 LexiTrack 现有双端洋葱架构和共享契约，把 BlueSea 的优势转译为新的领域概念与适配器：先增加“遇见记录/来源上下文”和可撤销评分，再评估独立的 Manifest V3 浏览器伴侣扩展。Windows 与 Android 仍应同步支持这些数据的查看、筛选、导入和复习语义。

## BlueSea 入门指南

### 技术栈

| 层级 | 实际技术 | 说明 |
|---|---|---|
| 运行形态 | Chrome Extension Manifest V2 | `browser_action`、传统 background scripts、`<all_urls>` content scripts |
| 语言 | 原生 JavaScript、HTML、CSS | 默认分支没有 TypeScript 或包管理器 |
| UI | vendored Preact/HTM 兼容运行时 | 使用 `html`、`render`、`useState`、`useEffect` 等全局 API |
| 时间 | Day.js | 固定遗忘曲线和日期聚合 |
| 配置编辑 | CodeMirror | 用户可直接编辑完整 JSON 配置 |
| 持久化 | `chrome.storage.local` | `materials` 和 `config` 两个键，整表读写 |
| 网络 | 腾讯云 API Gateway、有道音频 URL | 翻译文本和可选 key 通过 URL query 发送 |
| 测试/CI | 无 | 没有测试目录、运行器、lint 或 GitHub Actions |

### 架构图

```text
                         Chrome runtime message
网页 Selection/Tip ------------------------------------+
       |                                                |
       v                                                v
Content scripts --> logic.js / BlueSea facade --> background.js --> 翻译网关
       |             |          |                      |
       |             |          +--> chrome.tabs       +--> 有道数据
       |             +--> dayjs / learning rules
       |             +--> chrome.storage.local <-------+
       |                         ^
       +--> Highlighter/Barrage  |
                                 |
Popup components ----------------+
```

这是“浏览器扩展三运行上下文 + 共享全局业务门面”结构：

- background 处理翻译请求和高亮粗筛计算。
- content scripts 注入网页，负责划词、浮层、高亮、统计和弹幕。
- popup 提供查词、词库、卡片和配置界面。
- `logic.js` 被三个上下文共同加载，混合存储、学习规则、统计、排序和 UI hooks。

它不是洋葱架构，也不是标准 MVVM。UI 会直接调用 `bluesea`、`chrome.tabs` 和底层 `materialsDB`；领域规则无法脱离 Chrome/DOM/Day.js 单独测试。

### 关键入口与目录

| 位置 | 职责 |
|---|---|
| `manifest.json` | 权限、background、popup 和 content scripts 的装载顺序 |
| `logic.js` | Storage 包装、BlueSea 门面、遗忘曲线、排序、统计、功能开关 |
| `background/background.js` | `tf` 翻译消息、`calcEls` 文本预筛 |
| `content_scripts/selection.js` | 网页划词入口与输入过滤 |
| `content_scripts/tip.jsx` | 翻译浮层、发音和收藏 |
| `content_scripts/highlighter.js` | DOM 扫描、高亮、悬停释义、词频快照 |
| `content_scripts/bullet-screens.jsx` | 到期词弹幕、认识/不认识和撤销 |
| `popup/app.js` | 查词、词库、配置三个 tab 的入口 |
| `popup/page-material.js` | 词库、卡片、排序、导入导出 |
| `popup/page-setting.js` | 功能开关、域名黑名单和 JSON 配置 |
| `lib/` | 直接提交到仓库的第三方运行时和编辑器代码 |

### 典型数据流

```text
用户划选英文
  -> selection.js 过滤中文、短文本、特殊符号、超长 token、pre/code
  -> tip.jsx 发送 {type: "tf"}
  -> background.js 先查已收藏词，未命中则请求翻译网关
  -> 点击收藏，logic.js 创建 material
  -> chrome.storage.local["materials"]
  -> storage change 触发页面高亮和词频快照
  -> learnDate 到期后显示弹幕或 popup 卡片
  -> 认识：level + 1；不认识：level 归零
  -> 整表写回 chrome.storage.local
```

material 的核心字段包括 `text`、`textExts`、`translation`、`ctime`、`learn`、完整 `youdao` 响应和 `addFrom` 来源 URL。复习曲线是固定九档：5 分钟、30 分钟、12 小时、1/2/4/7/15/30 天。

### 代码与 Git 约定

- 文件名主要为 lowercase kebab-case，类和组件用 PascalCase，函数和方法用 camelCase。
- 配置键是中文字符串，持久化键是英文小写。
- 异步代码主要使用 `async/await`，并用 Promise 包装 Chrome callback API。
- 错误处理多为局部 `try/catch + alert`；网络请求没有统一超时、重试或错误模型。
- 默认分支有 42 个提交；提交信息混用 `feat:`、`fix:`、`docs:`、emoji 和无前缀中文，约定不严格。

### 构建、运行与测试

默认分支没有构建命令。历史 README 的运行方式是进入 `chrome://extensions/`，选择“加载已解压的扩展程序”并加载仓库根目录。由于 Manifest V2 已被现代 Chrome 淘汰，这不再等价于可部署验证。

本次验证结果：

- `manifest.json` 可解析，版本为 `0.0.1`、`manifest_version=2`。
- `logic.js`、background、popup 和主要 content script `.js` 文件通过 Node 22 `--check`。
- `git fsck --connectivity-only` 通过，BlueSea 克隆工作树干净。
- 无自动测试、lint、覆盖率或 CI 命令可运行。
- 仓库根目录没有 `LICENSE`、`LICENSE.md` 或 `COPYING`；`v2/package.json` 的 ISC 元数据不能替代默认分支的明确许可证文件。

## 核心特色功能核验

| 功能 | 实际实现 | 边界或偏差 |
|---|---|---|
| 划词翻译与收藏 | 读取 Selection、显示定位浮层、发音并收藏单词 | 句子/词组只能翻译；含中文、特殊符号、`pre/code` 等会跳过 |
| 全页高亮 | 大小写不敏感匹配，英文字符边界检查，悬停显示释义 | 仅顶层普通 DOM 文本；不覆盖 iframe、Shadow DOM、Canvas、输入框或跨节点短语 |
| 词频统计 | 按日期和完整 URL 保存页面命中数，支持当前页/当天/总量排序 | 同一 URL 保存历史最大快照，不是累计阅读曝光次数 |
| 单词弹幕 | 到期词横向滚动，悬停暂停/发音，可选择认识或不认识 | 只在可见顶层网页运行，失焦清空，不是系统后台提醒 |
| 操作撤销 | 弹幕评分后可恢复操作前 material | 写入未串行，最终一级撤销存在竞态与误替换风险 |
| popup 卡片 | 翻面查看词典数据、来源、词频和学习状态 | 不是连续复习队列；弹幕开启时禁止卡片评分 |
| 遗忘曲线 | 认识升一级，不认识归零，九档固定时间 | 不是个性化算法，没有四档熟悉度、难度或答题耗时 |
| 导入导出 | TXT 单词列表、JSON 完整对象；增量导入 | TXT 在线逐词翻译且每次最多 20 条；JSON 只做浅层字段校验 |
| 配置与黑名单 | 三主开关、当前域名开关、JSON 编辑和重置 | 黑名单仅 hostname 精确匹配；配置无 schema 和默认值合并 |

## 主要工程风险

1. **数据完整性**：`getMaterials()` 默认过滤 `learn.done`，但添加、更新和复习又把这个过滤后的数组整体写回。存在已完成词时，后续操作可能永久删除这些记录；最终一级撤销还可能因 `findIndex=-1` 而替换错误词条。
2. **平台兼容**：Manifest V2、`browser_action` 和持久 background page 已不适合作为 2026 年的新实现基础，必须迁移到 Manifest V3 service worker。
3. **隐私与密钥**：选中文本、appkey 和 key 以 URL query 发往硬编码网关，可能进入网络基础设施日志。README 对服务端“不记录”的声明无法由客户端仓库证明。
4. **性能**：动态页面每 4 秒重扫 DOM；README 的“页面 100+ 单词、词库 5000+”是手工声明，没有可重复 benchmark。
5. **输入与异常处理**：配置和 JSON 导入没有完整 schema；网络失败可能令翻译浮层一直 loading；TXT 导入缺少事务和失败恢复。
6. **维护与分发**：没有自动测试、CI、依赖清单和默认分支许可证，不能直接作为可靠或可再分发的代码依赖。

## 与 LexiTrack 对比

| 维度 | BlueSea | LexiTrack | 判断 |
|---|---|---|---|
| 产品场景 | 浏览器阅读中的即时采集与复现 | Windows/Android 独立学习、复习和提醒 | 两者互补，不是同类替代 |
| 架构 | 三扩展上下文 + 全局门面，强耦合 | 双端洋葱架构、端口、组合根、共享契约 | LexiTrack 更适合持续开发 |
| 平台 | 旧 Chrome MV2 | Windows + Android | BlueSea 覆盖网页上下文，LexiTrack 覆盖桌面/移动学习 |
| 词汇来源 | 用户在网页中收藏，附来源 URL | 内置 7,116 词、CET4/CET6 membership + CSV 自定义词库 | BlueSea 的上下文来源值得吸收 |
| 学习顺序 | 到期列表首项，词库支持多种排序 | 默认随机，可切字母排序，学习组多选 | LexiTrack 的会话控制更完整 |
| 复习模型 | 二档反馈、固定九级曲线 | 四档评分、`lexi-sm2-v1` 排期 + 独立权重无放回抽样 | LexiTrack 更细致且有 golden tests |
| 提醒 | 前台网页弹幕 | Windows 置顶卡；Android 前台卡片/后台通知 | BlueSea 更沉浸，LexiTrack 更可靠 |
| 内容质量 | 翻译 API 原始数据，没有例句质量门禁 | 中文释义、词书 membership、至少三组双语例句 | LexiTrack 内容契约更强 |
| 分组与标签 | 无分组，计划中 | CET4/CET6/CUSTOM 多选，学习/复习/提醒独立 | LexiTrack 已领先 |
| 遇见统计 | 日期 + URL 页面快照 | 复习活动、到期预测和保持率 | BlueSea 的真实语境统计是明显空白点 |
| 导入导出 | TXT/JSON，校验较弱 | RFC 4180 CSV v1、逐行稳定错误码 | LexiTrack 更适合可控迁移 |
| 离线与隐私 | 本地存储，但翻译/发音依赖网络 | 核心学习完全离线 | LexiTrack 隐私边界更清楚 |
| 质量保障 | 无测试、lint、CI | Windows/Android 测试、同步校验、双端 CI 和构建产物 | LexiTrack 明显更成熟 |
| 可扩展性 | 功能直接共享全局对象和整表存储 | domain/application/infrastructure/presentation 分层 | 新功能应落在 LexiTrack 架构中 |

## 值得吸收的产品设计

### P0：遇见记录与来源上下文

最值得吸收的是 `word + source URL/title + encounteredAt + context snippet`，而不是 BlueSea 的整表存储实现。建议：

- 在 `shared/contracts/` 定义 `encounter-v1`，明确 URL 可选、隐私裁剪、去重和保留期。
- Windows 与 Android domain 增加不可变 `EncounterRecord`，application 增加记录、查询和聚合用例。
- 两端 UI 同步展示“最近在哪里遇见”“今日遇见次数”和按遇见频率排序。
- 浏览器伴侣可通过契约化导入贡献记录；Android 可评估 Share Target 作为平台采集入口。
- 默认只保存在本机；导出前明确提示来源 URL 可能包含敏感信息。

### P1：可撤销评分

撤销能降低误触成本，但应采用操作日志或前一状态快照：

- domain 定义可恢复的 `ReviewTransition`，不直接回写任意旧对象。
- application 串行执行 rate/undo，并限制只能撤销当前会话最后一次操作。
- Windows 和 Android 同步增加撤销入口及领域测试、持久化测试。

### P1：现代浏览器伴侣扩展

若要完整获得 BlueSea 的优势，建议新建可选的 Manifest V3 伴侣，而不是把 DOM/Chrome API 放入现有客户端：

```text
Browser presentation/content script
  -> CaptureEncounterUseCase
  -> TranslationPort / EncounterRepository ports
  -> Chrome storage or explicit local export adapter
  -> versioned encounter-v1 interchange
  -> Windows/Android import and display
```

扩展只负责浏览器特有的 Selection、DOM 高亮和来源采集；复习算法、词条规范化、隐私规则和交换格式进入共享契约。若将浏览器列为正式第三平台，`parity.json` 应明确哪些能力是跨三端、哪些是 browser-only。

### P2：语境高亮与遇见频率

- 高亮应使用 Unicode-aware tokenization，并避开 editable、code、Shadow DOM 等边界。
- 动态页面优先使用有界 MutationObserver/增量索引，而不是固定周期全 DOM 扫描。
- 统计应记录不可变 encounter 事件，或清楚命名为 page snapshot，避免把最大快照误称累计词频。

### P2：可选的轻量复习流

可借鉴弹幕的低打扰形式，但它只能是 presentation 策略：

- 不能决定 popup/主页面是否允许评分。
- Windows 和 Android 应提供语义一致的“轻量提醒模式”，具体视觉可以平台化。
- 后台调度仍通过现有 application 用例和 Android 系统通知适配器完成。

### P2：版本化备份与恢复

BlueSea 的 JSON 导出提示了完整本地备份的价值，但不能沿用其浅校验格式。建议为词库、标签、学习排期、已学词权重、设置和 encounter 数据定义带 schema/version/checksum 的备份契约，并让 Windows 与 Android 使用同一迁移与错误报告语义；现有 CSV v1 继续只承担词库交换。

## 不应直接移植的部分

- 不复制 `logic.js` 全局门面、Chrome API 直连和整表读写。
- 不沿用 Manifest V2、`<all_urls>` 默认权限和持久 background page。
- 不把中文字符串配置键或可任意编辑的原始 JSON 作为公共设置契约。
- 不复用“过滤后整表覆写”、浅层 JSON 校验或未串行的撤销逻辑。
- 不把固定二档九级曲线替换现有 `lexi-sm2-v1` 和加权复习。
- 在许可证不明确前，不复制源代码或第三方 vendored 文件；仅吸收可独立实现的产品理念。

## 建议路线

1. 先写 `encounter-v1` 与隐私决策记录，明确跨端字段、去重、来源裁剪和导入导出语义。
2. 在 Windows/Android 同步实现 Encounter domain、repository port、application 用例、持久化和列表展示。
3. 增加最后一次评分撤销的共享契约和 golden vectors，双端同步实现。
4. 定义版本化全量备份/恢复契约，并为两端补迁移、损坏输入和往返测试。
5. 单独建立 Manifest V3 浏览器伴侣原型，只通过版本化交换契约对接，不反向污染现有内层。
6. 用可重复基准验证 100/1,000/5,000 词索引和动态网页高亮，再决定是否产品化。

## 查找位置

| 我想了解…… | BlueSea | LexiTrack |
|---|---|---|
| 启动与运行上下文 | `manifest.json` | `windows/main.py`、Android `AppContainer.kt` |
| 学习/调度规则 | `logic.js` | 两端 domain scheduler + shared golden contracts |
| 存储 | `logic.js: Storage` | 两端 infrastructure repositories |
| 网页采集 | `content_scripts/selection.js` | 当前无对应能力 |
| 高亮与统计 | `content_scripts/highlighter.js` | 当前无来源/遇见统计 |
| 轻量复习 | `content_scripts/bullet-screens.jsx` | 两端 reminder presentation/adapters |
| 词库与导入 | `popup/page-material.js` | 两端 application/import infrastructure + CSV v1 |
| 跨端能力状态 | 无 | `shared/contracts/parity.json` |
