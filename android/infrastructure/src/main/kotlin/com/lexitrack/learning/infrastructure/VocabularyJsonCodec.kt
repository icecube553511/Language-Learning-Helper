package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.normalizeWordId
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class CatalogDecodeResult(
    val entries: List<VocabularyEntry>,
    val rejected: Int,
)

object VocabularyJsonCodec {
    private val json = Json { ignoreUnknownKeys = true }

    fun decodeCatalog(text: String, defaultSource: String = "catalog"): CatalogDecodeResult {
        val root = json.parseToJsonElement(text)
        val items = when (root) {
            is JsonArray -> root
            is JsonObject -> {
                (root["entries"] ?: root["words"] ?: root["catalog"] ?: JsonArray(emptyList())).jsonArray
            }
            else -> JsonArray(emptyList())
        }
        val accepted = LinkedHashMap<String, VocabularyEntry>()
        var rejected = 0
        items.forEach { item ->
            val decoded = runCatching { decodeEntry(item.jsonObject, defaultSource) }.getOrNull()
            if (decoded == null || accepted.containsKey(decoded.id)) {
                rejected += 1
            } else {
                accepted[decoded.id] = decoded
            }
        }
        return CatalogDecodeResult(accepted.values.toList(), rejected)
    }

    fun encodeEntries(entries: List<VocabularyEntry>): String = buildJsonArray {
        entries.forEach { entry ->
            add(buildJsonObject {
                put("id", entry.id)
                put("word", entry.word)
                put("phonetic", entry.phonetic)
                put("meaning", entry.meaning)
                put("memberships", JsonArray(entry.levels.map(::JsonPrimitive)))
                put("tags", JsonArray(entry.tags.map(::JsonPrimitive)))
                put("mnemonic", entry.mnemonic)
                put("provenance", entry.source)
                put("examples", buildJsonArray {
                    entry.examples.forEach { example ->
                        add(buildJsonObject {
                            put("en", example.english)
                            put("zh", example.chinese)
                            put("source", example.source)
                        })
                    }
                })
            })
        }
    }.toString()

    private fun decodeEntry(item: JsonObject, defaultSource: String): VocabularyEntry {
        val word = item.string("word")
        val meaning = item.string("meaning").ifBlank {
            item.string("translation").ifBlank { item.string("meaningZh") }
        }
        val id = item.string("id").ifBlank { normalizeWordId(word) }
        val examples = decodeExamples(item)
        val levels = item.stringSet("memberships").ifEmpty {
            item.stringSet("levels").ifEmpty {
                setOf(item.string("level").ifBlank { "custom" })
            }
        }
        val provenance = item["provenance"]?.let { value ->
            when (value) {
                is JsonPrimitive -> value.contentOrNull
                is JsonObject -> value.string("source").ifBlank { value.string("name") }
                else -> null
            }
        }.orEmpty().ifBlank { defaultSource }
        return VocabularyEntry(
            id = id,
            word = word,
            meaning = meaning,
            phonetic = item.string("phonetic"),
            levels = levels,
            tags = item.stringSet("tags"),
            mnemonic = item.string("mnemonic"),
            examples = examples,
            source = provenance,
        )
    }

    private fun decodeExamples(item: JsonObject): List<BilingualExample> {
        val structured = item["examples"] as? JsonArray
        if (structured != null) {
            return structured.mapNotNull { exampleElement ->
                val example = exampleElement as? JsonObject ?: return@mapNotNull null
                val en = example.string("en").ifBlank { example.string("english") }
                val zh = example.string("zh").ifBlank { example.string("chinese") }
                if (en.isBlank() || zh.isBlank()) null else BilingualExample(en, zh, example.string("source"))
            }
        }
        return (1..3).mapNotNull { index ->
            val en = item.string("example${index}_en")
            val zh = item.string("example${index}_zh")
            if (en.isBlank() || zh.isBlank()) null else BilingualExample(en, zh)
        }
    }

    private fun JsonObject.string(key: String): String =
        (this[key] as? JsonPrimitive)?.contentOrNull?.trim().orEmpty()

    private fun JsonObject.stringSet(key: String): Set<String> {
        val value = this[key] ?: return emptySet()
        return when (value) {
            is JsonArray -> value.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.trim() }
                .filter { it.isNotEmpty() }
                .toSet()
            is JsonPrimitive -> value.contentOrNull.orEmpty()
                .split('|', ',', ' ')
                .map(String::trim)
                .filter(String::isNotEmpty)
                .toSet()
            else -> emptySet()
        }
    }
}
