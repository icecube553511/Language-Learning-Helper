# 架构说明

## 决策

LexiTrack 使用单一 monorepo 维护两个离线客户端。Windows 与 Android 可以使用各自最稳定的平台 UI 技术，但必须服从版本化的共享契约、品牌资产和 golden tests。

```text
Presentation  --->  Application  --->  Domain
       |                  |              ^
       +------------------+--------------|
                          Infrastructure -+
```

- `Domain`：词条、复习状态、已学词权重、评分与 `lexi-sm2-v1` 调度；不引用平台 API。
- `Application`：总览、学习抽卡、加权复习会话、评分、导入、搜索、预测复习量等用例和端口。
- `Infrastructure`：JSON/SharedPreferences 持久化、独立 `Words_Learnt`、内置词库、CSV 解析、系统文件选择器。
- `Presentation`：Tkinter 或 Compose 页面、状态与无障碍语义。
- Composition Root：唯一负责组装具体实现的最外层入口。

跨端品牌源资产位于 `shared/assets/branding/`。平台最外层的图标资源由此派生，不得由 `domain` 或 `application` 直接引用。

## 一致性边界

双端必须共享以下语义：

- `VocabularyEntry` 的规范化 ID、词书 membership、中文释义及至少三组双语例句。
- `ReviewState` 的 UTC 时间、评分枚举、间隔、熟练度、复习次数和遗忘次数。
- CSV v1 的列、编码、校验、重复处理和逐行错误代码。
- `lexi-sm2-v1` 的四档评分计算及 golden vectors。
- `weighted-review-v1` 的初始/更新权重、无放回会话、批次数量和旧数据迁移语义。
- 字体缩放范围 `0.9..1.4`、每日新词/复习上限及版本字段。

## 数据与隐私

核心学习完全离线，无账号、广告或后台上传。Windows 数据保存在用户应用数据目录，Android 数据保存在应用私有目录。Android CSV 选择使用 Storage Access Framework，不申请广泛存储权限。

## 内容门禁

内置词库发布前必须验证：稳定 ID 唯一、中文释义非空、CET membership 合法、至少三条不同的英文例句且每条中文翻译非空、来源和内容版本存在。导入词条使用同一套最小内容规则。
