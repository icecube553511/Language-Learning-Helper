package com.lexitrack.learning.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.doubleOrNull

class DictationDraftTest {
    private fun entry(id: String) = VocabularyEntry(
        id = id,
        word = id,
        meaning = "n. $id",
        examples = listOf(
            BilingualExample("$id one", "一"),
            BilingualExample("$id two", "二"),
            BilingualExample("$id three", "三"),
        ),
    )

    @Test
    fun `range is inclusive and stable in both directions`() {
        val entries = listOf(entry("Canada"), entry("apple"), entry("banana"), entry("dear"))
        assertEquals(setOf("apple", "banana"), dictationRangeIds(entries, "banana", "APPLE"))
    }

    @Test
    fun `nearest selection prefers earlier id on ties`() {
        val entries = listOf(entry("a"), entry("b"), entry("c"), entry("d"))
        assertEquals("b", nearestDictationId(entries, "c", listOf("b", "d")))
    }

    @Test
    fun `explicit random subset is without replacement and bounded`() {
        val entries = listOf(entry("a"), entry("b"), entry("c"), entry("d"))
        val selected = randomDictationSubset(entries, setOf("a", "c", "d"), 2) { 0.0 }
        assertEquals(listOf("a", "c"), selected.map { it.id })
        assertTrue(randomDictationSubset(entries, emptySet(), 3) { 0.0 }.isEmpty())
    }

    @Test
    fun `draft carries nested groups and version`() {
        val draft = DictationDraft(
            mode = "random",
            selectedIds = setOf("apple"),
            groups = mapOf("cet4" to DictationGroupDraft(setOf("apple"), "apple", "banana", 2f, true)),
        )
        assertEquals(1, draft.version)
        assertEquals("banana", draft.groups.getValue("cet4").endpointId)
    }

    @Test
    fun `sanitize drops unknown ids and invalid range markers`() {
        val draft = DictationDraft(
            selectedIds = setOf("apple", "gone"),
            groups = mapOf("cet4" to DictationGroupDraft(setOf("apple", "gone"), "gone", "apple", 4f, false)),
        )
        val clean = sanitizeDictationDraft(draft, listOf(entry("apple")))
        assertEquals(setOf("apple"), clean.selectedIds)
        assertEquals(null, clean.groups.getValue("cet4").anchorId)
        assertEquals(null, clean.groups.getValue("cet4").endpointId)
        assertEquals(1f, clean.groups.getValue("cet4").scrollPosition)
    }

    @Test
    fun `sanitize canonicalizes group keys and keeps valid markers`() {
        val draft = DictationDraft(
            scopeGroup = " CET-4 ",
            openGroup = "CET_4",
            groups = mapOf(
                "CET-4" to DictationGroupDraft(
                    selectedIds = setOf(" APPLE "),
                    anchorId = "APPLE",
                    endpointId = "APPLE",
                ),
            ),
        )
        val clean = sanitizeDictationDraft(draft, listOf(entry("apple").copy(levels = setOf("CET4"))))
        assertEquals("cet4", clean.scopeGroup)
        assertEquals("cet4", clean.openGroup)
        assertEquals(setOf("cet4"), clean.groups.keys)
        assertEquals("apple", clean.groups.getValue("cet4").anchorId)
        assertEquals("apple", clean.groups.getValue("cet4").endpointId)
    }

    @Test
    fun `sanitize merges normalized group aliases before catalog validation`() {
        val draft = DictationDraft(
            groups = linkedMapOf(
                "cet4" to DictationGroupDraft(
                    selectedIds = setOf("apple"),
                    anchorId = "apple",
                    scrollPosition = 0.2f,
                ),
                "CET-4" to DictationGroupDraft(
                    selectedIds = setOf("banana"),
                    endpointId = "banana",
                    scrollPosition = 0.8f,
                    expanded = true,
                ),
            ),
        )
        val clean = sanitizeDictationDraft(
            draft,
            listOf(
                entry("apple").copy(levels = setOf("CET4")),
                entry("banana").copy(levels = setOf("CET4")),
            ),
        )
        val group = clean.groups.getValue("cet4")
        assertEquals(setOf("apple", "banana"), group.selectedIds)
        assertEquals("apple", group.anchorId)
        assertEquals("banana", group.endpointId)
        assertEquals(0.8f, group.scrollPosition)
        assertTrue(group.expanded)
    }

    @Test
    fun `normalizing metadata removes invalid timestamp and blank revision`() {
        val clean = sanitizeDictationDraft(
            DictationDraft(
                syncMetadata = DictationDraftSyncMetadata(
                    accountId = " account ",
                    revision = "   ",
                    updatedAtUtc = Double.NaN,
                    deleted = true,
                ),
            ),
            emptyList(),
        )
        assertEquals("account", clean.syncMetadata.accountId)
        assertEquals("0", clean.syncMetadata.revision)
        assertEquals(0.0, clean.syncMetadata.updatedAtUtc)
        assertTrue(clean.syncMetadata.deleted)
    }

    @Test
    fun `canonical json emits fixed null fields and sync metadata`() {
        val draft = DictationDraft(
            openGroup = null,
            groups = mapOf("CET-4" to DictationGroupDraft(anchorId = null, endpointId = null)),
            syncMetadata = DictationDraftSyncMetadata(
                accountId = " user-1 ",
                revision = " 42 ",
                updatedAtUtc = 1_730_000_000.0,
            ),
        )
        val root = Json.parseToJsonElement(draft.canonicalJson()).jsonObject
        assertEquals(JsonNull, root["openGroup"])
        assertEquals(JsonNull, root["groups"]!!.jsonObject.getValue("cet4").jsonObject["anchorId"])
        assertEquals(JsonNull, root["groups"]!!.jsonObject.getValue("cet4").jsonObject["endpointId"])
        val metadata = root.getValue("syncMetadata").jsonObject
        assertEquals("user-1", metadata.getValue("accountId").jsonPrimitive.content)
        assertEquals("42", metadata.getValue("revision").jsonPrimitive.content)
        assertEquals(1730000000.0, metadata.getValue("updatedAtUtc").jsonPrimitive.doubleOrNull)
        assertFalse(draft.canonicalJson().contains("token"))
        assertEquals(draft.canonicalJsonBytes().size, draft.byteSize())
        assertTrue(draft.withinSizeLimit())
    }

    @Test
    fun `legacy flattened payload migrates and merges normalized group aliases`() {
        val raw = """
            {
              "version": 1,
              "mode": "manual",
              "scopeGroup": "CET-4",
              "openGroup": null,
              "count": 3,
              "selectedIds": [" Apple "],
              "groupSelectedIds": {"CET-4": ["BANANA"], "cet4": [" apple "]},
              "groupAnchors": {"CET-4": " BANANA "},
              "groupEndpoints": {"cet4": null},
              "groupScrollPositions": {"CET-4": 2.0},
              "expandedGroups": ["CET-4"],
              "rangeEnabled": true
            }
        """.trimIndent()
        val draft = decodeDictationDraft(raw) ?: error("legacy payload rejected")
        val group = draft.groups.getValue("cet4")
        assertEquals("cet4", draft.scopeGroup)
        assertEquals(setOf("apple", "banana"), group.selectedIds)
        assertEquals("banana", group.anchorId)
        assertEquals(null, group.endpointId)
        assertEquals(1f, group.scrollPosition)
        assertTrue(group.expanded)
        assertEquals(setOf("apple"), draft.selectedIds)
    }

    @Test
    fun `canonical payload round trips sync metadata`() {
        val draft = DictationDraft(
            selectedIds = setOf(" Apple "),
            groups = mapOf("CET-4" to DictationGroupDraft(setOf("BANANA"), "APPLE", "BANANA", 0.25f, true)),
            syncMetadata = DictationDraftSyncMetadata("account", "opaque", 12.5, false),
        )
        val restored = decodeDictationDraft(draft.canonicalJson()) ?: error("canonical payload rejected")
        assertEquals(draft.syncMetadata.normalized(), restored.syncMetadata)
        assertEquals(setOf("apple"), restored.selectedIds)
        assertEquals(setOf("banana"), restored.groups.getValue("cet4").selectedIds)
    }
}
