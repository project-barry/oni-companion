package io.github.projectbarry.onicompanion.art

import android.graphics.BitmapFactory
import android.graphics.Typeface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import io.github.projectbarry.onicompanion.net.ApiClient
import io.github.projectbarry.onicompanion.theme.FontRole
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.io.File

data class FontEntry(val name: String, val family: String, val style: String, val kind: String, val url: String, val size: Long)

/**
 * The game's fonts, read from the user's own game by the core (GET /fonts) and loaded here at run time.
 * Nothing is bundled. Every role has a fallback: with no fonts, or one that fails to load, the system font stays.
 *  - body: a font family from the game's TTF/OTF files, else the system sans.
 *  - header: the Graystroke SDF atlas ([SdfText]), else the first fallback family the game provides
 *    (Economica), else the body font, bold.
 */
class FontRepo(private val api: ApiClient, private val dir: File) {
    var body: FontFamily? by mutableStateOf(null); private set
    var headerFallback: FontFamily? by mutableStateOf(null); private set
    var headerTypeface: Typeface by mutableStateOf(Typeface.DEFAULT_BOLD); private set
    var atlas: SdfText? by mutableStateOf(null); private set

    private var entries: List<FontEntry> = emptyList()
    private var atlasKey = ""
    private var fileKey = ""

    /** Re-reads the font list and loads what is new. [roles] come from GET /theme (font.roles). */
    suspend fun refresh(roles: Map<String, FontRole>) {
        val list = runCatching { parseList(api.get("/fonts")) }.getOrNull() ?: return
        entries = list
        loadFamilies(roles)
        loadAtlas(roles)
    }

    /** Applies new roles (a theme change) to the fonts already listed. */
    suspend fun rolesChanged(roles: Map<String, FontRole>) {
        if (entries.isEmpty()) return
        loadFamilies(roles)
        loadAtlas(roles)
    }

    private suspend fun fileOf(e: FontEntry): File? {
        val f = File(dir, "${e.size}-${e.name}")
        if (f.isFile && f.length() > 0) return f
        val bytes = runCatching { api.bytes(e.url) }.getOrNull() ?: return null
        return withContext(Dispatchers.IO) { runCatching { dir.mkdirs(); f.writeBytes(bytes); f }.getOrNull() }
    }

    private fun weightOf(style: String) = if (style.contains("bold", true)) FontWeight.Bold else FontWeight.Normal
    private fun styleOf(style: String) = if (style.contains("italic", true)) FontStyle.Italic else FontStyle.Normal

    private suspend fun familyOf(family: String): FontFamily? {
        val fonts = ArrayList<Font>()
        for (e in entries) {
            if (e.kind != "ttf" || !e.family.equals(family, true)) continue
            val f = fileOf(e) ?: continue
            if (runCatching { Typeface.createFromFile(f) }.isFailure) continue
            fonts.add(Font(f, weightOf(e.style), styleOf(e.style)))
        }
        return if (fonts.isEmpty()) null else FontFamily(fonts)
    }

    private suspend fun loadFamilies(roles: Map<String, FontRole>) {
        val bodyRole = roles["body"]
        val bodyEntry = bodyRole?.font?.let { n -> entries.firstOrNull { it.name == n && it.kind == "ttf" } }
        val key = entries.joinToString("|") { "${it.name}:${it.size}" } + "#" + bodyEntry?.family + "#" + roles["header"]?.fallback
        if (key == fileKey) return
        fileKey = key
        body = bodyEntry?.let { familyOf(it.family) }
        var hf: FontFamily? = null
        for (fam in roles["header"]?.fallback.orEmpty()) {
            hf = familyOf(fam)
            if (hf != null) break
        }
        headerFallback = hf
        // the typeface used for atlas fallback runs: Economica Bold when the game has it
        val fbEntry = roles["header"]?.fallback.orEmpty().firstNotNullOfOrNull { fam ->
            entries.firstOrNull { it.kind == "ttf" && it.family.equals(fam, true) && it.style.contains("bold", true) && !it.style.contains("italic", true) }
        }
        headerTypeface = fbEntry?.let { fileOf(it) }?.let { runCatching { Typeface.createFromFile(it) }.getOrNull() } ?: Typeface.DEFAULT_BOLD
        if (atlas != null) atlasKey = ""      // the fallback typeface changed: rebuild the renderer
    }

    private suspend fun loadAtlas(roles: Map<String, FontRole>) {
        val role = roles["header"]
        val tbl = role?.font?.let { n -> entries.firstOrNull { it.name == n && it.kind == "sdfAtlasTable" } }
        val img = tbl?.let { t -> entries.firstOrNull { it.kind == "sdfAtlasImage" && it.family == t.family } }
        if (tbl == null || img == null) { atlas = null; atlasKey = ""; return }
        val key = "${tbl.url}:${tbl.size}:${img.size}:${headerTypeface.hashCode()}"
        if (key == atlasKey) return
        val table = runCatching { api.get(tbl.url.removePrefix("/api/v1")) }.getOrNull() ?: return
        val png = runCatching { api.bytes(img.url) }.getOrNull() ?: return
        val built = withContext(Dispatchers.Default) {
            val opts = BitmapFactory.Options().apply { inPremultiplied = false }
            val bmp = BitmapFactory.decodeByteArray(png, 0, png.size, opts) ?: return@withContext null
            val px = IntArray(bmp.width * bmp.height)
            bmp.getPixels(px, 0, bmp.width, 0, 0, bmp.width, bmp.height)
            SdfAtlas.from(table, px, bmp.width, bmp.height)
        } ?: return
        atlasKey = key
        atlas = SdfText(built, headerTypeface)
    }

    companion object {
        fun parseList(o: JsonObject): List<FontEntry> = (o["fonts"] as? JsonArray).orEmpty().mapNotNull { e ->
            val f = e as? JsonObject ?: return@mapNotNull null
            fun s(k: String) = (f[k] as? JsonPrimitive)?.contentOrNull
            FontEntry(s("name") ?: return@mapNotNull null, s("family") ?: "", s("style") ?: "regular", s("kind") ?: "",
                s("url") ?: return@mapNotNull null, s("size")?.toLongOrNull() ?: 0)
        }
    }
}
