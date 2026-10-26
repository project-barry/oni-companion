package io.github.projectbarry.onicompanion.net

/** What a TLS connection to an address proved: the certificate fingerprint (and the public label body). */
data class ProbeResult(val fingerprint: String, val identity: Identity?) {
    val tag get() = Fingerprint.tag(fingerprint)
}

/**
 * Reads the certificate fingerprint of a service we have not pinned yet, and its public GET /identity.
 * Sends no token and no pairing code. The fingerprint comes from the TLS handshake itself, never
 * from the body (a body is only a label anyone could copy).
 */
object Prober {
    suspend fun probe(host: String, port: Int): ProbeResult {
        val (http, capture) = Tls.captureClient()
        val conn = PinnedConnection(listOf(host), port, "0".repeat(64), null)
        val api = ApiClient(conn, http)
        val body = api.get("/identity")
        val fp = capture.fingerprint ?: throw UnreachableException("no certificate seen")
        val id = runCatching { ApiJson.decodeFromJsonElement(Identity.serializer(), body) }.getOrNull()
        return ProbeResult(fp, id)
    }
}
