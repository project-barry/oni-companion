package io.github.projectbarry.onicompanion.discovery

import io.github.projectbarry.onicompanion.net.Prober
import io.github.projectbarry.onicompanion.store.PairingStore
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * Keeps the "found nearby" list. Each announcement is probed over TLS (no token, no code) to learn
 * its real certificate fingerprint, then classified against the stored pairings.
 */
class DiscoveryRepository(
    private val store: PairingStore,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher = Dispatchers.IO,
    private val probe: suspend (String, Int) -> Probe = { h, p ->
        try { Probe.Seen(Prober.probe(h, p).fingerprint) } catch (e: Exception) { Probe.Unreachable }
    },
) {
    private val announced = LinkedHashMap<String, Announced>()
    private val probes = HashMap<String, Probe>()
    private val _entries = MutableStateFlow<List<Entry>>(emptyList())
    val entries: StateFlow<List<Entry>> = _entries

    @Synchronized fun onFound(a: Announced) {
        announced[a.key] = a
        probes[a.key] = Probe.Pending
        publish()
        scope.launch(io) {
            val r = probe(a.host, a.port)
            synchronized(this@DiscoveryRepository) {
                if (announced[a.key] != a) return@launch
                probes[a.key] = r
                if (r is Probe.Seen) store.updateAddress(r.fingerprint, a.host, a.port)
                publish()
            }
        }
    }

    @Synchronized fun onLost(key: String) { announced.remove(key); probes.remove(key); publish() }

    @Synchronized fun clear() { announced.clear(); probes.clear(); publish() }

    /** Pairings changed (paired or forgotten): re-classify. */
    @Synchronized fun refresh() = publish()

    private fun publish() {
        val pairings = store.all()
        _entries.value = Classifier.merge(announced.values.map { Classifier.classify(it, probes[it.key] ?: Probe.Pending, pairings) })
    }
}
