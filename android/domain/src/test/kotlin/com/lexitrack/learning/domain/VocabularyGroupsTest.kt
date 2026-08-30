package com.lexitrack.learning.domain

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class VocabularyGroupsTest {
    @Test
    fun `classifier matches shared golden fixtures and counts`() {
        val path = requireNotNull(System.getProperty("vocabulary.groups.golden.path"))
        val root = Json.parseToJsonElement(File(path).readText()).jsonObject
        assertEquals("vocabulary-groups-v1", root.getValue("contractVersion").jsonPrimitive.content)

        val order = root.getValue("groupOrder").jsonArray.map { it.jsonPrimitive.content }
        assertEquals(order, GROUP_ORDER)
        assertEquals("全部", root.getValue("groupLabels").jsonObject.getValue("all").jsonPrimitive.content)

        root.getValue("normalize").jsonObject.forEach { (raw, expected) ->
            assertEquals(expected.jsonPrimitive.content, normalizeGroupMembership(raw))
        }

        val counts = GROUP_ORDER.associateWith { 0 }.toMutableMap()
        root.getValue("fixtures").jsonArray.forEach { fixtureElement ->
            val fixture = fixtureElement.jsonObject
            val expected = fixture.getValue("expectedGroups").jsonArray
                .map { it.jsonPrimitive.content }
                .sorted()
            val memberships = fixture.getValue("memberships").jsonArray.map { it.jsonPrimitive.content }.toSet()
            val tags = fixture.getValue("tags").jsonArray.map { it.jsonPrimitive.content }.toSet()
            val actual = classifyGroups(memberships, tags).sorted()
            assertEquals(expected, actual, fixture.getValue("id").jsonPrimitive.content)
            actual.forEach { counts[it] = counts.getValue(it) + 1 }
        }
        val expectedCounts = root.getValue("expected").jsonObject.getValue("groupCounts").jsonObject
        expectedCounts.forEach { (key, value) ->
            assertEquals(value.jsonPrimitive.content.toInt(), counts.getValue(key), key)
        }
    }

    @Test
    fun `arbitrary tags never create groups`() {
        val groups = classifyGroups(setOf("GK"), setOf("business"))
        assertEquals(setOf("all", "gk"), groups)
        assertEquals("GK", normalizeGroupMembership("gk"))
        assertTrue("custom" !in classifyGroups(setOf("CET4"), setOf("custom")))
    }
}
