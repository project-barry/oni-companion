package io.github.projectbarry.onicompanion.discovery

import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.store.Pairing

/** What mDNS said about a service. Every field is a label anyone could announce; none is trusted. */
data class Announced(
    val key: String,          // NSD service name, for lost events
    val instanceId: String,
    val name: String,
    val apiVersion: String,
    val coreVersion: String,
    val host: String,
    val port: Int,
)

/** What a TLS connection to the announced address showed. */
sealed interface Probe {
    data object Pending : Probe
    data object Unreachable : Probe
    data class Seen(val fingerprint: String) : Probe
}

enum class Trust { Checking, Paired, New, CantVerify, Unreachable }

data class Entry(
    val announced: Announced,
    val trust: Trust,
    val fingerprint: String?,
    /** "spiffy-raccoon · 7F3A" (the tag comes from the certificate we saw, never from the announcement). */
    val title: String,
    val pairing: Pairing?,
    val needsUpdate: Boolean,
)

object Classifier {
    /**
     * Paired: the certificate fingerprint matches a stored pairing (also when the address changed).
     * CantVerify: a known instance id is announced by a service whose certificate is a different one.
     * New: a certificate we have no pairing for. A service with the same name and id but another key
     * stays a separate entry because the fingerprints differ.
     */
    fun classify(a: Announced, probe: Probe, pairings: List<Pairing>): Entry {
        val update = (a.apiVersion.toIntOrNull() ?: 1) > 1
        return when (probe) {
            Probe.Pending -> Entry(a, Trust.Checking, null, "${a.name} · ····", null, update)
            Probe.Unreachable -> Entry(a, Trust.Unreachable, null, "${a.name} · ····", null, update)
            is Probe.Seen -> {
                val tag = Fingerprint.tag(probe.fingerprint)
                val paired = pairings.firstOrNull { Fingerprint.same(it.fingerprint, probe.fingerprint) }
                when {
                    paired != null -> Entry(a, Trust.Paired, probe.fingerprint, "${paired.name} · $tag", paired, update)
                    pairings.any { it.instanceId == a.instanceId } ->
                        Entry(a, Trust.CantVerify, probe.fingerprint, "${a.name} · $tag", null, update)
                    else -> Entry(a, Trust.New, probe.fingerprint, "${a.name} · $tag", null, update)
                }
            }
        }
    }

    /** One list row per real service: the same certificate seen at several addresses is shown once. */
    fun merge(entries: List<Entry>): List<Entry> {
        val seen = HashSet<String>()
        return entries.filter { e -> e.fingerprint == null || seen.add(e.fingerprint + "/" + e.trust) }
    }
}
