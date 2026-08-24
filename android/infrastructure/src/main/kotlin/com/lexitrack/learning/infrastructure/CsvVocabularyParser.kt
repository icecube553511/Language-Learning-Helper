package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.ImportBatch
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ImportRowResult
import com.lexitrack.learning.domain.ImportRowStatus
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.normalizeWordId
import java.io.InputStream
import java.io.InputStreamReader
import java.io.PushbackInputStream
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import org.apache.commons.csv.CSVFormat

class CsvVocabularyParser {
    fun parse(input: InputStream, existingIds: Set<String>): ImportBatch {
        val accepted = mutableListOf<VocabularyEntry>()
        val results = mutableListOf<ImportRowResult>()
        val seen = existingIds.mapTo(mutableSetOf()) { normalizeWordId(it) }
        val warnings = mutableListOf<String>()
        var totalRows = 0

        try {
            utf8Reader(input).use { reader ->
                val format = CSVFormat.RFC4180.builder()
                    .setHeader()
                    .setSkipHeaderRecord(true)
                    .setIgnoreEmptyLines(true)
                    .build()
                format.parse(reader).use { parser ->
                    val headers = parser.headerMap.keys
                        .map { it.removePrefix("\uFEFF").trim() }
                        .toSet()
                    val missing = REQUIRED_COLUMNS - headers
                    if (missing.isNotEmpty()) {
                        return globalFailure(
                            code = "missing_column",
                            field = missing.sorted().joinToString(","),
                            message = "缺少必填列：${missing.sorted().joinToString()}。",
                        )
                    }
                    val unknown = headers - ALL_COLUMNS
                    if (unknown.isNotEmpty()) {
                        warnings += "已忽略未知列：${unknown.sorted().joinToString()}。"
                    }

                    for (record in parser) {
                        totalRows += 1
                        val rowNumber = record.recordNumber + 1
                        val values = record.toMap().entries.associate { (key, value) ->
                            key.removePrefix("\uFEFF").trim() to value.trim()
                        }
                        val failure = validateRow(rowNumber, values)
                        if (failure != null) {
                            results += failure
                            continue
                        }

                        val word = values.getValue("word")
                        val id = normalizeWordId(word)
                        if (!seen.add(id)) {
                            results += ImportRowResult(
                                row = rowNumber,
                                status = ImportRowStatus.SKIPPED,
                                word = word,
                                field = "word",
                                errorCode = "duplicate_word",
                                message = "词条已存在，未覆盖原有内容和学习进度。",
                            )
                            continue
                        }
                        val entry = VocabularyEntry(
                            id = id,
                            word = word,
                            meaning = values.getValue("meaning"),
                            phonetic = values["phonetic"].orEmpty(),
                            levels = setOf(values["level"].orEmpty().ifBlank { "custom" }),
                            tags = values["tags"].orEmpty().split('|').map(String::trim)
                                .filter(String::isNotEmpty).toSet(),
                            mnemonic = values["mnemonic"].orEmpty(),
                            examples = (1..3).map { index ->
                                BilingualExample(
                                    english = values.getValue("example${index}_en"),
                                    chinese = values.getValue("example${index}_zh"),
                                    source = "csv",
                                )
                            },
                            source = "csv",
                        )
                        accepted += entry
                        results += ImportRowResult(
                            row = rowNumber,
                            status = ImportRowStatus.IMPORTED,
                            word = word,
                            message = "已导入。",
                        )
                    }
                }
            }
        } catch (error: Exception) {
            val invalidEncoding = generateSequence<Throwable>(error) { it.cause }
                .any { it is java.nio.charset.CharacterCodingException }
            val code = if (invalidEncoding) "invalid_encoding" else "malformed_csv"
            val message = if (invalidEncoding) "文件不是有效的 UTF-8 编码。" else "CSV 结构无法解析。"
            return globalFailure(code, null, message)
        }

        return ImportBatch(
            entries = accepted,
            report = ImportReport(
                totalRows = totalRows,
                imported = results.count { it.status == ImportRowStatus.IMPORTED },
                skipped = results.count { it.status == ImportRowStatus.SKIPPED },
                failed = results.count { it.status == ImportRowStatus.FAILED },
                rows = results,
                warnings = warnings,
            ),
        )
    }

    private fun validateRow(row: Long, values: Map<String, String>): ImportRowResult? {
        REQUIRED_COLUMNS.firstOrNull { values[it].isNullOrBlank() }?.let { field ->
            return failure(row, values["word"], field, "empty_required", "必填字段不能为空。")
        }
        values.entries.firstOrNull { (field, value) ->
            value.length > if (field == "word") 100 else 2000
        }?.let { (field, _) ->
            return failure(row, values["word"], field, "too_long", "字段超过允许长度。")
        }
        val level = values["level"].orEmpty().ifBlank { "custom" }
        if (level !in VALID_LEVELS) {
            return failure(row, values["word"], "level", "invalid_level", "level 只能是 CET4、CET6 或 custom。")
        }
        val normalizedExamples = (1..3).map { values.getValue("example${it}_en").lowercase() }
        if (normalizedExamples.distinct().size != normalizedExamples.size) {
            return failure(row, values["word"], "examples", "duplicate_example", "三条英文例句必须互不相同。")
        }
        return null
    }

    private fun failure(
        row: Long,
        word: String?,
        field: String?,
        code: String,
        message: String,
    ) = ImportRowResult(row, ImportRowStatus.FAILED, word, field, code, message)

    private fun globalFailure(code: String, field: String?, message: String) = ImportBatch(
        entries = emptyList(),
        report = ImportReport(
            totalRows = 0,
            imported = 0,
            skipped = 0,
            failed = 1,
            rows = listOf(failure(1, null, field, code, message)),
        ),
    )

    private fun utf8Reader(input: InputStream): InputStreamReader {
        val stream = PushbackInputStream(input, 3)
        val prefix = ByteArray(3)
        val read = stream.read(prefix)
        val hasBom = read == 3 && prefix.contentEquals(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()))
        if (!hasBom && read > 0) stream.unread(prefix, 0, read)
        val decoder = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
        return InputStreamReader(stream, decoder)
    }

    private companion object {
        val REQUIRED_COLUMNS = setOf(
            "word", "meaning",
            "example1_en", "example1_zh",
            "example2_en", "example2_zh",
            "example3_en", "example3_zh",
        )
        val OPTIONAL_COLUMNS = setOf("phonetic", "level", "tags", "mnemonic")
        val ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
        val VALID_LEVELS = setOf("CET4", "CET6", "custom")
    }
}
