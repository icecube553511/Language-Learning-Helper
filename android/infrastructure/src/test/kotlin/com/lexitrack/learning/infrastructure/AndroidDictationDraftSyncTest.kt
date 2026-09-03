package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.application.DictationDraftSyncEnvelope
import com.lexitrack.learning.application.DictationDraftSyncStatus
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationGroupDraft
import com.lexitrack.learning.domain.MAX_DICTATION_DRAFT_BYTES
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidDictationDraftSyncTest {
    private val localDraft = DictationDraft(
        mode = "manual",
        scopeGroup = "CET-4",
        selectedIds = setOf(" Apple ", "BANANA"),
        groups = mapOf(
            "CET-4" to DictationGroupDraft(
                selectedIds = setOf(" Apple ", "BANANA"),
                anchorId = "Apple",
                endpointId = "BANANA",
            ),
        ),
    )

    private fun envelope(
        accountId: String = "user-1",
        revision: String = "42",
        draft: DictationDraft? = localDraft,
    ) = DictationDraftSyncEnvelope(
        accountId = accountId,
        revision = revision,
        updatedAtUtc = 1_730_000_000.0,
        deleted = draft == null,
        draft = draft,
    )

    @Test
    fun missingConfigurationNeverOpensConnection() = runBlocking {
        val calls = AtomicInteger()
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig(),
            connectionFactory = {
                calls.incrementAndGet()
                throw AssertionError("network must remain disabled")
            },
        )

        assertFalse(adapter.enabled)
        assertEquals(DictationDraftSyncStatus.DISABLED, adapter.pull("user-1").status)
        assertEquals(DictationDraftSyncStatus.DISABLED, adapter.push("user-1", envelope()).status)
        assertEquals(0, calls.get())
    }

    @Test
    fun canonicalEnvelopeUsesSortedCrossPlatformWireShape() {
        val actual = envelope().canonicalJson()
        assertTrue(actual.startsWith("{\"accountId\":\"user-1\",\"deleted\":false,\"draft\":{\"count\":10"))
        assertTrue("actual=$actual", actual.contains("\"updatedAtUtc\":1730000000.0"))
        assertFalse(actual.contains(" "))
    }

    @Test
    fun envelopeCanonicalizationAlignsEmbeddedMetadata() {
        val stale = localDraft.copy(
            syncMetadata = com.lexitrack.learning.domain.DictationDraftSyncMetadata(
                accountId = "old-account",
                revision = "old-revision",
                updatedAtUtc = 1.0,
            ),
        )
        val canonical = envelope(draft = stale).canonicalJson()
        val decoded = DictationDraftSyncEnvelope.fromJson(canonical)
        assertNotNull(decoded)
        assertEquals("user-1", decoded?.draft?.syncMetadata?.accountId)
        assertEquals("42", decoded?.draft?.syncMetadata?.revision)
        assertEquals(1_730_000_000.0, decoded?.draft?.syncMetadata?.updatedAtUtc ?: 0.0, 0.0)
    }

    @Test
    fun unsupportedEnvelopeVersionIsRejected() {
        val raw = envelope().canonicalJson().replaceFirst("{", "{\"version\":\"dictation-draft-v2\",")
        assertNull(DictationDraftSyncEnvelope.fromJson(raw))
    }

    @Test
    fun nonHttpsAndCredentiallessConfigurationsAreDisabledAndRedacted() {
        val token = "do-not-leak"
        val config = AndroidDictationDraftSyncConfig(
            endpoint = "http://sync.example",
            accountId = "user-1",
            bearerToken = token,
        )
        assertFalse(config.configured)
        assertFalse(config.toString().contains(token))
        assertTrue(config.toString().contains("bearerToken=<set>"))
    }

    @Test
    fun pullUsesEncodedHttpsPathAndBearerHeader() = runBlocking {
        val remote = envelope(accountId = "user/a b")
        lateinit var connection: FakeConnection
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig(
                endpoint = "https://sync.example/api",
                accountId = "user/a b",
                bearerToken = "secret-token",
            ),
            connectionFactory = { url ->
                connection = FakeConnection(url, HttpURLConnection.HTTP_OK, remote.canonicalJsonBytes())
                connection
            },
        )

        val result = adapter.pull("user/a b")

        assertEquals(DictationDraftSyncStatus.SYNCED, result.status)
        assertEquals(remote.canonicalJson(), result.envelope?.canonicalJson())
        assertEquals("https://sync.example/api/v1/dictation-drafts/user%2Fa%20b", connection.url.toString())
        assertEquals("GET", connection.requestMethod)
        assertEquals("Bearer secret-token", connection.getRequestProperty("Authorization"))
        assertEquals("application/json", connection.getRequestProperty("Accept"))
    }

    @Test
    fun pushSendsCanonicalBodyAndIfMatch() = runBlocking {
        val local = envelope()
        lateinit var connection: FakeConnection
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig(
                endpoint = "https://sync.example",
                accountId = "user-1",
                bearerToken = "secret-token",
            ),
            connectionFactory = { url ->
                connection = FakeConnection(url, HttpURLConnection.HTTP_OK, local.canonicalJsonBytes())
                connection
            },
        )

        val result = adapter.push("user-1", local, ifMatchRevision = "41")

        assertEquals(DictationDraftSyncStatus.SYNCED, result.status)
        assertEquals("PUT", connection.requestMethod)
        assertEquals("Bearer secret-token", connection.getRequestProperty("Authorization"))
        assertEquals("41", connection.getRequestProperty("If-Match"))
        assertEquals("application/json", connection.getRequestProperty("Content-Type"))
        assertArrayEquals(local.canonicalJsonBytes(), connection.requestBody.toByteArray())
    }

    @Test
    fun initialRevisionOmitsIfMatchHeader() = runBlocking {
        val initial = envelope(revision = "0")
        lateinit var connection: FakeConnection
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = { url ->
                connection = FakeConnection(url, HttpURLConnection.HTTP_NO_CONTENT)
                connection
            },
        )

        val result = adapter.push("user-1", initial)

        assertEquals(DictationDraftSyncStatus.SYNCED, result.status)
        assertNull(connection.getRequestProperty("If-Match"))
    }

    @Test
    fun conflictsRetainLocalAndRemoteEnvelopes() = runBlocking {
        val local = envelope(revision = "41")
        val remote = envelope(revision = "42", draft = localDraft.copy(customExample = "remote"))
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = { url ->
                FakeConnection(url, HttpURLConnection.HTTP_CONFLICT, remote.canonicalJsonBytes())
            },
        )

        val result = adapter.push("user-1", local)

        assertEquals(DictationDraftSyncStatus.CONFLICT, result.status)
        assertNotNull(result.conflict)
        assertEquals("41", result.conflict?.local?.revision)
        assertEquals("42", result.conflict?.remote?.revision)
        assertNotNull(result.envelope)
        assertFalse(result.message.contains("secret"))
        assertFalse(result.toString().contains("secret"))
    }

    @Test
    fun missingRemoteAndTombstoneAreExplicit() = runBlocking {
        val missing = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = { url -> FakeConnection(url, HttpURLConnection.HTTP_NOT_FOUND) },
        )
        val missingResult = missing.pull("user-1")
        assertEquals(DictationDraftSyncStatus.LOCAL_ONLY, missingResult.status)
        assertTrue(missingResult.message.contains("missing"))

        val tombstone = envelope(revision = "43", draft = null)
        val remoteDeleted = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = { url -> FakeConnection(url, HttpURLConnection.HTTP_OK, tombstone.canonicalJsonBytes()) },
        )
        val tombstoneResult = remoteDeleted.pull("user-1")
        assertEquals(DictationDraftSyncStatus.TOMBSTONE, tombstoneResult.status)
        assertTrue(tombstoneResult.envelope?.deleted == true)
        assertNull(tombstoneResult.envelope?.draft)
    }

    @Test
    fun oversizedEnvelopeIsRejectedBeforeConnection() = runBlocking {
        val calls = AtomicInteger()
        val huge = envelope(draft = localDraft.copy(customExample = "x".repeat(MAX_DICTATION_DRAFT_BYTES)))
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = {
                calls.incrementAndGet()
                throw AssertionError("oversized request must not open a connection")
            },
        )

        val result = adapter.push("user-1", huge)

        assertEquals(DictationDraftSyncStatus.TOO_LARGE, result.status)
        assertEquals(0, calls.get())
    }

    @Test
    fun networkFailureReturnsStableInvalidResult() = runBlocking {
        val adapter = AndroidDictationDraftSync(
            AndroidDictationDraftSyncConfig("https://sync.example", "user-1", "secret"),
            connectionFactory = { throw IOException("secret should not escape") },
        )

        val result = adapter.pull("user-1")

        assertEquals(DictationDraftSyncStatus.INVALID, result.status)
        assertFalse(result.message.contains("secret"))
    }

    private class FakeConnection(
        url: URL,
        private val statusCode: Int,
        private val responseBody: ByteArray = ByteArray(0),
        private val errorBody: ByteArray = responseBody,
    ) : HttpURLConnection(url) {
        val requestBody = ByteArrayOutputStream()

        override fun connect() = Unit
        override fun disconnect() = Unit
        override fun usingProxy(): Boolean = false
        override fun getResponseCode(): Int = statusCode
        override fun getInputStream() = ByteArrayInputStream(responseBody)
        override fun getErrorStream() = if (statusCode >= 400) ByteArrayInputStream(errorBody) else null
        override fun getOutputStream() = requestBody
    }
}
