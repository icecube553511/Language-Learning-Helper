@file:OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)

package com.lexitrack.learning.domain

import kotlin.math.abs
import kotlin.math.max
import java.text.Normalizer
import java.util.Locale
import java.math.BigDecimal
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonUnquotedLiteral
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.ExperimentalSerializationApi

/** Versioned editor state for the dictation worksheet.  UI-only geometry is
 * deliberately excluded; IDs and logical scroll positions are portable. */
const val DICTATION_DRAFT_VERSION = 1
const val MAX_DICTATION_DRAFT_BYTES = 1_048_576

private fun canonicalUtcNumber(value: Double): String {
    val plain = BigDecimal.valueOf(value).toPlainString()
    return if (!plain.contains('.') && !plain.contains('e', ignoreCase = true)) "$plain.0" else plain
}

/** Metadata is persisted even when sync is disabled so both clients share
 * one canonical draft shape. Credentials are intentionally absent. */
@OptIn(ExperimentalSerializationApi::class)
data class DictationDraftSyncMetadata(
    val accountId: String = "",
    val revision: String = "0",
    val updatedAtUtc: Double = 0.0,
    val deleted: Boolean = false,
) {
    /** Return the wire-safe metadata representation without credentials. */
    fun normalized(): DictationDraftSyncMetadata = copy(
        accountId = accountId.trim(),
        revision = revision.trim().ifBlank { "0" },
        updatedAtUtc = updatedAtUtc.takeIf { it.isFinite() && it >= 0.0 } ?: 0.0,
    )

    fun canonicalJson(): String = CANONICAL_JSON.encodeToString(
        JsonElement.serializer(),
        normalized().toJsonObject(),
    )
}

/** Canonical identifier used for persisted group keys and cross-platform sync. */
fun normalizeDictationGroupKey(value: String?): String {
    val normalized = Normalizer.normalize(value?.trim().orEmpty(), Normalizer.Form.NFKC)
        .lowercase(Locale.ROOT)
    return normalized.filterNot { it in " -_." }.ifBlank { "all" }
}

data class DictationGroupDraft(
    val selectedIds: Set<String> = emptySet(),
    val anchorId: String? = null,
    val endpointId: String? = null,
    val scrollPosition: Float = 0f,
    val expanded: Boolean = false,
)

data class DictationDraft(
    val mode: String = "random",
    val scopeGroup: String = "all",
    val openGroup: String? = null,
    val count: Int = 10,
    val includeEvaluated: Boolean = false,
    val formats: Set<String> = setOf("DOCX", "PDF"),
    val fontSizePt: Int = 12,
    val missingFields: Set<String> = setOf("word"),
    val showInitial: Boolean = false,
    val includeExamples: Boolean = false,
    val includeExampleChinese: Boolean = false,
    val customExample: String = "",
    val selectedIds: Set<String> = emptySet(),
    val groups: Map<String, DictationGroupDraft> = emptyMap(),
    val rangeEnabled: Boolean = true,
    val syncMetadata: DictationDraftSyncMetadata = DictationDraftSyncMetadata(),
) {
    val version: Int get() = DICTATION_DRAFT_VERSION

    // Compatibility views for adapters that still expose the flattened names
    // used by the first draft prototype. The persisted contract remains the
    // nested `groups` object.
    val groupSelectedIds: Map<String, Set<String>>
        get() = groups.mapValues { it.value.selectedIds }
    val groupAnchors: Map<String, String?>
        get() = groups.mapValues { it.value.anchorId }
    val groupEndpoints: Map<String, String?>
        get() = groups.mapValues { it.value.endpointId }
    val groupScrollPositions: Map<String, Float>
        get() = groups.mapValues { it.value.scrollPosition }
    val expandedGroups: Set<String>
        get() = groups.filterValues { it.expanded }.keys

    /** Compact, deterministic JSON matching dictation-draft-v1. */
    fun canonicalJson(): String = CANONICAL_JSON.encodeToString(
        JsonElement.serializer(),
        canonicalPayload(),
    )

    fun canonicalJsonBytes(): ByteArray = canonicalJson().toByteArray(Charsets.UTF_8)

    fun byteSize(): Int = canonicalJsonBytes().size

    fun withinSizeLimit(limit: Int = MAX_DICTATION_DRAFT_BYTES): Boolean = byteSize() <= limit

    /** Alias used by sync adapters that speak in payload terminology. */
    fun canonicalPayload(): JsonObject {
        val canonicalGroups = normalizeDictationGroups(groups)
        val fields = linkedMapOf<String, JsonElement>()
        // Keep insertion order lexicographic; JsonObject preserves it and the
        // same order is emitted by both Android and Windows canonical codecs.
        fields["count"] = JsonPrimitive(count.coerceAtLeast(1))
        fields["customExample"] = JsonPrimitive(customExample)
        fields["formats"] = buildJsonArray {
            formats.map(String::uppercase).distinct().sorted().forEach { add(JsonPrimitive(it)) }
        }
        fields["fontSizePt"] = JsonPrimitive(fontSizePt.coerceIn(8, 24))
        fields["groups"] = JsonObject(linkedMapOf<String, JsonElement>().apply {
            canonicalGroups.toSortedMap().forEach { (key, group) ->
                put(key, group.toJsonObject())
            }
        })
        fields["includeEvaluated"] = JsonPrimitive(includeEvaluated)
        fields["includeExampleChinese"] = JsonPrimitive(includeExampleChinese)
        fields["includeExamples"] = JsonPrimitive(includeExamples)
        fields["missingFields"] = buildJsonArray {
            missingFields.map { it.toString() }.distinct().sorted().forEach { add(JsonPrimitive(it)) }
        }
        fields["mode"] = JsonPrimitive(if (mode == "manual") "manual" else "random")
        fields["openGroup"] = openGroup
            ?.let(::normalizeDictationGroupKey)
            ?.let(::JsonPrimitive)
            ?: JsonNull
        fields["rangeEnabled"] = JsonPrimitive(rangeEnabled)
        fields["scopeGroup"] = JsonPrimitive(normalizeDictationGroupKey(scopeGroup))
        fields["selectedIds"] = buildJsonArray {
            selectedIds.map(::normalizeWordId)
                .filter(String::isNotBlank)
                .distinct()
                .sorted()
                .forEach { add(JsonPrimitive(it)) }
        }
        fields["showInitial"] = JsonPrimitive(showInitial)
        fields["syncMetadata"] = syncMetadata.normalized().toJsonObject()
        fields["version"] = JsonPrimitive(DICTATION_DRAFT_VERSION)
        return JsonObject(fields.toSortedMap())
    }
}

private val CANONICAL_JSON = Json {
    prettyPrint = false
    encodeDefaults = true
    explicitNulls = true
}

fun decodeDictationDraftSyncMetadata(raw: String): DictationDraftSyncMetadata? = runCatching {
    val root = CANONICAL_JSON.parseToJsonElement(raw).jsonObject
    DictationDraftSyncMetadata(
        accountId = root["accountId"]?.jsonPrimitive?.contentOrNull.orEmpty(),
        revision = root["revision"]?.jsonPrimitive?.contentOrNull ?: "0",
        updatedAtUtc = root["updatedAtUtc"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0,
        deleted = root["deleted"]?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: false,
    ).normalized()
}.getOrNull()

private fun DictationDraftSyncMetadata.toJsonObject(): JsonObject = JsonObject(
    linkedMapOf(
        "accountId" to JsonPrimitive(normalized().accountId),
        "deleted" to JsonPrimitive(normalized().deleted),
        "revision" to JsonPrimitive(normalized().revision),
        // Keep numeric spelling identical to the Windows JSON codec.
        "updatedAtUtc" to JsonUnquotedLiteral(
            canonicalUtcNumber(normalized().updatedAtUtc),
        ),
    ),
)

private fun DictationGroupDraft.toJsonObject(): JsonObject = JsonObject(
    linkedMapOf(
        "anchorId" to (anchorId?.let(::normalizeWordId)?.takeIf(String::isNotBlank)?.let(::JsonPrimitive) ?: JsonNull),
        "endpointId" to (endpointId?.let(::normalizeWordId)?.takeIf(String::isNotBlank)?.let(::JsonPrimitive) ?: JsonNull),
        "expanded" to JsonPrimitive(expanded),
        "scrollPosition" to JsonPrimitive(scrollPosition.takeIf { it.isFinite() }?.coerceIn(0f, 1f) ?: 0f),
        "selectedIds" to buildJsonArray {
            selectedIds.map(::normalizeWordId)
                .filter(String::isNotBlank)
                .distinct()
                .sorted()
                .forEach { add(JsonPrimitive(it)) }
        },
    ),
)

/** Merge normalized group aliases without dropping any selected IDs. */
fun normalizeDictationGroups(
    source: Map<String, DictationGroupDraft>,
): Map<String, DictationGroupDraft> {
    val result = linkedMapOf<String, DictationGroupDraft>()
    source.toSortedMap().forEach { (rawKey, rawGroup) ->
        val key = normalizeDictationGroupKey(rawKey)
        val clean = rawGroup.copy(
            selectedIds = rawGroup.selectedIds.map(::normalizeWordId).filter(String::isNotBlank).toSet(),
            anchorId = rawGroup.anchorId?.let(::normalizeWordId)?.takeIf(String::isNotBlank),
            endpointId = rawGroup.endpointId?.let(::normalizeWordId)?.takeIf(String::isNotBlank),
            scrollPosition = rawGroup.scrollPosition.takeIf { it.isFinite() }?.coerceIn(0f, 1f) ?: 0f,
        )
        val previous = result[key]
        result[key] = if (previous == null) clean else previous.copy(
            selectedIds = previous.selectedIds + clean.selectedIds,
            // Later canonical aliases carry the most recent marker/position;
            // a non-null value from either alias is retained.
            anchorId = clean.anchorId ?: previous.anchorId,
            endpointId = clean.endpointId ?: previous.endpointId,
            scrollPosition = max(previous.scrollPosition, clean.scrollPosition),
            expanded = previous.expanded || clean.expanded,
        )
    }
    return result
        .mapValues { (_, group) ->
            if (group.anchorId == null) group.copy(endpointId = null) else group
        }
        .toSortedMap()
}

/** Decode canonical or early flattened draft JSON without platform state. */
fun decodeDictationDraft(raw: String): DictationDraft? = runCatching {
    val root = CANONICAL_JSON.parseToJsonElement(raw).jsonObject
    require(root["version"]?.jsonPrimitive?.content?.toIntOrNull() == DICTATION_DRAFT_VERSION)
    fun primitive(key: String): JsonPrimitive? = root[key]?.takeUnless { it is JsonNull }?.jsonPrimitive
    fun string(key: String, fallback: String = ""): String = primitive(key)?.content ?: fallback
    fun bool(key: String, fallback: Boolean = false): Boolean = primitive(key)?.content?.toBooleanStrictOrNull() ?: fallback
    fun strings(key: String): List<String> = root[key]?.takeUnless { it is JsonNull }
        ?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull } ?: emptyList()
    val nested = linkedMapOf<String, DictationGroupDraft>()
    root["groups"]?.takeUnless { it is JsonNull }?.jsonObject?.forEach { (key, element) ->
        val obj = element as? JsonObject ?: return@forEach
        nested[key] = DictationGroupDraft(
            selectedIds = stringsFrom(obj, "selectedIds"),
            anchorId = stringFrom(obj, "anchorId"),
            endpointId = stringFrom(obj, "endpointId"),
            scrollPosition = numberFrom(obj, "scrollPosition")?.toFloat() ?: 0f,
            expanded = boolFrom(obj, "expanded"),
        )
    }
    // Migrate the first prototype's flattened maps and merge them with any
    // nested values already present in the same payload.
    val legacySelected = root["groupSelectedIds"]?.jsonObject.orEmpty()
    val legacyAnchors = root["groupAnchors"]?.jsonObject.orEmpty()
    val legacyEndpoints = root["groupEndpoints"]?.jsonObject.orEmpty()
    val legacyScroll = root["groupScrollPositions"]?.jsonObject.orEmpty()
    val legacyExpanded = strings("expandedGroups").toSet()
    val legacyKeys = legacySelected.keys + legacyAnchors.keys + legacyEndpoints.keys + legacyScroll.keys + legacyExpanded
    legacyKeys.forEach { key ->
        val existing = nested[key] ?: DictationGroupDraft()
        nested[key] = existing.copy(
            selectedIds = existing.selectedIds + (legacySelected[key]?.let(::stringsFromElement).orEmpty()),
            anchorId = existing.anchorId ?: stringFromElement(legacyAnchors[key]),
            endpointId = existing.endpointId ?: stringFromElement(legacyEndpoints[key]),
            scrollPosition = max(existing.scrollPosition, numberFromElement(legacyScroll[key])?.toFloat() ?: 0f),
            expanded = existing.expanded || normalizeDictationGroupKey(key) in legacyExpanded.map(::normalizeDictationGroupKey),
        )
    }
    val metadataObject = root["syncMetadata"]?.takeUnless { it is JsonNull }?.jsonObject
    val metadata = DictationDraftSyncMetadata(
        accountId = rawStringFromElement(metadataObject?.get("accountId") ?: root["accountId"], ""),
        revision = rawStringFromElement(metadataObject?.get("revision") ?: root["revision"], "0").ifBlank { "0" },
        updatedAtUtc = numberFromElement(metadataObject?.get("updatedAtUtc") ?: root["updatedAtUtc"]) ?: 0.0,
        deleted = boolFromElement(metadataObject?.get("deleted") ?: root["deleted"]),
    ).normalized()
    DictationDraft(
        mode = if (string("mode") == "manual") "manual" else "random",
        scopeGroup = normalizeDictationGroupKey(string("scopeGroup", "all")),
        openGroup = root["openGroup"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content?.let(::normalizeDictationGroupKey),
        count = string("count", "10").toIntOrNull()?.coerceAtLeast(1) ?: 10,
        includeEvaluated = bool("includeEvaluated"),
        formats = strings("formats").map(String::uppercase).toSet().ifEmpty { setOf("DOCX", "PDF") },
        fontSizePt = string("fontSizePt", "12").toIntOrNull()?.coerceIn(8, 24) ?: 12,
        missingFields = strings("missingFields").toSet().ifEmpty { setOf("word") },
        showInitial = bool("showInitial"),
        includeExamples = bool("includeExamples"),
        includeExampleChinese = bool("includeExampleChinese"),
        customExample = string("customExample"),
        selectedIds = strings("selectedIds").map(::normalizeWordId).filter(String::isNotBlank).toSet(),
        groups = normalizeDictationGroups(nested),
        rangeEnabled = bool("rangeEnabled", true),
        syncMetadata = metadata,
    )
}.getOrNull()

private fun stringsFrom(obj: JsonObject, key: String): Set<String> = obj[key]
    ?.takeUnless { it is JsonNull }
    ?.jsonArray
    ?.mapNotNull { it.jsonPrimitive.contentOrNull }
    ?.map(::normalizeWordId)
    ?.filter(String::isNotBlank)
    ?.toSet()
    .orEmpty()

private fun stringFrom(obj: JsonObject, key: String): String? = stringFromElement(obj[key])
private fun stringFromElement(element: JsonElement?, fallback: String? = null): String? =
    element?.takeUnless { it is JsonNull }?.jsonPrimitive?.contentOrNull?.let(::normalizeWordId) ?: fallback
private fun rawStringFromElement(element: JsonElement?, fallback: String = ""): String =
    element?.takeUnless { it is JsonNull }?.jsonPrimitive?.contentOrNull ?: fallback
private fun stringsFromElement(element: JsonElement?): Set<String> = element
    ?.takeUnless { it is JsonNull }
    ?.jsonArray
    ?.mapNotNull { it.jsonPrimitive.contentOrNull }
    ?.map(::normalizeWordId)
    ?.filter(String::isNotBlank)
    ?.toSet()
    .orEmpty()
private fun numberFrom(obj: JsonObject, key: String): Double? = numberFromElement(obj[key])
private fun numberFromElement(element: JsonElement?): Double? = element
    ?.takeUnless { it is JsonNull }
    ?.jsonPrimitive?.content?.toDoubleOrNull()
    ?.takeIf { it.isFinite() }
private fun boolFrom(obj: JsonObject, key: String): Boolean = boolFromElement(obj[key])
private fun boolFromElement(element: JsonElement?): Boolean = element
    ?.takeUnless { it is JsonNull }
    ?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: false

/** Stable order shared by random subset and range selection. */
fun dictationOrderedIds(entries: Iterable<VocabularyEntry>): List<String> =
    entries.map { normalizeWordId(it.id) }
        .filter(String::isNotBlank)
        .distinct()
        .sorted()

/** Inclusive range in canonical ID order; invalid IDs produce an empty set. */
fun dictationRangeIds(
    entries: Iterable<VocabularyEntry>,
    anchorId: String?,
    endpointId: String?,
): Set<String> {
    if (anchorId.isNullOrBlank() || endpointId.isNullOrBlank()) return emptySet()
    val ordered = dictationOrderedIds(entries)
    val start = ordered.indexOf(normalizeWordId(anchorId))
    val end = ordered.indexOf(normalizeWordId(endpointId))
    if (start < 0 || end < 0) return emptySet()
    val low = minOf(start, end)
    val high = maxOf(start, end)
    return ordered.subList(low, high + 1).toSet()
}

/** Nearest selected ID by canonical list distance; ties prefer earlier ID. */
fun nearestDictationId(
    entries: Iterable<VocabularyEntry>,
    referenceId: String?,
    selectedIds: Collection<String>,
): String? {
    if (referenceId.isNullOrBlank()) return null
    val ordered = dictationOrderedIds(entries)
    val reference = ordered.indexOf(normalizeWordId(referenceId))
    if (reference < 0) return null
    val selected = selectedIds.map(::normalizeWordId).toSet()
    return ordered.withIndex()
        .filter { it.value in selected }
        .minWithOrNull(compareBy<IndexedValue<String>> { abs(it.index - reference) }.thenBy { it.index })
        ?.value
}

/** Select up to [count] unique entries from an explicit candidate subset. */
fun randomDictationSubset(
    entries: Iterable<VocabularyEntry>,
    candidateIds: Collection<String>?,
    count: Int,
    randomUnit: () -> Double,
): List<VocabularyEntry> {
    require(count >= 0) { "默写词数不能为负数" }
    val wanted = candidateIds?.map(::normalizeWordId)?.toSet()
    val pool = entries.filter { wanted == null || normalizeWordId(it.id) in wanted }
        .distinctBy { normalizeWordId(it.id) }
        .sortedBy { normalizeWordId(it.id) }
        .toMutableList()
    val result = ArrayList<VocabularyEntry>(minOf(count, pool.size))
    repeat(minOf(count, pool.size)) {
        val unit = randomUnit().coerceIn(0.0, 0.9999999999999999)
        result += pool.removeAt((unit * pool.size).toInt())
    }
    return result
}

/**
 * Reconcile a persisted draft with the current catalog. Unknown IDs are
 * removed, while selected IDs survive membership changes. Range markers are
 * valid only when both IDs still occur in their saved group's current list.
 */
fun sanitizeDictationDraft(
    draft: DictationDraft,
    entries: Iterable<VocabularyEntry>,
): DictationDraft {
    val catalog = entries.toList()
    val known = catalog.mapTo(mutableSetOf()) { normalizeWordId(it.id) }
    // Normalize and merge aliases before validating against the current
    // catalog.  This prevents a later `CET-4` entry from erasing selections
    // stored under `cet4`.
    val cleanGroups = normalizeDictationGroups(draft.groups).mapValues { (key, group) ->
        val groupEntries = when {
            key == "all" -> catalog
            key in GROUP_ORDER -> catalog.filter { key in classifyGroups(it.levels, it.tags) }
            else -> {
                val code = normalizeGroupMembership(key)
                catalog.filter { entry -> entry.levels.any { normalizeGroupMembership(it) == code } }
            }
        }
        val groupIds = groupEntries.mapTo(mutableSetOf()) { normalizeWordId(it.id) }
        group.copy(
            selectedIds = group.selectedIds.map(::normalizeWordId).filter { it in known }.toSet(),
            anchorId = group.anchorId?.let(::normalizeWordId)?.takeIf { it in groupIds },
            endpointId = group.endpointId?.let(::normalizeWordId)?.takeIf { it in groupIds },
            scrollPosition = group.scrollPosition.coerceIn(0f, 1f),
        ).let { cleaned ->
            if (cleaned.anchorId == null) cleaned.copy(endpointId = null) else cleaned
        }
    }
    val global = (draft.selectedIds.map(::normalizeWordId) + cleanGroups.values.flatMap { it.selectedIds })
        .filter { it in known }
        .toSet()
    return draft.copy(
        selectedIds = global,
        groups = cleanGroups,
        scopeGroup = normalizeDictationGroupKey(draft.scopeGroup),
        openGroup = draft.openGroup?.let(::normalizeDictationGroupKey),
        count = draft.count.coerceAtLeast(1),
        fontSizePt = draft.fontSizePt.coerceIn(8, 24),
        syncMetadata = draft.syncMetadata.normalized(),
    )
}
