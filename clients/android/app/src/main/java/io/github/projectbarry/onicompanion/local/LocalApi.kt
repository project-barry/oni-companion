package io.github.projectbarry.onicompanion.local

class LocalReply(val status: Int, val contentType: String, val etag: String, val body: ByteArray)

/** The embedded core as seen from Kotlin: the same routes the HTTP service has, called in-process. */
interface LocalApi {
    /** [path] is below /api/v1, e.g. "/home" or "/events?since=3&timeout=25". Blocks (events long-poll). */
    fun call(method: String, path: String, body: String?): LocalReply
}
