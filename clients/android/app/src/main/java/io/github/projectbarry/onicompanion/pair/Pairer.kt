package io.github.projectbarry.onicompanion.pair

import io.github.projectbarry.onicompanion.net.ApiClient
import io.github.projectbarry.onicompanion.net.ApiException
import io.github.projectbarry.onicompanion.net.ApiJson
import io.github.projectbarry.onicompanion.net.ClaimPost
import io.github.projectbarry.onicompanion.net.ClaimReply
import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.net.PinMismatchException
import io.github.projectbarry.onicompanion.net.PinnedConnection
import io.github.projectbarry.onicompanion.net.UnreachableException
import io.github.projectbarry.onicompanion.store.Pairing
import io.github.projectbarry.onicompanion.store.PairingStore
import okhttp3.OkHttpClient
import java.time.Instant

sealed interface PairOutcome {
    data class Paired(val pairing: Pairing) : PairOutcome
    data class Failed(val message: String, val cantVerify: Boolean = false) : PairOutcome
}

/**
 * Claims a one-time code from the service whose certificate fingerprint [fingerprint] was pinned
 * (from the QR code, or probed and confirmed by the user). The code is sent only inside TLS to that
 * certificate; the returned device token is stored per service.
 */
class Pairer(private val store: PairingStore, private val clientFor: ((String) -> OkHttpClient)? = null) {

    suspend fun claim(hosts: List<String>, port: Int, fingerprint: String, instanceId: String?, code: String, label: String): PairOutcome {
        val fp = fingerprint.lowercase()
        val conn = PinnedConnection(hosts, port, fp, null)
        val api = ApiClient(conn, clientFor?.invoke(fp))
        val body = ApiJson.encodeToJsonElement(ClaimPost.serializer(), ClaimPost(code.trim(), label.take(40)))
        val reply: ClaimReply = try {
            ApiJson.decodeFromJsonElement(ClaimReply.serializer(), api.post("/connect/claim", body))
        } catch (e: PinMismatchException) {
            return PairOutcome.Failed("Can't verify this device. Nothing was sent.", cantVerify = true)
        } catch (e: ApiException) {
            return PairOutcome.Failed(when (e.code) {
                "bad_code" -> "That code is wrong, expired or already used. Check the Connect a phone window."
                "rate_limited" -> "Too many tries. Wait a minute and try again."
                else -> e.message ?: "Pairing failed"
            })
        } catch (e: UnreachableException) {
            return PairOutcome.Failed("Can't reach the gaming device. Is Connect a phone on?")
        } catch (e: Exception) {
            return PairOutcome.Failed("The gaming device sent an answer this app does not understand.")
        }
        // The pinned TLS session already proved the key; the body is a label and must agree.
        if (!Fingerprint.same(reply.identity.fingerprint, fp)) {
            return PairOutcome.Failed("Can't verify this device.", cantVerify = true)
        }
        if (instanceId != null && instanceId != reply.identity.instanceId) {
            // Labels differ but the certificate matched: keep the service's own id.
        }
        val p = Pairing(
            instanceId = reply.identity.instanceId, name = reply.identity.name, fingerprint = fp,
            hosts = hosts, port = port, deviceToken = reply.deviceToken, deviceId = reply.deviceId,
            pairedAt = Instant.now().toString(),
        )
        store.put(p)
        return PairOutcome.Paired(p)
    }
}
