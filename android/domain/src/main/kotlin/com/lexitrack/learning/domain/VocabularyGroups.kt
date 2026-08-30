package com.lexitrack.learning.domain

import java.text.Normalizer
import java.util.Locale

/**
 * Vocabulary-group classification mirrors shared/contracts/vocabulary-groups-v1.md
 * and vocabulary-groups-golden-v1.json. It is pure Kotlin with no Android SDK
 * dependency so words classify identically on Windows and Android.
 */
val GROUP_ORDER = listOf("all", "cet4", "cet6", "zk", "gk", "custom")

val GROUP_LABELS = mapOf(
    "all" to "全部",
    "cet4" to "CET-4（四级）",
    "cet6" to "CET-6（六级）",
    "zk" to "中考（zk）",
    "gk" to "高考（gk）",
    "custom" to "自定义",
)

private val GROUP_RULES = listOf(
    Triple("cet4", setOf("CET4"), setOf("cet4")),
    Triple("cet6", setOf("CET6"), setOf("cet6")),
    Triple("zk", setOf("ZK"), setOf("zk")),
    Triple("gk", setOf("GK"), setOf("gk")),
)

private val CANONICAL_MEMBERSHIPS = setOf("CET4", "CET6", "ZK", "GK", "CUSTOM")

private fun stripSeparators(value: String): String = buildString {
    for (ch in value) {
        if (ch !in " -_.") append(ch)
    }
}

fun normalizeGroupMembership(code: String): String =
    stripSeparators(Normalizer.normalize(code.trim(), Normalizer.Form.NFKC)).uppercase(Locale.ROOT)

fun normalizeGroupTag(tag: String): String =
    Normalizer.normalize(tag.trim(), Normalizer.Form.NFKC).lowercase(Locale.ROOT)

fun classifyGroups(memberships: Set<String>, tags: Set<String>): Set<String> {
    val levels = memberships.mapTo(mutableSetOf()) { normalizeGroupMembership(it) }
    val normalizedTags = tags.mapTo(mutableSetOf()) { normalizeGroupTag(it) }
    val result = mutableSetOf("all")
    for ((key, levelCodes, tagCodes) in GROUP_RULES) {
        if (levels.any { it in levelCodes } || normalizedTags.any { it in tagCodes }) {
            result.add(key)
        }
    }
    if ("CUSTOM" in levels) result.add("custom")
    return result
}

fun groupLabel(key: String): String = GROUP_LABELS[key] ?: key

fun canonicalMemberships(): Set<String> = CANONICAL_MEMBERSHIPS
