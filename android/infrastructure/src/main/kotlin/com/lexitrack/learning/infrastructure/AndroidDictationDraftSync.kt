package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.application.DictationDraftSyncConflict
import com.lexitrack.learning.application.DictationDraftSyncEnvelope
import com.lexitrack.learning.application.DictationDraftSyncPort
import com.lexitrack.learning.application.DictationDraftSyncResult
import com.lexitrack.learning.application.DictationDraftSyncStatus
import com.lexitrack.learning.application.DICTATION_DRAFT_SYNC_VERSION
import com.lexitrack.learning.domain.MAX_DICTATION_DRAFT_BYTES
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject

/**
 * Credentials are supplied by the composition root and are intentionally not
 * persisted by this adapter.  A complete configuration is required before a
 * request can be opened; HTTP endpoints are rejected to prevent downgrade.
 */
data class AndroidDictationDraftSyncConfig(
    val endpoint: String? = null,
    val accountId: String? = null,
    val bearerToken: String? = null,
    val timeoutMillis: Int = DEFAULT_TIMEOUT_MILLIS,
) {
    val endpointUrl: String? get() = endpoint
    val token: String? get() = bearerToken

    val configured: Boolean
        get() {
            val endpointValue = endpoint?.trim().orEmpty()
            val accountValue = accountId?.trim().orEmpty()
            val tokenValue = bearerToken?.trim().orEmpty()
            if (endpointValue.isEmpty() || accountValue.isEmpty() || tokenValue.isEmpty()) return false
            if (timeoutMillis <= 0) return false
            return runCatching {
                val parsed = URL(endpointValue)
                parsed.protocol.equals("https", ignoreCase = true) &&
                    parsed.host.isNotBlank() &&
                    parsed.userInfo == null &&
                    parsed.query == null &&
                    parsed.ref == null
            }.getOrDefault(false)
        }

    override fun toString(): String =
        "AndroidDictationDraftSyncConfig(endpoint=${endpoint?.trim().orEmpty()}, " +
            "accountId=${accountId?.trim().orEmpty()}, bearerToken=<${if (bearerToken.isNullOrBlank()) "unset" else "set"}>, " +
            "timeoutMillis=$timeoutMillis)"

    companion object {
        const val DEFAULT_TIMEOUT_MILLIS = 10_000
    }
}

/** A no-network implementation useful as the explicit composition default. */
class DisabledAndroidDictationDraftSync(
    val config: AndroidDictationDraftSyncConfig = AndroidDictationDraftSyncConfig(),
) : DictationDraftSyncPort {
    override val configuredAccountId: String get() = config.accountId?.trim().orEmpty()

    override suspend fun pull(accountId: String): DictationDraftSyncResult =
        DictationDraftSyncResult(
            status = DictationDraftSyncStatus.DISABLED,
            message = "dictation draft sync is not configured; local-only mode",
        )

    override suspend fun push(
        accountId: String,
        draft: DictationDraftSyncEnvelope,
        ifMatchRevision: String?,
    ): DictationDraftSyncResult = if (draft.byteSize() > MAX_DICTATION_DRAFT_BYTES) {
        DictationDraftSyncResult(
            status = DictationDraftSyncStatus.TOO_LARGE,
            message = "dictation draft sync payload exceeds $MAX_DICTATION_DRAFT_BYTES bytes",
        )
    } else {
        DictationDraftSyncResult(
            status = DictationDraftSyncStatus.DISABLED,
            message = "dictation draft sync is not configured; local-only mode",
        )
    }

    suspend fun push(accountId: String, draft: DictationDraftSyncEnvelope): DictationDraftSyncResult =
        push(accountId, draft, null)
}

/**
 * Optional HTTPS REST adapter for `dictation-draft-v1`.
 *
 * The connection factory is injectable for deterministic tests.  No Android
 * networking library is required, and all blocking I/O is dispatched off the
 * caller's thread.
 */
class AndroidDictationDraftSync(
    val config: AndroidDictationDraftSyncConfig,
    private val connectionFactory: (URL) -> HttpURLConnection = { url ->
        url.openConnection() as HttpURLConnection
    },
) : DictationDraftSyncPort {

    constructor(
        endpoint: String?,
        accountId: String?,
        bearerToken: String?,
        timeoutMillis: Int = AndroidDictationDraftSyncConfig.DEFAULT_TIMEOUT_MILLIS,
        connectionFactory: (URL) -> HttpURLConnection = { url ->
            url.openConnection() as HttpURLConnection
        },
    ) : this(
        AndroidDictationDraftSyncConfig(endpoint, accountId, bearerToken, timeoutMillis),
        connectionFactory,
    )

    val enabled: Boolean get() = config.configured
    override val configuredAccountId: String get() = config.accountId?.trim().orEmpty()

    override suspend fun pull(accountId: String): DictationDraftSyncResult {
        if (!enabled) return disabledResult()
        val resolved = resolveAccount(accountId) ?: return invalidResult("account_id does not match sync configuration")
        return withContext(Dispatchers.IO) {
            val url = runCatching { endpointUrl(resolved) }.getOrNull()
                ?: return@withContext invalidResult("sync endpoint is invalid")
            val response = execute(url, "GET", null)
                ?: return@withContext invalidResult("dictation draft sync request failed")
            if (response.oversized) return@withContext tooLargeResult()
            when (response.status) {
                HttpURLConnection.HTTP_NOT_FOUND -> DictationDraftSyncResult(
                    status = DictationDraftSyncStatus.LOCAL_ONLY,
                    message = "remote dictation draft is missing",
                )
                HttpURLConnection.HTTP_CONFLICT,
                HttpURLConnection.HTTP_PRECON_FAILED,
                -> conflictFromResponse(response.body, resolved)
                HttpURLConnection.HTTP_OK,
                HttpURLConnection.HTTP_CREATED,
                -> decodeSuccess(response.body, resolved)
                HttpURLConnection.HTTP_NO_CONTENT -> DictationDraftSyncResult(
                    status = DictationDraftSyncStatus.LOCAL_ONLY,
                    message = "remote dictation draft is missing",
                )
                else -> invalidResult("dictation draft sync request returned an unexpected status")
            }
        }
    }

    suspend fun push(accountId: String, draft: DictationDraftSyncEnvelope): DictationDraftSyncResult =
        push(accountId, draft, null)

    override suspend fun push(
        accountId: String,
        draft: DictationDraftSyncEnvelope,
        ifMatchRevision: String?,
    ): DictationDraftSyncResult {
        // Serialize and measure before entering the I/O dispatcher or opening
        // a connection.  Local persistence remains the caller's responsibility.
        val body = runCatching { draft.canonicalJsonBytes() }.getOrNull()
            ?: return invalidResult("dictation draft envelope is invalid")
        if (body.size > MAX_DICTATION_DRAFT_BYTES) return tooLargeResult()
        if (!enabled) return disabledResult()
        val resolved = resolveAccount(accountId) ?: return invalidResult("account_id does not match sync configuration")
        if (draft.accountId.trim() != resolved) return invalidResult("account_id does not match envelope")
        val revision = if (ifMatchRevision != null) {
            ifMatchRevision.trim()
        } else {
            draft.revision.trim().let { if (it == "0") "" else it }
        }
        return withContext(Dispatchers.IO) {
            val url = runCatching { endpointUrl(resolved) }.getOrNull()
                ?: return@withContext invalidResult("sync endpoint is invalid")
            val response = execute(url, "PUT", body, revision.takeIf(String::isNotEmpty))
                ?: return@withContext invalidResult("dictation draft sync request failed")
            if (response.oversized) return@withContext tooLargeResult()
            when (response.status) {
                HttpURLConnection.HTTP_CONFLICT,
                HttpURLConnection.HTTP_PRECON_FAILED,
                -> conflictResult(draft, response.body)
                HttpURLConnection.HTTP_NOT_FOUND -> DictationDraftSyncResult(
                    status = DictationDraftSyncStatus.LOCAL_ONLY,
                    message = "remote dictation draft is missing; no overwrite was attempted",
                )
                HttpURLConnection.HTTP_OK,
                HttpURLConnection.HTTP_CREATED,
                HttpURLConnection.HTTP_NO_CONTENT,
                -> if (response.body.isEmpty()) {
                    DictationDraftSyncResult(
                        status = if (draft.deleted) DictationDraftSyncStatus.TOMBSTONE else DictationDraftSyncStatus.SYNCED,
                        envelope = draft,
                    )
                } else {
                    decodeSuccess(response.body, resolved)
                }
                else -> invalidResult("dictation draft sync request returned an unexpected status")
            }
        }
    }

    private fun resolveAccount(accountId: String?): String? {
        val requested = accountId?.trim().orEmpty().ifEmpty { config.accountId?.trim().orEmpty() }
        val configured = config.accountId?.trim().orEmpty()
        return requested.takeIf { it.isNotEmpty() && it == configured }
    }

    private fun endpointUrl(accountId: String): URL {
        val base = config.endpoint!!.trimEnd('/')
        val encoded = encodePathSegment(accountId)
        val path = if (base.endsWith("/v1/dictation-drafts")) {
            "$base/$encoded"
        } else {
            "$base/v1/dictation-drafts/$encoded"
        }
        return URL(path)
    }

    /** RFC 3986 path-segment encoding (space is %20, slash is %2F). */
    private fun encodePathSegment(value: String): String = buildString {
        value.toByteArray(StandardCharsets.UTF_8).forEach { byte ->
            val code = byte.toInt() and 0xff
            if (code in 0x30..0x39 || code in 0x41..0x5a || code in 0x61..0x7a || code == '-'.code || code == '.'.code || code == '_'.code || code == '~'.code) {
                append(code.toChar())
            } else {
                append('%')
                append("0123456789ABCDEF"[code ushr 4])
                append("0123456789ABCDEF"[code and 0x0f])
            }
        }
    }

    private fun execute(
        url: URL,
        method: String,
        body: ByteArray?,
        ifMatchRevision: String? = null,
    ): HttpResponse? {
        var connection: HttpURLConnection? = null
        return try {
            connection = connectionFactory(url)
            connection.requestMethod = method
            connection.connectTimeout = config.timeoutMillis
            connection.readTimeout = config.timeoutMillis
            connection.useCaches = false
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Authorization", "Bearer ${config.bearerToken!!.trim()}")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                ifMatchRevision?.let { connection.setRequestProperty("If-Match", it) }
                connection.outputStream.use { it.write(body) }
            }
            val status = connection.responseCode
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val read = readBounded(stream)
            HttpResponse(status, read.bytes, read.oversized)
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        } finally {
            connection?.disconnect()
        }
    }

    private fun decodeSuccess(body: ByteArray, accountId: String): DictationDraftSyncResult {
        val envelope = decodeEnvelope(body) ?: return invalidResult("sync response was not a valid dictation draft envelope")
        if (envelope.accountId.trim() != accountId) return invalidResult("sync response account_id does not match request")
        return DictationDraftSyncResult(
            status = if (envelope.deleted) DictationDraftSyncStatus.TOMBSTONE else DictationDraftSyncStatus.SYNCED,
            envelope = envelope,
        )
    }

    private fun conflictFromResponse(body: ByteArray, accountId: String): DictationDraftSyncResult {
        val remote = decodeEnvelope(body)
        if (remote != null && remote.accountId.trim() != accountId) {
            return invalidResult("sync response account_id does not match request")
        }
        return DictationDraftSyncResult(
            status = DictationDraftSyncStatus.CONFLICT,
            envelope = remote,
            message = "remote dictation draft revision conflict",
        )
    }

    private fun conflictResult(
        local: DictationDraftSyncEnvelope,
        body: ByteArray,
    ): DictationDraftSyncResult {
        val remote = decodeEnvelope(body)
        if (remote != null && remote.accountId.trim() != local.accountId.trim()) {
            return invalidResult("sync response account_id does not match request")
        }
        return if (remote == null) {
            DictationDraftSyncResult(
                status = DictationDraftSyncStatus.CONFLICT,
                message = "remote dictation draft revision conflict",
            )
        } else {
            DictationDraftSyncResult(
                status = DictationDraftSyncStatus.CONFLICT,
                envelope = remote,
                conflict = DictationDraftSyncConflict(local = local, remote = remote),
                message = "remote dictation draft revision conflict",
            )
        }
    }

    private fun decodeEnvelope(body: ByteArray): DictationDraftSyncEnvelope? = runCatching {
        if (body.isEmpty()) return@runCatching null
        val root = Json.parseToJsonElement(body.toString(Charsets.UTF_8)).jsonObject
        val candidate = (root["remote"] as? JsonObject)
            ?: (root["envelope"] as? JsonObject)
            ?: root
        DictationDraftSyncEnvelope.fromJsonObject(candidate)
    }.getOrNull()

    private fun disabledResult() = DictationDraftSyncResult(
        status = DictationDraftSyncStatus.DISABLED,
        message = "dictation draft sync is not configured; local-only mode",
    )

    private fun invalidResult(message: String) = DictationDraftSyncResult(
        status = DictationDraftSyncStatus.INVALID,
        message = message,
    )

    private fun tooLargeResult() = DictationDraftSyncResult(
        status = DictationDraftSyncStatus.TOO_LARGE,
        message = "dictation draft sync payload exceeds $MAX_DICTATION_DRAFT_BYTES bytes",
    )

    private data class HttpResponse(
        val status: Int,
        val body: ByteArray,
        val oversized: Boolean,
    )

    private data class ReadResult(val bytes: ByteArray, val oversized: Boolean)

    private fun readBounded(stream: InputStream?): ReadResult {
        if (stream == null) return ReadResult(ByteArray(0), false)
        stream.use { input ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var total = 0
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                total += read
                if (total > MAX_DICTATION_DRAFT_BYTES) {
                    return ReadResult(ByteArray(0), true)
                }
                output.write(buffer, 0, read)
            }
            return ReadResult(output.toByteArray(), false)
        }
    }

    private companion object {
        const val DEFAULT_BUFFER_SIZE = 8192
    }
}

/** Naming aliases used by platform composition roots. */
typealias DictationDraftSyncConfig = AndroidDictationDraftSyncConfig
typealias DisabledDictationDraftSync = DisabledAndroidDictationDraftSync
typealias DisabledDictationDraftSyncPort = DisabledAndroidDictationDraftSync
typealias HttpDictationDraftSync = AndroidDictationDraftSync
typealias HttpsDictationDraftSync = AndroidDictationDraftSync
typealias OnlineDictationDraftSync = AndroidDictationDraftSync
