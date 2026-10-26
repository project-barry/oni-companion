package io.github.projectbarry.onicompanion.local

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant

/** Is the mod writing right now? Same rule as the core (colony.live_fresh): 15 s, or 180 s while the game is paused. */
object LocalFresh {
    const val FRESH_SECONDS = 15L
    const val FRESH_PAUSED_SECONDS = 180L

    fun fresh(liveJson: ByteArray?, nowMs: Long): Boolean {
        if (liveJson == null) return false
        return try {
            val o = Json.parseToJsonElement(liveJson.decodeToString()).jsonObject
            if (o["state"]?.jsonPrimitive?.contentOrNull != "running") return false
            val at = Instant.parse(o["writtenAt"]?.jsonPrimitive?.contentOrNull ?: return false).toEpochMilli()
            val paused = o["paused"]?.jsonPrimitive?.boolean == true
            nowMs - at <= (if (paused) FRESH_PAUSED_SECONDS else FRESH_SECONDS) * 1000
        } catch (e: Exception) { false }
    }

    fun isMarker(json: ByteArray?): Boolean {
        if (json == null) return false
        return try {
            val o = Json.parseToJsonElement(json.decodeToString()).jsonObject
            o["schema"]?.jsonPrimitive?.contentOrNull == "1" && o["app"]?.jsonPrimitive?.contentOrNull == "oni-companion"
        } catch (e: Exception) { false }
    }
}
