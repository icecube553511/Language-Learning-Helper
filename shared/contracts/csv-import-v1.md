# CSV import v1

## 编码与列

文件必须为 UTF-8 或 UTF-8 BOM，并遵循 RFC 4180。解析器必须正确处理双引号、字段中的逗号以及引号转义。

必填列：

```text
word,meaning,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
```

选填列：`phonetic,level,tags,mnemonic`。未知列忽略并在汇总中提示。`level` 可由 `CET4`、`CET6`、`custom` 中一个或多个值组成，默认 `custom`；多个词汇组和多个 `tags` 均用竖线分隔。导入后，两端都允许对导入词条批量替换词汇组和标签，内置词条只读。

```csv
word,meaning,phonetic,level,tags,mnemonic,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
negotiate,"v. 谈判,协商",/nɪˈɡəʊʃieɪt/,CET6,business|meeting,go + tiate,"They negotiated a better contract.","他们谈成了一份更好的合同。","We need to negotiate with the supplier.","我们需要与供应商协商。","""Negotiate clearly,"" the manager said.","经理说：""要清楚地协商。"""
```

## 校验

- 所有字段先 trim，word 再进行 Unicode NFKC 与不区分大小写的 ID 规范化。
- word、meaning 和三组 `en/zh` 均不得为空；三条英文例句必须互不相同。
- 单字段上限 2000 字符，word 上限 100 字符。
- 同文件重复或与现有词条重复时跳过，不覆盖既有词条和学习进度。
- 无效行不进入学习队列；有效行可以导入，结果必须提供总行数、成功、跳过、失败以及 `row/field/errorCode/message`。

标准错误码：`missing_column`、`empty_required`、`duplicate_example`、`duplicate_word`、`invalid_level`、`too_long`、`invalid_encoding`、`malformed_csv`。
