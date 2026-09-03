@file:OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)

package com.lexitrack.learning.application

import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationDraftSyncMetadata
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.PetVitals
import com.lexitrack.learning.domain.MAX_DICTATION_DRAFT_BYTES
import com.lexitrack.learning.domain.decodeDictationDraft
import java.io.InputStream
import java.time.LocalDate
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import java.math.BigDecimal
import kotlinx.serialization.ExperimentalSerializationApi

data class CatalogStatus(
    val loading: Boolean = true,
    val message: String = "正在加载词库",
    val acceptedEntries: Int = 0,
    val rejectedEntries: Int = 0,
)

data class UserSettings(
    val fontScale: Float = DEFAULT_FONT_SCALE,
    val reviewBatchSize: Int = DEFAULT_REVIEW_BATCH_SIZE,
    val studyOrder: String = STUDY_ORDER_RANDOM,
    val studyLevels: Set<String> = emptySet(),
    val reviewLevels: Set<String> = emptySet(),
    val reminderLevels: Set<String> = emptySet(),
    val reminderEnabled: Boolean = false,
    val reminderIntervalMinutes: Float = DEFAULT_REMINDER_INTERVAL_MINUTES,
    val markMode: MarkMode = MarkMode.ASK,
)

const val DEFAULT_REVIEW_BATCH_SIZE = 20
const val DEFAULT_FONT_SCALE = 1.0f
const val MIN_FONT_SCALE = 0.9f
const val MAX_FONT_SCALE = 1.4f
const val STUDY_ORDER_ALPHABETICAL = "alphabetical"
const val STUDY_ORDER_RANDOM = "random"
val SUPPORTED_VOCABULARY_LEVELS = setOf("CET4", "CET6", "CUSTOM")
const val DEFAULT_REMINDER_INTERVAL_MINUTES = 30.0f
const val MIN_REMINDER_INTERVAL_MINUTES = 0.5f
const val MAX_REMINDER_INTERVAL_MINUTES = 120.0f

/**
 * Keep persisted and transient font settings safe for Compose text layout.
 * Float.coerceIn leaves NaN unchanged, which would produce an invalid TextUnit.
 */
fun sanitizeFontScale(scale: Float): Float =
    if (scale.isFinite()) scale.coerceIn(MIN_FONT_SCALE, MAX_FONT_SCALE) else DEFAULT_FONT_SCALE

interface VocabularyRepository {
    val words: StateFlow<List<VocabularyEntry>>
    val status: StateFlow<CatalogStatus>

    suspend fun initialize()
    suspend fun importCsv(input: InputStream): ImportReport
    suspend fun updateLabels(wordIds: Set<String>, levels: Set<String>, tags: Set<String>): Int

    suspend fun updateTags(wordIds: Set<String>, add: Set<String>, remove: Set<String>): Int = 0
}

/** Opaque token owned and interpreted only by a ReviewRepository adapter. */
interface ReviewSavepoint

interface ReviewRepository {
    val schedules: StateFlow<Map<String, ScheduleState>>
    val history: StateFlow<List<ReviewEvent>>

    suspend fun saveReview(wordId: String, state: ScheduleState, event: ReviewEvent): ReviewSavepoint
    suspend fun rollbackReview(savepoint: ReviewSavepoint)
}

interface LearntWordsRepository {
    val learntWords: StateFlow<Map<String, LearntWord>>
    val petVitals: StateFlow<PetVitals>

    suspend fun saveLearntWords(words: Collection<LearntWord>)
    suspend fun saveLearningOutcome(word: LearntWord, vitals: PetVitals)
}

interface SettingsRepository {
    val settings: StateFlow<UserSettings>

    suspend fun setFontScale(scale: Float)
    suspend fun setReviewBatchSize(count: Int)
    suspend fun setStudyOrder(order: String)
    suspend fun setStudyLevels(levels: Set<String>)
    suspend fun setReviewLevels(levels: Set<String>)
    suspend fun setReminderLevels(levels: Set<String>)
    suspend fun setReminderEnabled(enabled: Boolean)
    suspend fun setReminderIntervalMinutes(minutes: Float)
    suspend fun setMarkMode(mode: MarkMode) = Unit
}

interface DictationExporter {
    fun export(document: DictationDocument, format: DictationFormat): ExportedDictation
}

/** Persistence boundary for the editable 默写纸 draft. */
interface DictationDraftRepository {
    fun get(): DictationDraft?
    fun save(draft: DictationDraft)
    fun clear()
    fun getSyncMetadata(): DictationDraftSyncMetadata?
    fun saveSyncMetadata(metadata: DictationDraftSyncMetadata)
    fun getLastSyncedEnvelope(): DictationDraftSyncEnvelope? = null
    fun saveLastSyncedEnvelope(envelope: DictationDraftSyncEnvelope) = Unit
    fun getConflictBackups(): List<DictationDraftSyncEnvelope> = emptyList()
    fun addConflictBackup(envelope: DictationDraftSyncEnvelope) = Unit
}

/** Optional online transport seam. No concrete service is enabled until the
 * user configures an HTTPS endpoint and account credentials. */
@OptIn(ExperimentalSerializationApi::class)
data class DictationDraftSyncEnvelope(
    val accountId: String,
    val revision: String = "0",
    val updatedAtUtc: Double = 0.0,
    val deleted: Boolean = false,
    val draft: DictationDraft? = null,
) {
    init {
        require(!deleted || draft == null) { "deleted envelopes must not contain a draft" }
        require(deleted || draft != null) { "non-deleted envelopes require a draft" }
    }

    /** Version marker shared by the Windows and Android wire codecs. */
    val version: String get() = DICTATION_DRAFT_SYNC_VERSION

    val isTombstone: Boolean get() = deleted

    /** Normalized copy used at the transport boundary. */
    fun normalized(): DictationDraftSyncEnvelope {
        return normalizedWithoutRecursion()
    }

    /** Canonical compact UTF-8 JSON used for both HTTP and size gates. */
    fun canonicalJson(): String = CANONICAL_SYNC_JSON.encodeToString(
        JsonElement.serializer(),
        canonicalPayload(),
    )

    fun canonicalJsonBytes(): ByteArray = canonicalJson().toByteArray(Charsets.UTF_8)

    fun byteSize(): Int = canonicalJsonBytes().size

    fun withinSizeLimit(limit: Int = MAX_DICTATION_DRAFT_BYTES): Boolean = byteSize() <= limit

    fun canonicalPayload(): JsonObject {
        val safe = normalizedWithoutRecursion()
        val fields = linkedMapOf<String, JsonElement>(
            "accountId" to JsonPrimitive(safe.accountId),
            "deleted" to JsonPrimitive(safe.deleted),
            "draft" to (if (safe.deleted) JsonNull else requireNotNull(safe.draft).canonicalPayload()),
            "revision" to JsonPrimitive(safe.revision),
            "updatedAtUtc" to JsonUnquotedLiteral(canonicalUtcNumber(safe.updatedAtUtc)),
        )
        // JsonObject preserves insertion order; sorting makes the contract
        // independent of constructor order and matches Python's codec.
        return JsonObject(fields.toSortedMap())
    }

    private fun normalizedWithoutRecursion(): DictationDraftSyncEnvelope = copy(
        accountId = accountId.trim(),
        revision = revision.trim().ifBlank { "0" },
        updatedAtUtc = updatedAtUtc.takeIf { it.isFinite() && it >= 0.0 } ?: 0.0,
        // The envelope metadata is authoritative.  Re-encoding a draft with
        // stale embedded metadata would otherwise produce different hashes on
        // Windows and Android for the same logical snapshot.
        draft = draft?.let {
            val decoded = decodeDictationDraft(it.canonicalJson()) ?: it
            decoded.copy(
                syncMetadata = com.lexitrack.learning.domain.DictationDraftSyncMetadata(
                    accountId = accountId.trim(),
                    revision = revision.trim().ifBlank { "0" },
                    updatedAtUtc = updatedAtUtc.takeIf { value -> value.isFinite() && value >= 0.0 } ?: 0.0,
                    deleted = deleted,
                ),
            )
        },
    )

    companion object {
        fun fromJson(raw: String): DictationDraftSyncEnvelope? = runCatching {
            val root = CANONICAL_SYNC_JSON.parseToJsonElement(raw).jsonObject
            fromJsonObject(root)
        }.getOrNull()

        fun fromJsonObject(root: JsonObject): DictationDraftSyncEnvelope {
            val version = root["version"]?.asString()
            require(version == null || version == DICTATION_DRAFT_SYNC_VERSION) {
                "unsupported dictation draft sync version"
            }
            val account = root["accountId"]?.asString() ?: ""
            val revision = root["revision"]?.asString() ?: "0"
            val updated = root["updatedAtUtc"]?.asDouble() ?: 0.0
            val deleted = root["deleted"]?.asBoolean() ?: false
            val draft = if (deleted) {
                null
            } else {
                val draftRaw = root["draft"]?.takeUnless { it is JsonNull }?.toString()
                    ?: throw IllegalArgumentException("non-deleted envelope requires draft")
                decodeDictationDraft(draftRaw)
                    ?: throw IllegalArgumentException("invalid dictation draft envelope")
            }
            return DictationDraftSyncEnvelope(account, revision, updated, deleted, draft).normalized()
        }

        private fun JsonElement.asString(): String? = (this as? JsonPrimitive)?.contentOrNull
        private fun JsonElement.asDouble(): Double? = asString()?.toDoubleOrNull()
        private fun JsonElement.asBoolean(): Boolean? = asString()?.toBooleanStrictOrNull()
    }
}

const val DICTATION_DRAFT_SYNC_VERSION = "dictation-draft-v1"

private val CANONICAL_SYNC_JSON = Json {
    prettyPrint = false
    encodeDefaults = true
    explicitNulls = true
}

private fun canonicalUtcNumber(value: Double): String {
    val plain = BigDecimal.valueOf(value).toPlainString()
    return if (!plain.contains('.') && !plain.contains('e', ignoreCase = true)) "$plain.0" else plain
}

enum class DictationDraftSyncStatus {
    DISABLED,
    LOCAL_ONLY,
    SYNCED,
    CONFLICT,
    TOMBSTONE,
    TOO_LARGE,
    INVALID,
}

data class DictationDraftSyncConflict(
    val local: DictationDraftSyncEnvelope,
    val remote: DictationDraftSyncEnvelope,
)

data class DictationDraftSyncResult(
    val status: DictationDraftSyncStatus,
    val envelope: DictationDraftSyncEnvelope? = null,
    val conflict: DictationDraftSyncConflict? = null,
    val message: String = "",
) {
    val disabled: Boolean get() = status == DictationDraftSyncStatus.DISABLED
    val localOnly: Boolean get() = status == DictationDraftSyncStatus.DISABLED || status == DictationDraftSyncStatus.LOCAL_ONLY
    val isLocalOnly: Boolean get() = localOnly || status == DictationDraftSyncStatus.TOO_LARGE
    val isConflict: Boolean get() = status == DictationDraftSyncStatus.CONFLICT
    val isSuccess: Boolean get() = status == DictationDraftSyncStatus.SYNCED || status == DictationDraftSyncStatus.TOMBSTONE
    val revision: String? get() = envelope?.revision
}

/** Build a transport envelope while carrying the server token from the local
 * draft.  The application layer owns this rule so both platform presenters
 * use the same optimistic-concurrency semantics. */
fun makeDictationDraftSyncEnvelope(
    accountId: String,
    draft: DictationDraft?,
    revision: String? = null,
    updatedAtUtc: Double? = null,
): DictationDraftSyncEnvelope {
    val saved = draft?.syncMetadata?.normalized()
    val effectiveAccount = accountId.trim().ifBlank { saved?.accountId.orEmpty() }
    val effectiveRevision = revision?.trim()?.takeIf { it.isNotBlank() }
        ?: saved?.revision?.takeIf { it.isNotBlank() }
        ?: "0"
    val effectiveUpdated = updatedAtUtc?.takeIf { it.isFinite() && it >= 0.0 }
        ?: saved?.updatedAtUtc?.takeIf { it.isFinite() && it >= 0.0 }
        ?: 0.0
    return DictationDraftSyncEnvelope(
        accountId = effectiveAccount,
        revision = effectiveRevision,
        updatedAtUtc = effectiveUpdated,
        deleted = draft == null,
        draft = draft,
    ).normalized()
}

/** Compare complete canonical snapshots; opaque revision tokens have no
 * ordering and equal tokens with different payloads are still conflicts. */
fun reconcileDictationDraftSyncEnvelopes(
    local: DictationDraftSyncEnvelope,
    remote: DictationDraftSyncEnvelope?,
): DictationDraftSyncResult {
    if (remote == null) {
        return DictationDraftSyncResult(
            status = if (local.deleted) DictationDraftSyncStatus.TOMBSTONE else DictationDraftSyncStatus.LOCAL_ONLY,
            envelope = local,
        )
    }
    val left = local.normalized()
    val right = remote.normalized()
    if (left.accountId != right.accountId) {
        return DictationDraftSyncResult(
            status = DictationDraftSyncStatus.INVALID,
            message = "local and remote envelopes use different accounts",
        )
    }
    if (left.revision == right.revision && left.canonicalJson() == right.canonicalJson()) {
        return DictationDraftSyncResult(
            status = if (right.deleted) DictationDraftSyncStatus.TOMBSTONE else DictationDraftSyncStatus.SYNCED,
            envelope = right,
        )
    }
    return DictationDraftSyncResult(
        status = DictationDraftSyncStatus.CONFLICT,
        envelope = right,
        conflict = DictationDraftSyncConflict(local = left, remote = right),
        message = "remote dictation draft revision conflict",
    )
}

interface DictationDraftSyncPort {
    /** Configured account supplied by the composition root; blank is disabled. */
    val configuredAccountId: String get() = ""

    /** Pull returns a status so disabled, missing, and tombstone are explicit. */
    suspend fun pull(accountId: String): DictationDraftSyncResult

    suspend fun push(
        accountId: String,
        draft: DictationDraftSyncEnvelope,
        ifMatchRevision: String? = null,
    ): DictationDraftSyncResult

    /** Compatibility helpers for callers that only need a returned envelope. */
    suspend fun pullEnvelope(accountId: String): DictationDraftSyncEnvelope? = pull(accountId).envelope

    suspend fun pushEnvelope(
        accountId: String,
        draft: DictationDraftSyncEnvelope,
        ifMatchRevision: String? = null,
    ): DictationDraftSyncEnvelope = requireNotNull(push(accountId, draft, ifMatchRevision).envelope)
}

data class ExportedDictation(val bytes: ByteArray, val fileName: String, val mimeType: String)

interface TimeProvider {
    fun nowUtcSeconds(): Double
    fun localDate(epochSeconds: Double): LocalDate
}
