package io.github.projectbarry.onicompanion.net

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import javax.net.ssl.SSLException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** The service answered with an error (Error in api.schema.json). 401 = not paired any more. */
class ApiException(val status: Int, val code: String, message: String) : IOException(message) {
    val unauthorized get() = status == 401
}

/** No address of the service could be reached. */
class UnreachableException(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * HTTP client for one service. Paths are relative to /api/v1 (as the API lists them), e.g. "/status".
 * For a [PinnedConnection] the TLS handshake accepts only the pinned certificate, so the device
 * token header can never reach a different server. Addresses are tried in order.
 */
class ApiClient(private val conn: Connection, client: OkHttpClient? = null) {
    private val http: OkHttpClient = client ?: when (conn) {
        is PinnedConnection -> Tls.pinnedClient(conn.fingerprint)
        is LoopbackConnection, is LocalConnection -> Tls.plainClient()
    }
    @Volatile private var lastGood = 0

    private val hosts: List<String> = when (conn) {
        is PinnedConnection -> conn.hosts
        is LoopbackConnection -> listOf(conn.host)
        is LocalConnection -> listOf("local")
    }

    private fun url(host: String, path: String): HttpUrl {
        val (scheme, port) = when (conn) {
            is PinnedConnection -> "https" to conn.port
            is LoopbackConnection -> "http" to conn.port
            is LocalConnection -> "http" to 0
        }
        val base = HttpUrl.Builder().scheme(scheme).host(host).port(port).build()
        return base.resolve("/api/v1$path") ?: throw IllegalArgumentException("bad path")
    }

    private fun build(host: String, path: String, method: String, body: JsonElement?): Request {
        val b = Request.Builder().url(url(host, path))
        when (conn) {
            is PinnedConnection -> conn.deviceToken?.let { b.header("X-Oni-Device", it) }
            is LoopbackConnection -> b.header("X-Oni-Token", conn.token)
            is LocalConnection -> Unit
        }
        val rb = (body?.toString() ?: if (method == "POST") "{}" else null)
            ?.toRequestBody("application/json; charset=utf-8".toMediaType())
        return b.method(method, rb).build()
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { c ->
        c.invokeOnCancellation { cancel() }
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { c.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) { c.resume(response) }
        })
    }

    private fun isPinFailure(e: Throwable): Boolean {
        var t: Throwable? = e
        while (t != null) { if (t is PinMismatchException) return true; t = t.cause }
        return false
    }

    /** One answer, whatever its status: [body] is the raw bytes. */
    class Raw(val status: Int, val body: ByteArray) {
        val ok get() = status in 200..299
    }

    /** Sends one request, trying the addresses in order. Throws only for network, pin and cancellation problems. */
    suspend fun send(method: String, path: String, body: JsonElement? = null, http: OkHttpClient = this.http): Raw {
        if (conn is LocalConnection) {
            val reply = withContext(Dispatchers.IO) { conn.api.call(method, path, body?.toString()) }
            return Raw(reply.status, reply.body)
        }
        var failure: Throwable? = null
        val order = hosts.indices.map { (lastGood + it) % hosts.size }
        for (i in order) {
            val host = hosts[i]
            try {
                val call = http.newCall(build(host, path, method, body))
                call.await().use { resp ->
                    lastGood = i
                    val bytes = withContext(Dispatchers.IO) { resp.body?.bytes() ?: ByteArray(0) }
                    return Raw(resp.code, bytes)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: IOException) {
                // A wrong certificate is final: another address of the same service will not fix it.
                if (isPinFailure(e) || (e is SSLException && conn is PinnedConnection && e.message?.contains("Trust") == true)) {
                    throw PinMismatchException("Can't verify this device")
                }
                failure = e
            }
        }
        throw UnreachableException("Can't reach the gaming device", failure)
    }

    suspend fun request(method: String, path: String, body: JsonElement? = null, http: OkHttpClient = this.http): JsonObject {
        val r = send(method, path, body, http)
        val text = r.body.toString(Charsets.UTF_8)
        if (!r.ok) throw errorOf(r.status, text)
        return if (text.isBlank()) JsonObject(emptyMap()) else ApiJson.parseToJsonElement(text).jsonObject
    }

    /**
     * A file (art, a font): [path] is the API path as the core writes it ("/api/v1/art/building/Ladder").
     * Returns null for 404 ("no such picture"); other errors throw like [request].
     */
    suspend fun bytes(path: String): ByteArray? {
        val r = send("GET", path.removePrefix("/api/v1"))
        if (r.status == 404) return null
        if (!r.ok) throw errorOf(r.status, r.body.toString(Charsets.UTF_8))
        return r.body
    }

    private fun errorOf(status: Int, text: String): ApiException {
        val err = runCatching { ApiJson.parseToJsonElement(text).jsonObject["error"]?.jsonObject }.getOrNull()
        val code = err?.get("code")?.jsonPrimitive?.contentOrNull ?: "http_$status"
        val msg = err?.get("message")?.jsonPrimitive?.contentOrNull ?: "Request failed ($status)"
        return ApiException(status, code, msg)
    }

    suspend fun get(path: String) = request("GET", path)
    suspend fun post(path: String, body: JsonElement? = null) = request("POST", path, body)
    suspend fun delete(path: String) = request("DELETE", path)

    /** One long-poll round. Pass the last [EventsReply.seq] (0 for "the current seq"). */
    suspend fun events(since: Long, timeoutSeconds: Int = 25): EventsReply {
        val longClient = if (conn is LocalConnection) http else http.newBuilder().readTimeout(java.time.Duration.ofSeconds(timeoutSeconds + 10L)).build()
        val o = request("GET", "/events?since=$since&timeout=$timeoutSeconds", http = longClient)
        return ApiJson.decodeFromJsonElement(EventsReply.serializer(), o)
    }

    suspend fun identity(): Identity =
        ApiJson.decodeFromJsonElement(Identity.serializer(), get("/identity"))
}
