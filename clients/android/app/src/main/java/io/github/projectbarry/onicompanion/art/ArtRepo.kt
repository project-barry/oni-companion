package io.github.projectbarry.onicompanion.art

import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import io.github.projectbarry.onicompanion.net.ApiClient
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

/**
 * Pictures from the core's art folder (GET /art/...), drawn from the user's own game: nothing is bundled.
 * Memory cache first, then a folder in the app's cache directory, then the network. A 404 means "no art
 * (yet)": it is remembered until the core says the art manifest changed (the `art` event, [bumpGeneration]),
 * so a row that scrolls past again does not ask again, but a picture the game has just drawn gets picked up.
 */
class ArtRepo(private val api: ApiClient, private val dir: File) {
    /** Changes whenever the core reports new art; pictures that came back 404 ask again after it. */
    var generation by mutableIntStateOf(0)
        private set

    private val mem = object : LruCache<String, ImageBitmap>(32 * 1024 * 1024) {
        override fun sizeOf(key: String, value: ImageBitmap) = value.width * value.height * 4
    }
    private val missing = HashMap<String, Int>()          // path -> generation it answered 404 in
    private val inflight = HashMap<String, CompletableDeferred<ImageBitmap?>>()
    private val lock = Any()
    private val gate = Semaphore(4)

    fun bumpGeneration() { generation++ }

    fun peek(path: String): ImageBitmap? = synchronized(lock) { mem.get(path) }

    fun isMissing(path: String): Boolean = synchronized(lock) { missing[path] == generation }

    /** Forget everything stored (after a sync wrote new pictures). */
    fun clear() {
        synchronized(lock) { mem.evictAll(); missing.clear() }
        dir.deleteRecursively()
    }

    suspend fun load(path: String): ImageBitmap? {
        val ours: CompletableDeferred<ImageBitmap?>
        val theirs: CompletableDeferred<ImageBitmap?>?
        synchronized(lock) {
            mem.get(path)?.let { return it }
            if (missing[path] == generation) return null
            theirs = inflight[path]
            ours = CompletableDeferred()
            if (theirs == null) inflight[path] = ours
        }
        if (theirs != null) return theirs.await()
        var result: ImageBitmap? = null
        try {
            result = fetch(path)
            return result
        } finally {
            synchronized(lock) {
                inflight.remove(path)
                if (result != null) mem.put(path, result) else missing[path] = generation
            }
            ours.complete(result)
        }
    }

    private suspend fun fetch(path: String): ImageBitmap? {
        val file = File(dir, hash(path))
        val cached = withContext(Dispatchers.IO) { if (file.isFile) runCatching { file.readBytes() }.getOrNull() else null }
        if (cached != null) decode(cached)?.let { return it }
        val bytes = gate.withPermit { api.bytes(path) } ?: return null
        val bmp = decode(bytes) ?: return null
        withContext(Dispatchers.IO) { runCatching { dir.mkdirs(); file.writeBytes(bytes) } }
        return bmp
    }

    private suspend fun decode(bytes: ByteArray): ImageBitmap? = withContext(Dispatchers.Default) {
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    }

    private fun hash(s: String): String =
        MessageDigest.getInstance("SHA-1").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }
}
