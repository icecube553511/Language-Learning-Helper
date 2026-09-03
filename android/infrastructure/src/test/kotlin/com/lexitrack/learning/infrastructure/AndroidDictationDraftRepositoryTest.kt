package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationDraftSyncMetadata
import com.lexitrack.learning.domain.DictationGroupDraft
import com.lexitrack.learning.application.makeDictationDraftSyncEnvelope
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@RunWith(RobolectricTestRunner::class)
class AndroidDictationDraftRepositoryTest {
    private lateinit var context: Context

    private class XorCipher : DraftCipher {
        override fun encrypt(plaintext: ByteArray): ByteArray =
            plaintext.map { (it.toInt() xor 0x5A).toByte() }.toByteArray()

        override fun decrypt(ciphertext: ByteArray): ByteArray = encrypt(ciphertext)
    }

    private fun repository() = AndroidDictationDraftRepository(context, XorCipher())

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun `nested draft survives restart and clear`() {
        val draft = DictationDraft(
            mode = "random",
            scopeGroup = "cet4",
            selectedIds = setOf("apple", "banana"),
            groups = mapOf("cet4" to DictationGroupDraft(setOf("apple"), "apple", "banana", 0.5f, true)),
        )
        repository().save(draft)
        val loaded = repository().get()
        assertEquals(draft, loaded)
        repository().clear()
        assertNull(repository().get())
    }

    @Test
    fun `sync metadata survives draft clear and repository restart`() {
        val metadata = DictationDraftSyncMetadata(
            accountId = "user-1",
            revision = "opaque-9",
            updatedAtUtc = 9.0,
            deleted = true,
        )
        val first = repository()
        first.save(DictationDraft(syncMetadata = metadata.copy(deleted = false)))
        first.clear()
        first.saveSyncMetadata(metadata)

        val restarted = repository()
        assertNull(restarted.get())
        assertEquals(metadata, restarted.getSyncMetadata())
        val raw = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .getString("sync_metadata_v1", null).orEmpty()
        assertFalse(raw.contains("user-1"))
        assertFalse(raw.contains("opaque-9"))
    }

    @Test
    fun `synced snapshot and three conflict backups are encrypted and bounded`() {
        val repository = repository()
        val synced = makeDictationDraftSyncEnvelope(
            accountId = "user-1",
            draft = DictationDraft(customExample = "last-synced-secret"),
            revision = "synced-7",
            updatedAtUtc = 7.0,
        )
        repository.saveLastSyncedEnvelope(synced)
        repeat(5) { revision ->
            repository.addConflictBackup(makeDictationDraftSyncEnvelope(
                accountId = "user-1",
                draft = DictationDraft(customExample = "conflict-secret-$revision"),
                revision = revision.toString(),
                updatedAtUtc = revision.toDouble(),
            ))
        }
        repository.addConflictBackup(makeDictationDraftSyncEnvelope(
            accountId = "user-1",
            draft = DictationDraft(customExample = "conflict-secret-4"),
            revision = "4",
            updatedAtUtc = 4.0,
        ))

        val restarted = repository()
        assertEquals(synced.canonicalJson(), restarted.getLastSyncedEnvelope()?.canonicalJson())
        assertEquals(listOf("4", "3", "2"), restarted.getConflictBackups().map { it.revision })
        val preferences = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
        assertFalse(preferences.getString("last_synced_envelope_v1", "").orEmpty().contains("last-synced-secret"))
        assertFalse(preferences.getString("conflict_backups_v1", "").orEmpty().contains("conflict-secret"))
    }

    @Test
    fun `codec preserves complete export configuration`() {
        val draft = DictationDraft(
            count = 3,
            formats = setOf("PDF"),
            fontSizePt = 18,
            missingFields = setOf("word", "partOfSpeech", "meaning"),
            showInitial = true,
            includeExamples = true,
            includeExampleChinese = true,
            customExample = "Use this.",
        )
        val repository = repository()
        repository.save(draft)
        assertEquals(draft, repository.get())
    }

    @Test
    fun `codec normalizes ids and clamps scroll and orphan endpoint`() {
        val draft = DictationDraft(
            selectedIds = setOf(" Apple "),
            groups = mapOf(
                "cet4" to DictationGroupDraft(
                    selectedIds = setOf(" BANANA "),
                    anchorId = " Apple ",
                    endpointId = " Banana ",
                    scrollPosition = 4f,
                ),
            ),
        )
        val repository = repository()
        repository.save(draft)
        val loaded = repository.get() ?: error("draft missing")
        assertEquals(setOf("apple"), loaded.selectedIds)
        val group = loaded.groups.getValue("cet4")
        assertEquals(setOf("banana"), group.selectedIds)
        assertEquals("apple", group.anchorId)
        assertEquals("banana", group.endpointId)
        assertEquals(1f, group.scrollPosition)
    }

    @Test
    fun `repository reads legacy flattened payload and writes canonical metadata`() {
        val raw = """
            {
              "version": 1,
              "mode": "manual",
              "scopeGroup": "CET-4",
              "openGroup": null,
              "count": 2,
              "selectedIds": ["APPLE"],
              "groupSelectedIds": {"CET-4": ["BANANA"]},
              "groupAnchors": {"CET-4": "BANANA"},
              "groupEndpoints": {"CET-4": null},
              "groupScrollPositions": {"CET-4": 0.4},
              "expandedGroups": ["CET-4"],
              "rangeEnabled": true
            }
        """.trimIndent()
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .edit().putString("draft_v1", raw).commit()
        val repository = repository()
        val loaded = repository.get() ?: error("legacy draft missing")
        assertEquals(setOf("apple"), loaded.selectedIds)
        assertEquals(setOf("banana"), loaded.groups.getValue("cet4").selectedIds)
        repository.save(loaded)
        val canonical = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .getString("draft_v1", null) ?: error("canonical draft missing")
        val root = Json.parseToJsonElement(canonical).jsonObject
        assertEquals("keystore-aes-gcm-v1", root.getValue("format").jsonPrimitive.content)
        assertEquals("0", loaded.syncMetadata.revision)
        assertEquals(JsonNull, Json.parseToJsonElement(loaded.canonicalJson()).jsonObject["openGroup"])
    }

    @Test
    fun `new snapshot is encrypted and plaintext never reaches preferences`() {
        val draft = DictationDraft(
            customExample = "secret-draft-marker",
            selectedIds = setOf("token-word-id"),
        )
        repository().save(draft)
        val raw = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .getString("draft_v1", null) ?: error("snapshot missing")
        assertFalse(raw.contains("secret-draft-marker"))
        assertFalse(raw.contains("token-word-id"))
        val root = Json.parseToJsonElement(raw).jsonObject
        assertEquals("keystore-aes-gcm-v1", root.getValue("format").jsonPrimitive.content)
        assertTrue(root.getValue("ciphertext").jsonPrimitive.content.isNotBlank())
    }

    @Test
    fun `legacy plaintext migrates once and remains readable`() {
        val draft = DictationDraft(customExample = "legacy-secret-marker")
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .edit().putString("draft_v1", draft.canonicalJson()).commit()
        val loaded = repository().get()
        assertEquals(draft, loaded)
        val migrated = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .getString("draft_v1", null) ?: error("migrated snapshot missing")
        assertFalse(migrated.contains("legacy-secret-marker"))
        assertEquals("keystore-aes-gcm-v1", Json.parseToJsonElement(migrated).jsonObject
            .getValue("format").jsonPrimitive.content)
    }

    @Test
    fun `corrupt encrypted snapshot is ignored`() {
        val raw = "{\"format\":\"keystore-aes-gcm-v1\",\"ciphertext\":\"not-valid\"}"
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .edit().putString("draft_v1", raw).commit()
        assertNull(repository().get())
    }

    @Test
    fun `malformed encrypted wrapper never falls through to plaintext decoder`() {
        val raw = "{\"format\":[],\"ciphertext\":\"not-valid\",\"version\":1}"
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .edit().putString("draft_v1", raw).commit()
        assertNull(repository().get())
    }

    @Test
    fun `migration failure returns legacy value without retaining plaintext`() {
        val draft = DictationDraft(customExample = "legacy-keystore-unavailable")
        context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .edit().putString("draft_v1", draft.canonicalJson()).commit()
        val failingCipher = object : DictationDraftCipher {
            override fun encrypt(plaintext: ByteArray): ByteArray = error("keystore unavailable")
            override fun decrypt(ciphertext: ByteArray): ByteArray = error("keystore unavailable")
        }
        val repository = AndroidDictationDraftRepository(context, failingCipher)
        assertEquals(draft, repository.get())
        val raw = context.getSharedPreferences("lexitrack_dictation_draft", Context.MODE_PRIVATE)
            .getString("draft_v1", null)
        assertNull(raw)
        // A second repository instance must not recover the process-local
        // fallback; the old plaintext has been deliberately discarded.
        assertNull(AndroidDictationDraftRepository(context, failingCipher).get())
    }
}
