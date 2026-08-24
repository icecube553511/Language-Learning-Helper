package com.lexitrack.learning.domain

enum class ImportRowStatus {
    IMPORTED,
    SKIPPED,
    FAILED,
}

data class ImportRowResult(
    val row: Long,
    val status: ImportRowStatus,
    val word: String? = null,
    val field: String? = null,
    val errorCode: String? = null,
    val message: String,
)

data class ImportReport(
    val totalRows: Int,
    val imported: Int,
    val skipped: Int,
    val failed: Int,
    val rows: List<ImportRowResult>,
    val warnings: List<String> = emptyList(),
) {
    companion object {
        val Empty = ImportReport(0, 0, 0, 0, emptyList())
    }
}

data class ImportBatch(
    val entries: List<VocabularyEntry>,
    val report: ImportReport,
)
