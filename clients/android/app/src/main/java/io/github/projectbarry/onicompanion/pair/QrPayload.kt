package io.github.projectbarry.onicompanion.pair

import io.github.projectbarry.onicompanion.net.ApiJson
import io.github.projectbarry.onicompanion.net.Fingerprint
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant

/** The text in the pairing QR code (pairing.schema.json QrPayload). */
data class QrPayload(
    val addresses: List<String>,
    val port: Int,
    val code: String,
    val instanceId: String,
    val fingerprint: String,
    val name: String,
    val expires: Instant?,
) {
    fun isExpired(now: Instant = Instant.now()) = expires != null && now.isAfter(expires)
}

sealed interface QrResult {
    data class Ok(val payload: QrPayload) : QrResult
    /** Some other QR code. */
    data object NotOurs : QrResult
    /** Payload version above what this app knows. */
    data object UpdateApp : QrResult
    data class Bad(val why: String) : QrResult
}

object QrParser {
    private val CODE = Regex("^[A-HJKMNP-Z2-9]{8}$")
    private val NAME = Regex("^[a-z]{2,20}-[a-z]{2,20}$")

    fun parse(text: String): QrResult {
        if (text.length > 600) return QrResult.NotOurs
        val o: JsonObject = try { ApiJson.parseToJsonElement(text).jsonObject } catch (e: Exception) { return QrResult.NotOurs }
        if (o["t"]?.jsonPrimitive?.contentOrNullSafe() != "onic-pair") return QrResult.NotOurs
        val v = try { o["v"]!!.jsonPrimitive.int } catch (e: Exception) { return QrResult.Bad("no version") }
        if (v > 1) return QrResult.UpdateApp
        if (v < 1) return QrResult.Bad("bad version")
        return try {
            val addrs = o["a"]!!.jsonArray.map { it.jsonPrimitive.content }
            val port = o["p"]!!.jsonPrimitive.int
            val code = o["c"]!!.jsonPrimitive.content.uppercase()
            val fp = o["f"]!!.jsonPrimitive.content.lowercase()
            val name = o["n"]!!.jsonPrimitive.content
            val id = o["i"]!!.jsonPrimitive.content
            val x = o["x"]?.jsonPrimitive?.content?.let { runCatching { Instant.parse(it) }.getOrNull() }
            when {
                addrs.isEmpty() || addrs.size > 6 || addrs.any { it.isBlank() || it.length > 80 || it.any { c -> c.isWhitespace() || c == '/' } } ->
                    QrResult.Bad("bad address")
                port !in 1024..65535 -> QrResult.Bad("bad port")
                !CODE.matches(code) -> QrResult.Bad("bad code")
                !Fingerprint.isValid(fp) -> QrResult.Bad("bad fingerprint")
                id.isBlank() || id.length > 64 -> QrResult.Bad("bad id")
                else -> QrResult.Ok(QrPayload(addrs, port, code, id, fp, if (NAME.matches(name)) name else "unknown-device", x))
            }
        } catch (e: Exception) {
            QrResult.Bad("incomplete")
        }
    }

    private fun kotlinx.serialization.json.JsonPrimitive.contentOrNullSafe() = if (isString) content else null
}
