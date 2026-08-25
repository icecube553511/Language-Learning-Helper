package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import java.io.ByteArrayInputStream
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidVocabularyRepositoryTest {
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        clearPreferences()
    }

    @After
    fun tearDown() = clearPreferences()

    @Test
    fun batchLabelsOnlyModifyImportedEntries() = runBlocking {
        val repository = AndroidVocabularyRepository(context)
        repository.initialize()
        val builtInBefore = repository.words.value.firstOrNull { it.id == "a" }
        assertNotNull(builtInBefore)
        repository.importCsv(ByteArrayInputStream(CSV.toByteArray(Charsets.UTF_8)))

        val updated = repository.updateLabels(
            wordIds = setOf("a", "custom-word"),
            levels = setOf("CET6"),
            tags = setOf("batch", "exam"),
        )

        assertEquals(1, updated)
        assertEquals(builtInBefore, repository.words.value.first { it.id == "a" })
        val custom = repository.words.value.first { it.id == "custom-word" }
        assertEquals(setOf("CET6"), custom.levels)
        assertEquals(setOf("batch", "exam"), custom.tags)
    }

    private fun clearPreferences() {
        context.getSharedPreferences("lexitrack_vocabulary", Context.MODE_PRIVATE).edit().clear().commit()
    }

    private companion object {
        val CSV = """
            word,meaning,level,tags,example1_en,example1_zh,example2_en,example2_zh,example3_en,example3_zh
            custom-word,自定义词,CET4,old,First custom example.,第一条例句。,Second custom example.,第二条例句。,Third custom example.,第三条例句。
        """.trimIndent()
    }
}
