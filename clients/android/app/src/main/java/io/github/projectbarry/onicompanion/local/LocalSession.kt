package io.github.projectbarry.onicompanion.local

import android.content.Context
import android.os.FileObserver
import android.os.Handler
import android.os.HandlerThread
import java.io.File

/**
 * Local mode while the app is open (plan 4.2): the embedded core runs on a private mirror of the shared folder.
 * Everything is event driven: a ContentObserver per shared folder, an inotify FileObserver on the private command
 * inbox, and one timer for the moment live.json goes stale. Nothing polls and no socket is opened.
 */
class LocalSession(private val ctx: Context, private val tree: SafTree, private val py: PythonLocalApi) {
    private val userDir = File(ctx.filesDir, "local")
    private val companion = File(userDir, "companion")
    private val thread = HandlerThread("oni-local").apply { start() }
    private val handler = Handler(thread.looper)
    private val mirror = Mirror(tree, companion) { f, removed ->
        if (removed) py.removed(f.path) else py.touch(f.path)
    }
    private val observers = HashMap<String, AutoCloseable>()
    private var commandWatch: FileObserver? = null
    @Volatile private var running = false

    val api: LocalApi get() = py

    private val down = Runnable { syncDown() }
    private val up = Runnable { mirror.syncUp() }
    private val stale = Runnable { py.publishStale() }

    fun start() {
        File(companion, "commands").mkdirs()
        py.start(userDir.path, File(ctx.filesDir, "local-data").apply { mkdirs() }.path)
        running = true
        watchCommands()
        handler.post(down)
    }

    /** Called when something in the shared tree may have changed (also on resume, and from "Refresh"). */
    fun refresh() { if (running) { handler.removeCallbacks(down); handler.postDelayed(down, 40) } }

    private fun syncDown() {
        if (!running) return
        mirror.syncDown()
        observeFolders()
        handler.removeCallbacks(stale)
        val left = py.staleIn()
        if (left > 0) handler.postDelayed(stale, (left * 1000).toLong() + 250)
    }

    private fun observeFolders() {
        for (dir in mirror.folders) {
            if (dir in observers) continue
            observers[dir] = tree.watch(dir) { refresh() } ?: continue
        }
    }

    private fun watchCommands() {
        val dir = File(companion, "commands")
        val w = object : @Suppress("DEPRECATION") FileObserver(dir.path, CLOSE_WRITE or MOVED_TO) {
            override fun onEvent(event: Int, path: String?) {
                if (path != null && path.endsWith(".json")) handler.post(up)
            }
        }
        w.startWatching()
        commandWatch = w
    }

    fun stop() {
        running = false
        commandWatch?.stopWatching()
        observers.values.forEach { runCatching { it.close() } }
        observers.clear()
        handler.removeCallbacksAndMessages(null)
        py.stop()
        thread.quitSafely()
    }
}
