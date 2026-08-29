package com.lexitrack.learning.infrastructure

import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import com.lexitrack.learning.application.DictationExporter
import com.lexitrack.learning.application.ExportedDictation
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationFormat
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.math.max

internal fun dictationPdfPageInfo(pageNumber: Int): PdfDocument.PageInfo =
    PdfDocument.PageInfo.Builder(595, 842, pageNumber).create()

class AndroidDictationExporter : DictationExporter {
    override fun export(document: DictationDocument, format: DictationFormat): ExportedDictation = when (format) {
        DictationFormat.PDF -> exportPdf(document)
        DictationFormat.DOCX -> exportDocx(document)
    }

    private fun exportPdf(document: DictationDocument): ExportedDictation {
        require(document.rows.isNotEmpty()) { "不能导出空默写文档" }
        val pdf = PdfDocument()
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = document.options.fontSizePt.toFloat() }
        val lineHeight = max(paint.textSize * 1.6f, 16f)
        var page: PdfDocument.Page? = null
        var canvas = page?.canvas
        var y = 36f
        var pageNumber = 0
        fun startPage() {
            pageNumber += 1
            page = pdf.startPage(dictationPdfPageInfo(pageNumber))
            canvas = page!!.canvas
            y = 36f
        }
        fun drawLine(text: String) {
            if (page == null || y > 806f) {
                page?.let(pdf::finishPage)
                startPage()
            }
            canvas!!.drawText(text, 36f, y, paint)
            y += lineHeight
        }
        fun line(text: String) {
            var remaining = text
            while (remaining.isNotEmpty()) {
                var count = paint.breakText(remaining, true, 523f, null).coerceAtLeast(1)
                if (count < remaining.length) {
                    val breakAt = remaining.substring(0, count).lastIndexOf(' ')
                    if (breakAt > 0) count = breakAt
                }
                if (count < remaining.length && count > 0 && Character.isHighSurrogate(remaining[count - 1])) count -= 1
                count = count.coerceAtLeast(1)
                drawLine(remaining.substring(0, count).trimEnd())
                remaining = remaining.substring(count).trimStart()
            }
            if (text.isEmpty()) drawLine("")
        }
        val output = ByteArrayOutputStream()
        try {
            document.rows.forEachIndexed { index, row ->
                line("${index + 1}. ${row.word}  ${row.partOfSpeech}  ${row.meaning}")
                row.examples.forEachIndexed { offset, example ->
                    val chinese = row.exampleChinese.getOrNull(offset).orEmpty()
                    line("   e.g. $example" + if (chinese.isNotEmpty()) "（$chinese）" else "")
                }
                y += lineHeight * .35f
            }
            page?.let(pdf::finishPage)
            pdf.writeTo(output)
        } finally {
            pdf.close()
        }
        return ExportedDictation(output.toByteArray(), "dictation.pdf", "application/pdf")
    }

    private fun exportDocx(document: DictationDocument): ExportedDictation {
        require(document.rows.isNotEmpty()) { "不能导出空默写文档" }
        val body = buildString {
            document.rows.forEachIndexed { index, row ->
                paragraph("${index + 1}. ${row.word}  ${row.partOfSpeech}  ${row.meaning}", document.options.fontSizePt)
                row.examples.forEachIndexed { offset, example ->
                    val chinese = row.exampleChinese.getOrNull(offset).orEmpty()
                    paragraph("    e.g. $example" + if (chinese.isNotEmpty()) "（$chinese）" else "", document.options.fontSizePt)
                }
            }
        }
        val xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>$body<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\" w:orient=\"portrait\"/><w:pgMar w:top=\"720\" w:right=\"720\" w:bottom=\"720\" w:left=\"720\"/></w:sectPr></w:body></w:document>"
        val contentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>"
        val rels = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>"
        val output = ByteArrayOutputStream()
        ZipOutputStream(output).use { zip ->
            fun entry(name: String, value: String) { zip.putNextEntry(ZipEntry(name)); zip.write(value.toByteArray(Charsets.UTF_8)); zip.closeEntry() }
            entry("[Content_Types].xml", contentTypes)
            entry("_rels/.rels", rels)
            entry("word/document.xml", xml)
        }
        return ExportedDictation(output.toByteArray(), "dictation.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }

    private fun StringBuilder.paragraph(text: String, fontSizePt: Int) {
        append("<w:p><w:r><w:rPr><w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\" w:eastAsia=\"Microsoft YaHei\"/><w:sz w:val=\"")
        append(fontSizePt * 2)
        append("\"/></w:rPr><w:t xml:space=\"preserve\">")
        append(xmlEscape(text))
        append("</w:t></w:r></w:p>")
    }

    private fun xmlEscape(value: String): String = value
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("\"", "&quot;").replace("'", "&apos;")
}
