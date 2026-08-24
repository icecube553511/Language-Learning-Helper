package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.domain.ImportRowStatus
import java.io.ByteArrayInputStream
import java.nio.charset.StandardCharsets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CsvVocabularyParserTest {
    private val parser = CsvVocabularyParser()
    private val header = "word,meaning,phonetic,level,tags,mnemonic," +
        "example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh\r\n"

    @Test
    fun parsesBomQuotedCommaAndThreeExamples() {
        val csv = header +
            "negotiate,\"v. 谈判,协商\",/test/,CET6,business|meeting,," +
            "\"They negotiated a contract.\",他们谈成了合同。," +
            "We need to negotiate.,我们需要协商。," +
            "Negotiation takes time.,协商需要时间。\r\n"
        val bytes = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()) + csv.toByteArray()

        val result = parser.parse(ByteArrayInputStream(bytes), emptySet())

        assertEquals(1, result.report.imported)
        assertEquals("v. 谈判,协商", result.entries.single().meaning)
        assertEquals(3, result.entries.single().examples.size)
    }

    @Test
    fun keepsValidRowsAndReportsInvalidRows() {
        val valid = "valid,有效,,custom,,,One.,一。,Two.,二。,Three.,三。\r\n"
        val invalid = "broken,损坏,,custom,,,Same.,相同。,Same.,相同。,Third.,第三。\r\n"

        val result = parser.parse((header + valid + invalid).byteInputStream(), emptySet())

        assertEquals(2, result.report.totalRows)
        assertEquals(1, result.report.imported)
        assertEquals(1, result.report.failed)
        assertEquals("duplicate_example", result.report.rows.last().errorCode)
    }

    @Test
    fun skipsExistingWordsWithoutOverwriting() {
        val csv = header + "Known,已知,,CET4,,,One.,一。,Two.,二。,Three.,三。\r\n"

        val result = parser.parse(csv.byteInputStream(), setOf("known"))

        assertEquals(1, result.report.skipped)
        assertTrue(result.entries.isEmpty())
        assertEquals(ImportRowStatus.SKIPPED, result.report.rows.single().status)
    }

    @Test
    fun rejectsMissingRequiredColumn() {
        val csv = "word,meaning\r\nhello,你好\r\n"
        val result = parser.parse(csv.byteInputStream(StandardCharsets.UTF_8), emptySet())
        assertEquals("missing_column", result.report.rows.single().errorCode)
    }
}
