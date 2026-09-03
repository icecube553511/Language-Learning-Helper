package com.lexitrack.learning.infrastructure

import android.content.Context
import android.util.Base64
import com.lexitrack.learning.application.DictationDraftRepository
import com.lexitrack.learning.application.DictationDraftSyncEnvelope
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationDraftSyncMetadata
import com.lexitrack.learning.domain.decodeDictationDraft
import com.lexitrack.learning.domain.decodeDictationDraftSyncMetadata
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** SharedPreferences adapter for the encrypted dictation-draft-v1 payload. */
class AndroidDictationDraftRepository(
    context: Context,
    cipher: DraftCipher? = null,
    draftCipher: DraftCipher? = null,
) : DictationDraftRepository {
    private val storageCipher: DraftCipher = run {
        require(cipher == null || draftCipher == null) { "pass either cipher or draftCipher" }
        cipher ?: draftCipher ?: AndroidKeystoreDictationDraftCipher()
    }

    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    // A legacy snapshot can be returned once when Keystore migration fails,
    // but it is never retained in SharedPreferences.  This process-local
    // value avoids writing plaintext back while still allowing the current
    // editor session to finish or ask the user to save/clear it.
    private var ephemeralLegacyDraft: DictationDraft? = null

    override fun get(): DictationDraft? {
        ephemeralLegacyDraft?.let { return it }
        val raw = preferences.getString(KEY_DRAFT, null) ?: return null
        // Once the encrypted envelope marker is present, never fall back to
        // interpreting that same object as legacy plaintext.  This keeps a
        // tampered/corrupt ciphertext fail-closed even if an attacker adds
        // coincidental draft-looking fields to the wrapper.
        val parsed = parseObject(raw)
        val format = parsed?.get("format")?.let {
            runCatching { it.jsonPrimitive.contentOrNull }.getOrNull()
        }
        if (parsed?.containsKey("format") == true) {
            if (format != ENCRYPTED_FORMAT) return null
            return decodeEncrypted(parsed)
        }
        // Read one legacy plaintext snapshot so upgrades do not lose the
        // editor state.  Re-save immediately through the cipher.  If secure
        // storage is unavailable, remove the plaintext and keep it only for
        // this process; a later restart must not recover an unencrypted copy.
        val legacy = decodeDictationDraft(raw) ?: return null
        val migrated = runCatching { save(legacy) }.isSuccess
        if (!migrated) {
            ephemeralLegacyDraft = legacy
            // Best effort removal; commit gives the migration a deterministic
            // boundary before returning to presentation.
            preferences.edit().remove(KEY_DRAFT).commit()
        }
        return legacy
    }

    override fun save(draft: DictationDraft) {
        val payload = encryptPayload(draft.canonicalJson())
        val metadataPayload = runCatching {
            encryptPayload(draft.syncMetadata.canonicalJson())
        }.getOrNull()
        // commit() gives the explicit Save action durable semantics before a
        // lifecycle transition (and still writes only the encrypted wrapper).
        val editor = preferences.edit().putString(KEY_DRAFT, payload)
        if (metadataPayload != null) editor.putString(KEY_SYNC_METADATA, metadataPayload)
        check(editor.commit()) {
            "无法保存默写草稿"
        }
        ephemeralLegacyDraft = null
    }

    override fun clear() {
        check(preferences.edit().remove(KEY_DRAFT).commit()) {
            "无法清除默写草稿"
        }
        ephemeralLegacyDraft = null
    }

    override fun getSyncMetadata(): DictationDraftSyncMetadata? {
        val raw = preferences.getString(KEY_SYNC_METADATA, null) ?: return null
        val parsed = parseObject(raw) ?: return null
        if (parsed["format"]?.jsonPrimitive?.contentOrNull != ENCRYPTED_FORMAT) return null
        val plaintext = decryptPayload(parsed) ?: return null
        return decodeDictationDraftSyncMetadata(plaintext.toString(Charsets.UTF_8))
    }

    override fun saveSyncMetadata(metadata: DictationDraftSyncMetadata) {
        val payload = encryptPayload(metadata.normalized().canonicalJson())
        check(preferences.edit().putString(KEY_SYNC_METADATA, payload).commit()) {
            "无法保存默写同步元数据"
        }
    }

    override fun getLastSyncedEnvelope(): DictationDraftSyncEnvelope? {
        val raw = preferences.getString(KEY_LAST_SYNCED, null) ?: return null
        val parsed = parseObject(raw) ?: return null
        if (parsed["format"]?.jsonPrimitive?.contentOrNull != ENCRYPTED_FORMAT) return null
        val plaintext = decryptPayload(parsed) ?: return null
        return DictationDraftSyncEnvelope.fromJson(plaintext.toString(Charsets.UTF_8))
    }

    override fun saveLastSyncedEnvelope(envelope: DictationDraftSyncEnvelope) {
        val payload = encryptPayload(envelope.normalized().canonicalJson())
        check(preferences.edit().putString(KEY_LAST_SYNCED, payload).commit()) {
            "无法保存上次默写同步快照"
        }
    }

    override fun getConflictBackups(): List<DictationDraftSyncEnvelope> {
        val raw = preferences.getString(KEY_CONFLICT_BACKUPS, null) ?: return emptyList()
        val parsed = parseObject(raw) ?: return emptyList()
        if (parsed["format"]?.jsonPrimitive?.contentOrNull != ENCRYPTED_FORMAT) return emptyList()
        val plaintext = decryptPayload(parsed) ?: return emptyList()
        val elements = runCatching {
            Json.parseToJsonElement(plaintext.toString(Charsets.UTF_8)) as? JsonArray
        }.getOrNull() ?: return emptyList()
        return elements.take(MAX_CONFLICT_BACKUPS).mapNotNull { element ->
            DictationDraftSyncEnvelope.fromJson(element.toString())
        }
    }

    override fun addConflictBackup(envelope: DictationDraftSyncEnvelope) {
        val normalized = envelope.normalized()
        val canonical = normalized.canonicalJson()
        val retained = buildList {
            add(normalized)
            addAll(getConflictBackups().filter { it.canonicalJson() != canonical })
        }.take(MAX_CONFLICT_BACKUPS)
        val array = JsonArray(retained.map { Json.parseToJsonElement(it.canonicalJson()) })
        val payload = encryptPayload(array.toString())
        check(preferences.edit().putString(KEY_CONFLICT_BACKUPS, payload).commit()) {
            "无法保存默写冲突备份"
        }
    }

    private fun decodeEncrypted(payload: JsonObject): DictationDraft? {
        val plaintext = decryptPayload(payload) ?: return null
        return decodeDictationDraft(plaintext.toString(Charsets.UTF_8))
    }

    private fun encryptPayload(raw: String): String {
        val ciphertext = storageCipher.encrypt(raw.toByteArray(Charsets.UTF_8))
        require(ciphertext.isNotEmpty()) { "dictation draft cipher returned empty data" }
        return buildJsonObject {
            put("format", ENCRYPTED_FORMAT)
            put("ciphertext", Base64.encodeToString(ciphertext, Base64.NO_WRAP))
        }.toString()
    }

    private fun decryptPayload(payload: JsonObject): ByteArray? {
        val encoded = payload["ciphertext"]?.let {
            runCatching { it.jsonPrimitive.contentOrNull }.getOrNull()
        } ?: return null
        if (!isCanonicalBase64(encoded)) return null
        return runCatching {
            val ciphertext = Base64.decode(encoded, Base64.NO_WRAP)
            if (ciphertext.isEmpty()) return@runCatching null
            storageCipher.decrypt(ciphertext)
        }.getOrNull()
    }

    private fun parseObject(raw: String): JsonObject? =
        runCatching { Json.parseToJsonElement(raw) as? JsonObject }.getOrNull()

    private companion object {
        const val PREFERENCES_NAME = "lexitrack_dictation_draft"
        const val KEY_DRAFT = "draft_v1"
        const val KEY_SYNC_METADATA = "sync_metadata_v1"
        const val KEY_LAST_SYNCED = "last_synced_envelope_v1"
        const val KEY_CONFLICT_BACKUPS = "conflict_backups_v1"
        const val ENCRYPTED_FORMAT = "keystore-aes-gcm-v1"
        const val MAX_CONFLICT_BACKUPS = 3

        // Android's Base64 decoder is intentionally permissive.  Validate
        // the persisted alphabet/length first so malformed blobs fail closed
        // instead of being silently normalized into a different ciphertext.
        fun isCanonicalBase64(value: String): Boolean {
            if (value.isEmpty() || value.length % 4 != 0) return false
            if (!Regex("^[A-Za-z0-9+/]*={0,2}$").matches(value)) return false
            val padding = value.indexOf('=')
            return padding < 0 || padding >= value.length - 2
        }
    }
}
