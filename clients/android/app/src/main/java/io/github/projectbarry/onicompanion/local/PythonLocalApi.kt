package io.github.projectbarry.onicompanion.local

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Chaquopy bridge to `oni_local.py` (clients/android/app/src/main/python). */
class PythonLocalApi private constructor(private val mod: PyObject) : LocalApi {

    override fun call(method: String, path: String, body: String?): LocalReply {
        val t = mod.callAttr("call", method, path, body).asList()
        return LocalReply(t[0].toInt(), t[1].toString(), t[2].toString(), t[3].toJava(ByteArray::class.java))
    }

    fun start(userDir: String, dataDir: String) { mod.callAttr("start", userDir, dataDir) }
    fun stop() { mod.callAttr("stop") }
    fun touch(path: String) { mod.callAttr("touch", path) }
    fun removed(path: String) { mod.callAttr("removed", path) }
    fun staleIn(): Double = mod.callAttr("stale_in").toDouble()
    fun publishStale() { mod.callAttr("publish_stale") }

    companion object {
        fun load(ctx: Context): PythonLocalApi {
            if (!Python.isStarted()) Python.start(AndroidPlatform(ctx.applicationContext))
            return PythonLocalApi(Python.getInstance().getModule("oni_local"))
        }
    }
}
