package io.github.projectbarry.onicompanion.net

/** Where and how an [ApiClient] talks to one service. */
sealed interface Connection

/**
 * A paired (or being-paired) gaming device over TLS. [deviceToken] is null only while claiming
 * a pairing code; it is sent as X-Oni-Device and only inside the pinned TLS session.
 */
data class PinnedConnection(
    val hosts: List<String>,
    val port: Int,
    val fingerprint: String,
    val deviceToken: String?,
) : Connection

/** Plain HTTP to this phone's own loopback (dev runs through adb reverse, later the local mode). */
data class LoopbackConnection(val host: String, val port: Int, val token: String) : Connection {
    init { require(host == "127.0.0.1" || host == "localhost" || host == "::1") { "loopback only" } }
}

/** Local mode (plan 4.2): the core embedded in this app, called in-process. No network, no pairing, no token. */
data class LocalConnection(val api: io.github.projectbarry.onicompanion.local.LocalApi) : Connection
