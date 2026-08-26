package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.DictationRow
import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidDictationExporterTest {
    private val document = DictationDocument(
        listOf(DictationRow("t_____", "n.", "测试 & 释义", listOf("A _____ example"))),
        DictationDocumentOptions(fontSizePt = 18),
    )

    @Test fun `docx is an OOXML zip with A4 and escaped XML`() {
        val bytes = AndroidDictationExporter().export(document, DictationFormat.DOCX).bytes
        val entries = mutableMapOf<String, String>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes().toString(Charsets.UTF_8)
            }
        }
        assertTrue(entries.containsKey("word/document.xml"))
        assertTrue(entries.getValue("word/document.xml").contains("w:w=\"11906\""))
        assertTrue(entries.getValue("word/document.xml").contains("w:h=\"16838\""))
        assertTrue(entries.getValue("word/document.xml").contains("w:val=\"36\""))
        assertTrue(entries.getValue("word/document.xml").contains("&amp;"))
    }

    @Test fun `pdf has magic and A4 page`() {
        val bytes = AndroidDictationExporter().export(document, DictationFormat.PDF).bytes
        assertEquals("%PDF", bytes.copyOfRange(0, 4).toString(Charsets.US_ASCII))
        val pdfText = bytes.toString(Charsets.ISO_8859_1)
        assertTrue(pdfText.contains("/MediaBox [0 0 595 842]"))
    }

    @Test fun `empty document is rejected`() {
        val empty = DictationDocument(emptyList(), DictationDocumentOptions())
        org.junit.Assert.assertThrows(IllegalArgumentException::class.java) {
            AndroidDictationExporter().export(empty, DictationFormat.PDF)
        }
    }
}
