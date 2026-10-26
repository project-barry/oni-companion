package io.github.projectbarry.onicompanion.store

import io.github.projectbarry.onicompanion.net.ApiJson
import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.net.PinnedConnection
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import java.io.File

/** One paired gaming device. The fingerprint is the identity; the token works only for this one. */
@Serializable
data class Pairing(
    val instanceId: String,
    val name: String,
    val fingerprint: String,
    val hosts: List<String>,
    val port: Int,
    val deviceToken: String,
    val deviceId: String,
    val pairedAt: String,
) {
    val tag get() = Fingerprint.tag(fingerprint)
    val title get() = "$name · $tag"
    fun connection() = PinnedConnection(hosts, port, fingerprint, deviceToken)
}

/**
 * Pairings kept in one file, encrypted by [box] (Android Keystore on the phone). Written to a temp
 * file and renamed. If the file cannot be decrypted (key lost), it is treated as empty and the
 * user pairs again; nothing is guessed.
 */
class PairingStore(private val file: File, private val box: SecretBox) {
    private val ser = ListSerializer(Pairing.serializer())
    private var cache: List<Pairing>? = null

    @Synchronized fun all(): List<Pairing> {
        cache?.let { return it }
        val list = try {
            if (!file.exists()) emptyList()
            else ApiJson.decodeFromString(ser, String(box.decrypt(file.readBytes()), Charsets.UTF_8))
        } catch (e: Exception) { emptyList() }
        cache = list
        return list
    }

    @Synchronized fun byFingerprint(fp: String) = all().firstOrNull { Fingerprint.same(it.fingerprint, fp) }
    @Synchronized fun byInstanceId(id: String) = all().firstOrNull { it.instanceId == id }

    /** Adds a pairing, replacing one with the same fingerprint (a re-pair). */
    @Synchronized fun put(p: Pairing) = save(all().filterNot { Fingerprint.same(it.fingerprint, p.fingerprint) } + p)

    /** Forget a pairing on this phone (the gaming device's list is separate). */
    @Synchronized fun remove(fingerprint: String) = save(all().filterNot { Fingerprint.same(it.fingerprint, fingerprint) })

    /** Update the stored addresses of a pairing found again at a new address. */
    @Synchronized fun updateAddress(fingerprint: String, host: String, port: Int) {
        val p = byFingerprint(fingerprint) ?: return
        if (p.hosts.firstOrNull() == host && p.port == port) return
        put(p.copy(hosts = listOf(host) + p.hosts.filter { it != host }.take(5), port = port))
    }

    private fun save(list: List<Pairing>) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeBytes(box.encrypt(ApiJson.encodeToString(ser, list).toByteArray(Charsets.UTF_8)))
        if (!tmp.renameTo(file)) { file.delete(); check(tmp.renameTo(file)) { "could not save pairings" } }
        cache = list
    }
}
