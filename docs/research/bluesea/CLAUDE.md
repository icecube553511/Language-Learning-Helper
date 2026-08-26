# BlueSea 项目说明

> 此文件由 2026-08-26 对 `main@e7f2af8` 的静态分析生成。上游仓库原先没有 CLAUDE.md。

## 项目定位

BlueSea 是 Chrome 英语学习扩展：在网页中划词翻译和收藏，在后续网页中高亮收藏词，并通过弹幕或 popup 卡片复习。

## 技术栈

- 默认分支：原生 JavaScript、HTML、CSS，Chrome Extension Manifest V2。
- UI：仓库内 vendored Preact/HTM 兼容运行时。
- 时间：Day.js；配置编辑：CodeMirror。
- 持久化：`chrome.storage.local` 的 `materials`、`config` 键。
- 网络：background 翻译网关和有道音频 URL。

## 现有架构

```text
popup + content scripts + background
            -> shared logic.js facade
            -> chrome.storage / chrome.tabs / dayjs / network
```

现有代码不是洋葱架构。`logic.js` 混合存储、学习规则、统计和 UI hooks；部分 UI 直接访问 Chrome API 与 `materialsDB`。

## 关键入口

- `manifest.json`：运行上下文、权限和脚本装载顺序。
- `logic.js`：Storage、BlueSea、遗忘曲线、统计和功能控制。
- `background/background.js`：翻译和文本预筛消息。
- `content_scripts/selection.js`：划词入口。
- `content_scripts/highlighter.js`：DOM 高亮和页面词频。
- `content_scripts/bullet-screens.jsx`：到期弹幕复习。
- `popup/page-material.js`：词库、卡片、导入导出。
- `popup/page-setting.js`：配置与黑名单。

## 修改规则

- 新开发必须以 Manifest V3 为目标，不继续扩展 MV2 持久 background 架构。
- 浏览器 API 只能留在外层 adapter；学习规则不得直接依赖 DOM、Chrome API 或 UI hooks。
- 将持久化端口、翻译端口、学习用例和 UI 状态分离，不再扩大 `logic.js`。
- 永远从完整 materials 集合写回存储；展示过滤不得改变持久化输入。
- 复习和撤销写入必须串行，并以稳定 ID 定位，不允许 `splice(-1, ...)`。
- 配置与导入数据必须使用版本化 schema、类型校验和迁移。
- 新权限采用最小范围；不要默认申请 `<all_urls>`，优先按站点授权。
- 翻译密钥不得放入 URL query；网络层需要超时、错误分类和用户可见恢复。
- 不把页面最大快照称为累计词频；统计语义必须在模型和 UI 中一致。
- 未确认许可证前，不复制上游或 vendored 代码到其他项目。

## 数据模型

material 现有字段：`text`、`textExts`、`translation`、`ctime`、`learn`、`youdao`、`addFrom`、可选 `statistics`。任何 schema 修改都要保留旧数据迁移和往返测试。

## 代码风格

- 文件主要使用 lowercase kebab-case。
- 类/组件使用 PascalCase；函数/方法使用 camelCase。
- 现有异步代码以 `async/await` 为主；新代码避免手工 Promise 包装可替代的 API。
- 错误必须进入统一结果模型；不要只依赖 `alert` 或 `console.error`。

## 构建与测试

- 遗留运行方式：在 Chrome 扩展页加载仓库根目录。现代 Chrome 已淘汰 MV2，不能视为有效发布流程。
- 默认分支没有 build、test、lint 或 CI 命令。
- 修改前先为学习曲线、storage migration、导入校验、消息处理和 DOM 边界建立自动测试。
- 最低检查：解析 `manifest.json`，对 JavaScript 运行 `node --check`，并进行浏览器端集成测试。

## Git

- 历史提交常见 `feat:`、`fix:`、`docs:`，也混有 emoji 和无前缀中文。
- 新提交统一使用短前缀风格，并把迁移、测试和文档放在同一功能提交。
- `v2` 是非默认、未完成的现代化分支；不要误将其当作当前发布基线。

