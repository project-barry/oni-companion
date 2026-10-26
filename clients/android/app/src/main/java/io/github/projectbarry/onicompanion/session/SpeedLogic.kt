package io.github.projectbarry.onicompanion.session

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

data class GameState(val state: String, val label: String, val tone: String)

data class Pending(val state: String?, val speed: Int?)

/** GET /controls (api.schema.json Controls). */
data class Controls(
    val available: Boolean,
    val paused: Boolean?,
    val speed: Int?,
    val pending: Pending?,
    val game: GameState?,
) {
    companion object {
        fun parse(o: JsonObject): Controls {
            fun p(k: String, from: JsonObject = o) = from[k] as? JsonPrimitive
            val pend = (o["pending"] as? JsonObject)?.let { Pending(p("state", it)?.contentOrNull, p("speed", it)?.contentOrNull?.toIntOrNull()) }
            val g = (o["game"] as? JsonObject)?.let {
                GameState(p("state", it)?.contentOrNull ?: "", p("label", it)?.contentOrNull ?: "", p("tone", it)?.contentOrNull ?: "neutral")
            }
            return Controls(p("available")?.booleanOrNull == true, p("paused")?.booleanOrNull, p("speed")?.contentOrNull?.toIntOrNull(), pend, g)
        }
    }
}

/**
 * The speed bar's decisions, ported from Barry's main.qml. Pause and the speeds highlight on their own like the
 * game: Pause while paused, the selected speed always. A pressed button shows at once ([pendingBtn]) and then
 * follows the real state.
 */
object SpeedLogic {
    fun paused(c: Controls?, pendingBtn: String): Boolean {
        if (pendingBtn == "pause") return !(c?.paused == true)     // a toggle: the opposite of the state it was pressed in
        if (c == null || !c.available) return false
        val p = c.pending
        if (p != null && p.state != null && p.state != "speed") return p.state == "pause"
        return c.paused == true
    }

    fun selected(c: Controls?, pendingBtn: String): Int {
        if (pendingBtn.startsWith("speed")) return pendingBtn.removePrefix("speed").toIntOrNull() ?: 0
        if (c == null || !c.available) return 0
        c.pending?.speed?.let { if (it > 0) return it }
        return c.speed ?: 0
    }

    /** The body of POST /controls for a pressed button ("pause", "speed1".."speed3"). */
    fun body(c: Controls, key: String): JsonObject =
        if (key == "pause") JsonObject(mapOf("state" to JsonPrimitive(if (c.paused == true) "play" else "pause")))
        else JsonObject(mapOf("state" to JsonPrimitive("speed"), "speed" to JsonPrimitive(key.removePrefix("speed").toInt())))
}
