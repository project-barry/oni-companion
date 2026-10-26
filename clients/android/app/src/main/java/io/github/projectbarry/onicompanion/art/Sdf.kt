package io.github.projectbarry.onicompanion.art

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.util.LruCache
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlin.math.ceil
import kotlin.math.floor

class SdfGlyph(val x: Int, val y: Int, val w: Int, val h: Int, val bearingX: Float, val bearingY: Float, val advance: Float)

/**
 * The game's Graystroke font as a signed-distance atlas (font-atlas.schema.json), read from the user's own
 * game at run time. [dist] holds the distance channel, one byte per atlas pixel.
 */
class SdfAtlas(
    val width: Int, val height: Int, val pad: Int, val spread: Float, val pointSize: Float,
    val ascent: Float, val descent: Float,
    val glyphs: Map<Int, SdfGlyph>, val kerning: Map<Long, Float>, val dist: ByteArray,
) {
    companion object {
        /** Builds the atlas from the table JSON and the decoded texture pixels (ARGB ints). */
        fun from(table: JsonObject, pixels: IntArray, texW: Int, texH: Int): SdfAtlas? {
            val a = table["atlas"] as? JsonObject ?: return null
            val face = table["face"] as? JsonObject ?: return null
            fun n(o: JsonObject, k: String) = (o[k] as? JsonPrimitive)?.contentOrNull?.toFloatOrNull()
            val red = (a["encoding"] as? JsonPrimitive)?.contentOrNull == "sdf-red"
            val dist = ByteArray(texW * texH) { i -> (if (red) (pixels[i] shr 16) and 0xFF else (pixels[i] ushr 24)).toByte() }
            val glyphs = HashMap<Int, SdfGlyph>()
            for (g in (table["glyphs"] as? JsonArray).orEmpty()) {
                val go = g as? JsonObject ?: continue
                val u = n(go, "unicode")?.toInt() ?: continue
                glyphs[u] = SdfGlyph(
                    n(go, "x")?.toInt() ?: 0, n(go, "y")?.toInt() ?: 0, n(go, "w")?.toInt() ?: 0, n(go, "h")?.toInt() ?: 0,
                    n(go, "bearingX") ?: 0f, n(go, "bearingY") ?: 0f, n(go, "advance") ?: 0f,
                )
            }
            val kern = HashMap<Long, Float>()
            for (k in (table["kerning"] as? JsonArray).orEmpty()) {
                val ko = k as? JsonObject ?: continue
                val f = n(ko, "first")?.toLong() ?: continue
                val s = n(ko, "second")?.toLong() ?: continue
                kern[f * 1048576L + s] = n(ko, "x") ?: 0f
            }
            return SdfAtlas(
                texW, texH, n(a, "padding")?.toInt() ?: 0, n(a, "spread") ?: 1f, n(a, "pointSize") ?: 1f,
                n(face, "ascent") ?: 0f, n(face, "descent") ?: 0f, glyphs, kern, dist,
            )
        }
    }
}

/** A line of header text drawn from the atlas, as a white-on-transparent mask: tint it with the wanted color. */
class SdfRendered(val bitmap: Bitmap, val widthPx: Int, val heightPx: Int)

/**
 * Draws header text from an [SdfAtlas] on the CPU: each pixel of each glyph samples the distance field and is
 * anti-aliased over exactly one screen pixel (the same formula as Barry's shader). A character the atlas has no
 * glyph for is drawn with [fallback], run by run, so a missing glyph never breaks the line.
 */
class SdfText(private val atlas: SdfAtlas, private val fallback: Typeface) {
    private val cache = LruCache<String, SdfRendered>(64)

    private class Seg(val glyph: SdfGlyph?, val text: String, val x: Float, val width: Float)

    private fun layout(text: String, k: Float, letterSpacing: Float, paint: Paint): Pair<List<Seg>, Float> {
        val out = ArrayList<Seg>()
        var x = 0f
        var prev = -1
        val fbRun = StringBuilder()
        var fbStart = 0f
        fun flushFallback() {
            if (fbRun.isEmpty()) return
            val w = paint.measureText(fbRun.toString())
            out.add(Seg(null, fbRun.toString(), fbStart, w))
            x = fbStart + w
            fbRun.clear()
        }
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            i += Character.charCount(cp)
            val g = atlas.glyphs[cp]
            if (g == null) {
                if (fbRun.isEmpty()) fbStart = x
                fbRun.appendCodePoint(cp)
                prev = -1
                continue
            }
            flushFallback()
            if (prev >= 0) x += (atlas.kerning[prev * 1048576L + cp] ?: 0f) * k
            out.add(Seg(g, "", x, g.advance * k))
            x += g.advance * k + letterSpacing
            prev = cp
        }
        flushFallback()
        return out to x
    }

    private fun fbPaint(pxSize: Float) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = fallback; textSize = pxSize; color = 0xFFFFFFFF.toInt()
    }

    /** Natural width in px of [text] at [pxSize] (the em size the atlas is scaled to). */
    fun measure(text: String, pxSize: Float, letterSpacing: Float = 0f): Float =
        layout(text, pxSize / atlas.pointSize, letterSpacing, fbPaint(pxSize)).second

    fun render(text: String, pxSize: Float, letterSpacing: Float = 0f): SdfRendered? {
        if (text.isEmpty()) return null
        val key = "$text|$pxSize|$letterSpacing"
        cache.get(key)?.let { return it }
        val k = pxSize / atlas.pointSize
        val paint = fbPaint(pxSize)
        val (segs, total) = layout(text, k, letterSpacing, paint)
        val w = ceil(total).toInt().coerceAtLeast(1)
        val h = ceil((atlas.ascent - atlas.descent) * k).toInt().coerceAtLeast(1)
        if (w > 4096) return null
        val alpha = IntArray(w * h)
        val base = atlas.ascent * k
        val pad = atlas.pad
        for (s in segs) {
            val g = s.glyph ?: continue
            if (g.w <= 0 || g.h <= 0) continue
            val dx = s.x + (g.bearingX - pad) * k
            val dy = base - (g.bearingY + pad) * k
            val dw = (g.w + 2 * pad) * k
            val dh = (g.h + 2 * pad) * k
            val x0 = floor(dx).toInt().coerceAtLeast(0)
            val x1 = ceil(dx + dw).toInt().coerceAtMost(w)
            val y0 = floor(dy).toInt().coerceAtLeast(0)
            val y1 = ceil(dy + dh).toInt().coerceAtMost(h)
            for (py in y0 until y1) {
                val ay = (g.y - pad) + (py + 0.5f - dy) / k
                for (px in x0 until x1) {
                    val ax = (g.x - pad) + (px + 0.5f - dx) / k
                    val t = sample(ax, ay)
                    val a = ((t - 0.5f) * atlas.spread * k + 0.5f).coerceIn(0f, 1f)
                    val v = (a * 255f + 0.5f).toInt()
                    val cur = alpha[py * w + px] ushr 24
                    if (v > cur) alpha[py * w + px] = v shl 24
                }
            }
        }
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        for (i in alpha.indices) { val a = alpha[i] ushr 24; alpha[i] = (a shl 24) or 0xFFFFFF }
        bmp.setPixels(alpha, 0, w, 0, 0, w, h)
        if (segs.any { it.glyph == null }) {
            val c = Canvas(bmp)
            for (s in segs) if (s.glyph == null) c.drawText(s.text, s.x, base, paint)
        }
        val r = SdfRendered(bmp, w, h)
        cache.put(key, r)
        return r
    }

    /** Bilinear sample of the distance channel at atlas pixel coordinates (centre of texel = +0.5). */
    private fun sample(ax: Float, ay: Float): Float {
        val fx = ax - 0.5f
        val fy = ay - 0.5f
        val x0 = floor(fx).toInt()
        val y0 = floor(fy).toInt()
        val tx = fx - x0
        val ty = fy - y0
        fun at(x: Int, y: Int): Float {
            val cx = x.coerceIn(0, atlas.width - 1)
            val cy = y.coerceIn(0, atlas.height - 1)
            return (atlas.dist[cy * atlas.width + cx].toInt() and 0xFF) / 255f
        }
        val top = at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx
        val bot = at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx
        return top * (1 - ty) + bot * ty
    }
}
