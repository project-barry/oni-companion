package io.github.projectbarry.onicompanion.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import java.net.Inet4Address
import java.net.Inet6Address
import java.util.ArrayDeque

/** Browses `_onicompanion._tcp` with the system's NsdManager. Results are hints; see [Classifier]. */
class NsdDiscovery(
    context: Context,
    private val onFound: (Announced) -> Unit,
    private val onLost: (String) -> Unit,
) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val queue = ArrayDeque<NsdServiceInfo>()
    private var resolving = false
    private var listener: NsdManager.DiscoveryListener? = null

    companion object {
        const val TYPE = "_onicompanion._tcp."
        private const val TAG = "OniNsd"
        private val NAME = Regex("^[a-z]{2,20}-[a-z]{2,20}$")

        fun txt(info: NsdServiceInfo, key: String, max: Int): String? =
            info.attributes?.get(key)?.let { String(it, Charsets.UTF_8) }?.takeIf { it.length <= max }

        /** TXT keys are exactly id, name, api, core. A bad or missing one makes the entry unusable. */
        fun toAnnounced(info: NsdServiceInfo): Announced? {
            val addr = info.host ?: return null
            val host = when {
                addr is Inet4Address -> addr.hostAddress
                addr is Inet6Address && !addr.isLinkLocalAddress -> addr.hostAddress?.substringBefore('%')
                else -> null
            } ?: return null
            val id = txt(info, "id", 64) ?: return null
            val name = txt(info, "name", 41)?.takeIf { NAME.matches(it) } ?: return null
            return Announced(info.serviceName, id, name, txt(info, "api", 4) ?: "1", txt(info, "core", 20) ?: "", host, info.port)
        }
    }

    fun start() {
        if (listener != null) return
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(t: String) {}
            override fun onDiscoveryStopped(t: String) {}
            override fun onStartDiscoveryFailed(t: String, code: Int) { Log.w(TAG, "start failed $code"); listener = null }
            override fun onStopDiscoveryFailed(t: String, code: Int) {}
            override fun onServiceFound(info: NsdServiceInfo) { enqueue(info) }
            override fun onServiceLost(info: NsdServiceInfo) { onLost(info.serviceName) }
        }
        listener = l
        nsd.discoverServices(TYPE, NsdManager.PROTOCOL_DNS_SD, l)
    }

    fun stop() {
        val l = listener ?: return
        listener = null
        runCatching { nsd.stopServiceDiscovery(l) }
        synchronized(queue) { queue.clear(); resolving = false }
    }

    private fun enqueue(info: NsdServiceInfo) {
        synchronized(queue) { queue.add(info) }
        next()
    }

    // NsdManager resolves one service at a time.
    private fun next() {
        val info = synchronized(queue) {
            if (resolving) return
            val i = queue.poll() ?: return
            resolving = true
            i
        }
        @Suppress("DEPRECATION")
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(i: NsdServiceInfo, code: Int) { done() }
            override fun onServiceResolved(i: NsdServiceInfo) {
                toAnnounced(i)?.let(onFound)
                done()
            }
        })
    }

    private fun done() { synchronized(queue) { resolving = false }; next() }
}
