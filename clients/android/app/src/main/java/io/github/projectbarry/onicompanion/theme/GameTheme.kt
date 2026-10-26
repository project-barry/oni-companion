package io.github.projectbarry.onicompanion.theme

import androidx.compose.ui.graphics.Color
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

data class Insets(val left: Int, val top: Int, val right: Int, val bottom: Int)
data class Slice(val name: String, val art: String, val width: Int, val height: Int, val insets: Insets)
data class Icon(val name: String, val art: String, val activeArt: String?, val width: Int, val height: Int)
data class FontRole(val family: String, val font: String?, val fallback: List<String>)

/**
 * The look of the app: the built-in dark theme until GET /theme answers, then the game's colors, 9-slice
 * images and icons (theme.schema.json). Tokens the core leaves out keep the built-in value, like Barry's Theme.qml.
 */
data class GameTheme(
    val game: Boolean = false,
    val bg: Color = Color(0xFF0E1218),
    val panel: Color = Color(0xFF18202A),
    val panelHi: Color = Color(0xFF222C39),
    val header: Color = Color(0xFF18202A),
    val line: Color = Color(0xFF2C3846),
    val text: Color = Color(0xFFEEF0F4),
    val title: Color = Color(0xFFEEF0F4),
    val muted: Color = Color(0xFF9AA4B5),
    val accent: Color = Color(0xFF5AA9FF),
    val good: Color = Color(0xFF4CC38A),
    val warn: Color = Color(0xFFE8B44A),
    val bad: Color = Color(0xFFEF5B5B),
    val buttonNormal: Color = Color(0xFF18202A),
    val buttonHover: Color = Color(0xFF222C39),
    val buttonPressed: Color = Color(0xFF222C39),
    val progressFill: Color = Color(0xFF5AA9FF),
    val progressTrack: Color = Color(0xFF2C3846),
    val meterStress: Color = Color(0xFFE8B44A),
    val meterHealth: Color = Color(0xFFEF5B5B),
    val meterCalories: Color = Color(0xFF5AA9FF),
    val sectionHeader: Color = Color(0xFF222C39),
    val sectionHeaderText: Color = Color(0xFFEEF0F4),
    val tabBg: Color = Color(0xFF18202A),
    val tabActiveBg: Color = Color(0xFF18202A),
    val tabText: Color = Color(0xFF9AA4B5),
    val tabTextActive: Color = Color(0xFFEEF0F4),
    val alertBg: Color = Color(0xFF18202A),
    val alertText: Color = Color(0xFFEEF0F4),
    val alertBadBg: Color = Color(0xFF18202A),
    val alertBadText: Color = Color(0xFFEF5B5B),
    val slices: Map<String, Slice> = emptyMap(),
    val icons: Map<String, Icon> = emptyMap(),
    val roles: Map<String, FontRole> = emptyMap(),
) {
    /** Text drawn straight on the page background: the title color in a game theme (white on the dark page). */
    val pageText get() = if (game) title else text
    /** Text on the game's dark slate buttons. */
    val buttonText get() = if (game) title else text
    /** The game's panels are nearly square; the built-in look is rounded. */
    val radiusUnits get() = if (game) 4 else 20

    fun slice(name: String): Slice? = slices[name]
    fun icon(name: String): Icon? = icons[name]

    /** A span's `color` (blocks.schema.json ColorToken). null: the caller's own color. */
    fun token(name: String?): Color? = when (name) {
        "text" -> text
        "textDim" -> muted
        "textTitle" -> title
        "positive" -> good
        "negative" -> bad
        "warning" -> warn
        "info" -> accent
        "alertText" -> alertText
        "alertBadText" -> alertBadText
        else -> null
    }

    fun tone(name: String?): Color = when (name) {
        "good" -> good
        "warn" -> warn
        "bad" -> bad
        "info" -> accent
        else -> muted
    }

    fun level(name: String?): Color = when (name) {
        "danger" -> bad
        "warn" -> warn
        else -> accent
    }

    /** Tone color for a value; neutral stays the normal text color. */
    fun valueTone(name: String?): Color = if (!name.isNullOrEmpty() && name != "neutral") tone(name) else text

    /** A warn or bad tone always shows as such; otherwise the game's own meter color for stress, health, calories. */
    fun meterColor(label: String, toneName: String?): Color {
        if (toneName == "warn" || toneName == "bad") return tone(toneName)
        if (game) {
            return when (label.lowercase()) {
                "stress" -> meterStress
                "health" -> meterHealth
                "calories" -> meterCalories
                else -> progressFill
            }
        }
        return if (toneName == "good") good else accent
    }

    fun stateColor(state: String?): Color = when (state) {
        "solid" -> Color(0xFF8B7355)
        "liquid" -> Color(0xFF3F7FD0)
        "gas" -> Color(0xFF7FCFD8)
        else -> Color(0xFF3A3F4A)
    }

    fun conduitColor(c: String?): Color = when (c) {
        "gas" -> Color(0xFF7FCFD8)
        "liquid" -> Color(0xFF3F7FD0)
        "solid" -> Color(0xFFA08A68)
        "power" -> Color(0xFFE8B44A)
        "logic" -> Color(0xFF4CC38A)
        else -> muted
    }

    companion object {
        /** #RRGGBB or #RRGGBBAA as the contract writes it (Android's own parser reads 8 digits as #AARRGGBB). */
        fun color(h: String?): Color? {
            if (h == null || h.length !in intArrayOf(7, 9) || h[0] != '#') return null
            return try {
                val r = h.substring(1, 3).toInt(16)
                val g = h.substring(3, 5).toInt(16)
                val b = h.substring(5, 7).toInt(16)
                val a = if (h.length == 9) h.substring(7, 9).toInt(16) else 255
                Color(r, g, b, a)
            } catch (e: NumberFormatException) { null }
        }

        /** Reads the GET /theme reply on top of [base]. Unknown or missing tokens keep the base value. */
        fun fromJson(o: JsonObject, base: GameTheme = GameTheme()): GameTheme {
            val c = o["colors"] as? JsonObject ?: return base
            fun col(k: String) = color((c[k] as? JsonPrimitive)?.contentOrNull)
            val hover = col("buttonHover")
            val slices = (o["slices"] as? JsonArray).orEmpty().mapNotNull { e ->
                val s = e as? JsonObject ?: return@mapNotNull null
                val ins = s["insets"] as? JsonObject ?: return@mapNotNull null
                val name = s.s("name") ?: return@mapNotNull null
                Slice(name, s.s("art") ?: return@mapNotNull null, s.i("width") ?: 1, s.i("height") ?: 1,
                    Insets(ins.i("left") ?: 0, ins.i("top") ?: 0, ins.i("right") ?: 0, ins.i("bottom") ?: 0))
            }.associateBy { it.name }
            val icons = (o["icons"] as? JsonArray).orEmpty().mapNotNull { e ->
                val s = e as? JsonObject ?: return@mapNotNull null
                val name = s.s("name") ?: return@mapNotNull null
                Icon(name, s.s("art") ?: return@mapNotNull null, s.s("activeArt"), s.i("width") ?: 1, s.i("height") ?: 1)
            }.associateBy { it.name }
            val roles = ((o["font"] as? JsonObject)?.get("roles") as? JsonObject)?.let { r ->
                r.entries.mapNotNull { (k, v) ->
                    val ro = v as? JsonObject ?: return@mapNotNull null
                    k to FontRole(ro.s("family") ?: "", ro.s("font"),
                        (ro["fallback"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull })
                }.toMap()
            }.orEmpty()
            return base.copy(
                game = o.s("source") == "game",
                bg = col("background") ?: base.bg, panel = col("panel") ?: base.panel,
                header = col("header") ?: base.header, line = col("border") ?: base.line,
                text = col("text") ?: base.text, title = col("textTitle") ?: base.title,
                muted = col("textDim") ?: base.muted, accent = col("info") ?: base.accent,
                good = col("positive") ?: base.good, bad = col("negative") ?: base.bad, warn = col("warning") ?: base.warn,
                buttonNormal = col("buttonNormal") ?: base.buttonNormal, buttonHover = hover ?: base.buttonHover,
                panelHi = hover ?: base.panelHi,
                buttonPressed = col("buttonPressed") ?: base.buttonPressed,
                progressFill = col("progressFill") ?: base.progressFill, progressTrack = col("progressTrack") ?: base.progressTrack,
                meterStress = col("meterStress") ?: base.meterStress, meterHealth = col("meterHealth") ?: base.meterHealth,
                meterCalories = col("meterCalories") ?: base.meterCalories,
                sectionHeader = col("sectionHeader") ?: base.sectionHeader,
                sectionHeaderText = col("sectionHeaderText") ?: base.sectionHeaderText,
                tabBg = col("tabBg") ?: base.tabBg, tabActiveBg = col("tabActiveBg") ?: base.tabActiveBg,
                tabText = col("tabText") ?: base.tabText, tabTextActive = col("tabTextActive") ?: base.tabTextActive,
                alertBg = col("alertBg") ?: base.alertBg, alertText = col("alertText") ?: base.alertText,
                alertBadBg = col("alertBadBg") ?: base.alertBadBg, alertBadText = col("alertBadText") ?: base.alertBadText,
                slices = slices, icons = icons, roles = roles,
            )
        }

        private fun JsonObject.s(k: String) = (this[k] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
        private fun JsonObject.i(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull?.toIntOrNull()
    }
}
