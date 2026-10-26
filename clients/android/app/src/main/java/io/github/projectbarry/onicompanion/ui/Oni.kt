package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.projectbarry.onicompanion.session.OniSession
import io.github.projectbarry.onicompanion.session.PageController
import io.github.projectbarry.onicompanion.theme.GameTheme
import io.github.projectbarry.onicompanion.theme.Slice
import kotlinx.coroutines.CancellationException
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * The drawing primitives of the service view, ported from Barry's qml/ (Theme, Tap, Btn, Pill, Skin, Art, SectionBar,
 * HeaderText, ProgressBar, NavRow, SearchField). Sizes keep Barry's numbers: one Barry pixel is [SCALE] dp.
 * Nothing here decides anything: wording, tones and state come from the core through [OniSession].
 */
val SCALE: Float get() = Fit.scale

/**
 * How big one Barry pixel is in this window, set by [Fit.window] before the service view composes (RootScreen keys
 * the view on the window size, so a rotation or resize redraws everything with the new numbers).
 * - [scale]: 0.53 dp on a ~411 dp phone (the size the view was tuned at), growing slowly to 0.66 on tablets. It follows
 *   the window's short side (height counts x1.1), so a phone on its side keeps phone-sized text.
 * - [narrow]: a phone in portrait (< 600 dp wide): tighter gutters and paddings so the content gets the width.
 * Wide windows need nothing more: pages keep their maximum width and center, card grids add columns.
 */
object Fit {
    var scale = 0.53f; private set
    var narrow = true; private set

    fun window(widthDp: Int, heightDp: Int) {
        val basis = minOf(widthDp.toFloat(), heightDp * 1.1f)
        scale = (0.53f + (basis - 411f) * 0.00025f).coerceIn(0.50f, 0.66f)
        narrow = widthDp < 600
    }

    /** [wide] Barry pixels normally, [narrow] on a phone in portrait. */
    fun px(wide: Int, narrow: Int): Int = if (this.narrow) narrow else wide
}

val LocalSession = compositionLocalOf<OniSession> { error("no session") }
/** The page that shows the blocks (a form posts its answer there). */
val LocalPage = compositionLocalOf<PageController?> { null }

/** Barry pixels as dp / sp. */
val Int.bp: Dp get() = (this * SCALE).dp
val Float.bp: Dp get() = (this * SCALE).dp
val Int.bsp: TextUnit get() = (this * SCALE).sp
val Float.bsp: TextUnit get() = (this * SCALE).sp

const val BODY = 30
const val SMALL = 24

val Dp.safeMin get() = max(1f, this.value).dp
fun hairline(): Dp = 1.dp
fun stroke(): Dp = (2 * SCALE).dp.safeMin

@Composable fun theme(): GameTheme = LocalSession.current.theme
@Composable fun radius(): RoundedCornerShape = RoundedCornerShape(theme().radiusUnits.bp)

@Composable
fun bodyFamily(): FontFamily? = LocalSession.current.fonts.body

/** Text in the body font. Sizes are Barry pixels. */
@Composable
fun OText(
    text: String,
    modifier: Modifier = Modifier,
    size: Int = BODY,
    color: Color = theme().text,
    weight: FontWeight? = null,
    italic: Boolean = false,
    align: TextAlign? = null,
    maxLines: Int = Int.MAX_VALUE,
    overflow: TextOverflow = TextOverflow.Clip,
    caps: Boolean = false,
) {
    androidx.compose.material3.Text(
        text = if (caps) text.uppercase() else text,
        modifier = modifier,
        color = color,
        fontSize = size.bsp,
        fontWeight = weight,
        fontStyle = if (italic) FontStyle.Italic else null,
        fontFamily = bodyFamily(),
        textAlign = align,
        maxLines = maxLines,
        overflow = overflow,
    )
}

fun Color.withAlpha(a: Float) = copy(alpha = a)

// ---------------------------------------------------------------- art

/** A picture from the core's art folder, or null while it loads or when the game has none. */
@Composable
fun rememberArt(path: String?): ImageBitmap? {
    if (path.isNullOrEmpty()) return null
    val repo = LocalSession.current.art
    val gen = repo.generation
    var bmp by remember(path) { mutableStateOf(repo.peek(path)) }
    LaunchedEffect(path, gen) {
        if (bmp == null) {
            bmp = try { repo.load(path) } catch (e: CancellationException) { throw e } catch (e: Exception) { null }
        }
    }
    return bmp
}

/**
 * Art.qml: takes no space when [art] is empty. A plain tile with the first letter of [glyph] shows while the picture
 * loads or when the game has none. Inside a LazyColumn the picture is only asked for once its row is composed.
 */
@Composable
fun ArtImage(art: String?, glyph: String, size: Dp, modifier: Modifier = Modifier) {
    if (art.isNullOrEmpty()) return
    val th = theme()
    val bmp = rememberArt(art)
    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        if (bmp != null) {
            Image(bmp, null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit, filterQuality = FilterQuality.Medium)
        } else {
            Box(Modifier.fillMaxSize().clip(RoundedCornerShape((th.radiusUnits / 2).bp)).background(th.panelHi), contentAlignment = Alignment.Center) {
                OText(glyph.take(1).uppercase(), size = max(10, (size.value / SCALE * 0.45f).roundToInt()), color = th.muted, weight = FontWeight.Bold)
            }
        }
    }
}

/** A theme icon (speed buttons) as a picture, or null. */
@Composable
fun rememberIcon(name: String, active: Boolean = false): ImageBitmap? {
    val ic = theme().icon(name) ?: return null
    return rememberArt(if (active) ic.activeArt ?: ic.art else ic.art)
}

// ---------------------------------------------------------------- 9-slice skins

private fun DrawScope.nineSlice(img: ImageBitmap, s: Slice, k: Float) {
    val iw = img.width
    val ih = img.height
    val l = s.insets.left.coerceIn(0, iw)
    val r = s.insets.right.coerceIn(0, iw - l)
    val t = s.insets.top.coerceIn(0, ih)
    val b = s.insets.bottom.coerceIn(0, ih - t)
    var dl = l * k; var dr = r * k; var dt = t * k; var db = b * k
    if (dl + dr > size.width) { val f = size.width / (dl + dr); dl *= f; dr *= f }
    if (dt + db > size.height) { val f = size.height / (dt + db); dt *= f; db *= f }
    val xs = intArrayOf(0, l, iw - r, iw)
    val ys = intArrayOf(0, t, ih - b, ih)
    val dxs = floatArrayOf(0f, dl, size.width - dr, size.width)
    val dys = floatArrayOf(0f, dt, size.height - db, size.height)
    for (j in 0 until 3) for (i in 0 until 3) {
        val sw = xs[i + 1] - xs[i]; val sh = ys[j + 1] - ys[j]
        val dw = dxs[i + 1] - dxs[i]; val dh = dys[j + 1] - dys[j]
        if (sw <= 0 || sh <= 0 || dw <= 0f || dh <= 0f) continue
        drawImage(
            img, IntOffset(xs[i], ys[j]), IntSize(sw, sh),
            IntOffset(dxs[i].roundToInt(), dys[j].roundToInt()), IntSize(dw.roundToInt().coerceAtLeast(1), dh.roundToInt().coerceAtLeast(1)),
            filterQuality = FilterQuality.Low,
        )
    }
}

/** The game's 9-slice image for [name], drawn over the parent's area; nothing until it has loaded or when the theme has none. */
@Composable
fun BoxScope.SkinLayer(name: String, modifier: Modifier = Modifier, alpha: Float = 1f) {
    val th = theme()
    val sl = th.slice(name) ?: return
    val img = rememberArt(sl.art) ?: return
    val k = max(1f, 2f * SCALE * LocalDensity.current.density)
    Canvas(modifier.matchParentSize().alpha(alpha)) { nineSlice(img, sl, k) }
}

// ---------------------------------------------------------------- taps and buttons

/**
 * A tappable rectangle (Tap.qml): [base] normally, [hi] while pressed. A long press calls [onLong] when given,
 * otherwise a slow press is still a tap.
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun TapBox(
    modifier: Modifier = Modifier,
    base: Color = Color.Transparent,
    hi: Color = theme().panelHi,
    shape: RoundedCornerShape = RoundedCornerShape(0.dp),
    border: BorderStroke? = null,
    enabled: Boolean = true,
    onLong: (() -> Unit)? = null,
    onTap: () -> Unit,
    content: @Composable BoxScope.(pressed: Boolean) -> Unit,
) {
    val src = remember { MutableInteractionSource() }
    val pressed by src.collectIsPressedAsState()
    var m = modifier.clip(shape).background(if (pressed) hi else base)
    if (border != null) m = m.border(border, shape)
    Box(
        m.combinedClickable(interactionSource = src, indication = null, enabled = enabled, onClick = onTap, onLongClick = onLong),
    ) { content(pressed) }
}

/** Btn.qml: a button with a label. */
@Composable
fun Btn(
    label: String,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
    dim: Boolean = false,
    minWidth: Dp = 0.dp,
    onTap: () -> Unit,
) {
    val th = theme()
    val shape = radius()
    TapBox(
        modifier.heightIn(min = 80.bp).widthIn(min = minWidth).alpha(if (dim) 0.4f else 1f),
        base = if (primary) th.accent else th.buttonNormal,
        hi = if (primary) th.accent.withAlpha(0.8f) else th.buttonPressed,
        shape = shape,
        border = if (primary) null else BorderStroke(stroke(), th.line),
        onTap = onTap,
    ) { pressed ->
        if (!primary) SkinLayer(if (pressed) "buttonPressed" else "button")
        Box(Modifier.padding(horizontal = 28.bp, vertical = 14.bp).heightIn(min = 52.bp), contentAlignment = Alignment.Center) {
            OText(label, color = if (primary) Color(0xFF06121F) else th.buttonText, weight = FontWeight.SemiBold, align = TextAlign.Center)
        }
    }
}

/** Pill.qml: a small rounded label (chip or badge). [compact]: smaller and always one line (a tag under a list title). */
@Composable
fun Pill(label: String, tint: Color, filled: Boolean = false, onPanel: Boolean = false, compact: Boolean = false, modifier: Modifier = Modifier) {
    val th = theme()
    val lum = 0.2126f * tint.red + 0.7152f * tint.green + 0.0722f * tint.blue
    val ink = if (onPanel && th.game && lum > 0.4f) Color(tint.red / 2.4f, tint.green / 2.4f, tint.blue / 2.4f, tint.alpha) else tint
    Box(
        modifier.heightIn(min = (if (compact) 34 else 44).bp).clip(RoundedCornerShape(50))
            .background(if (filled) tint.withAlpha(0.22f) else Color.Transparent, RoundedCornerShape(50))
            .border(stroke(), ink, RoundedCornerShape(50))
            .padding(horizontal = (if (compact) 10 else 14).bp),
        contentAlignment = Alignment.Center,
    ) {
        if (compact) OText(label, size = 19, color = ink, weight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        else OText(label, size = SMALL, color = ink, weight = FontWeight.SemiBold)
    }
}

// ---------------------------------------------------------------- header text

/**
 * A header in the game's header font. In order: the Graystroke atlas when the core has exported it and the text
 * fits on one line, else the game's Economica Bold, else the body font (HeaderText.qml). [width] limits the atlas.
 */
@Composable
fun HeaderText(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = theme().title,
    size: Int = BODY,
    weight: FontWeight = FontWeight.Bold,
    caps: Boolean = false,
    letterSpacing: Float = 0f,
    maxLines: Int = Int.MAX_VALUE,
    overflow: TextOverflow = TextOverflow.Clip,
    align: TextAlign? = null,
) {
    val fonts = LocalSession.current.fonts
    val shown = if (caps) text.uppercase() else text
    val atlas = fonts.atlas
    val density = LocalDensity.current
    BoxWithConstraints(modifier) {
        val px = with(density) { size.bsp.toPx() }
        val fits = atlas != null && shown.isNotEmpty() && '\n' !in shown &&
            atlas.measure(shown, px, letterSpacing) <= with(density) { maxWidth.toPx() }
        val rendered = if (fits) atlas!!.render(shown, px, letterSpacing) else null
        if (rendered != null) {
            Image(
                rendered.bitmap.asImageBitmap(), shown,
                Modifier.size(with(density) { rendered.widthPx.toDp() }, with(density) { rendered.heightPx.toDp() }),
                colorFilter = ColorFilter.tint(color),
            )
        } else {
            androidx.compose.material3.Text(
                shown, color = color, fontSize = size.bsp, fontWeight = weight,
                fontFamily = fonts.headerFallback ?: fonts.body, maxLines = maxLines, overflow = overflow,
                textAlign = align, letterSpacing = letterSpacing.sp,
            )
        }
    }
}

/** SectionBar.qml: the game's section header bar. */
@Composable
fun SectionBar(text: String) {
    val th = theme()
    Box(Modifier.fillMaxWidth().height(64.bp).background(th.sectionHeader), contentAlignment = Alignment.CenterStart) {
        SkinLayer("sectionHeader")
        HeaderText(
            text, Modifier.fillMaxWidth().padding(horizontal = 22.bp), color = th.sectionHeaderText,
            size = SMALL + 2, caps = true, letterSpacing = 1f, maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
    }
}

/** The title every titled block has: a game section bar, else small caps text. */
@Composable
fun BlockTitle(title: String?) {
    if (title.isNullOrEmpty()) return
    val th = theme()
    if (th.game) SectionBar(title)
    else OText(title, Modifier.fillMaxWidth(), size = SMALL, color = th.muted, weight = FontWeight.SemiBold, caps = true)
}

// ---------------------------------------------------------------- meter

/** ProgressBar.qml: label, "value / max unit" and a bar. */
@Composable
fun MeterBar(label: String, value: Double, max: Double, unit: String?, tone: String?, onPanel: Boolean, modifier: Modifier = Modifier) {
    val th = theme()
    val frac = if (max > 0) (value / max).coerceIn(0.0, 1.0).toFloat() else 0f
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.bp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            OText(label, Modifier.weight(1f), size = SMALL, color = if (th.game && onPanel) th.text else th.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            OText(fmtNum(value) + " / " + fmtNum(max) + (if (unit.isNullOrEmpty()) "" else " $unit"), size = SMALL,
                color = if (onPanel) th.text else th.pageText)
        }
        Box(Modifier.fillMaxWidth().height(14.bp).clip(RoundedCornerShape(50)).background(th.progressTrack)) {
            Box(Modifier.fillMaxHeight().fillMaxWidth(frac).background(th.meterColor(label, tone)))
        }
    }
}

fun fmtNum(d: Double): String =
    if (d == Math.rint(d) && Math.abs(d) < 1e15) d.toLong().toString() else {
        val s = "%.2f".format(java.util.Locale.US, d).trimEnd('0').trimEnd('.')
        s
    }

// ---------------------------------------------------------------- rows and fields

/** NavRow.qml: a row card with title, subtitle, badge and a chevron. */
@Composable
fun NavRow(title: String, subtitle: String? = null, badge: String? = null, modifier: Modifier = Modifier, onTap: () -> Unit) {
    val th = theme()
    TapBox(modifier.fillMaxWidth().heightIn(min = 88.bp), base = th.panel, shape = radius(), onTap = onTap) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 26.bp, vertical = 14.bp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.bp)) {
            Column(Modifier.weight(1f)) {
                OText(title, color = th.text, weight = FontWeight.SemiBold)
                if (!subtitle.isNullOrEmpty()) OText(subtitle, size = SMALL, color = th.muted)
            }
            if (!badge.isNullOrEmpty()) Pill(badge, th.muted, filled = true, onPanel = true)
            OText("›", size = 44, color = th.muted)
        }
    }
}

/** SearchField.qml: a text field with a clear button. */
@Composable
fun SearchField(value: String, placeholder: String, onChange: (String) -> Unit, modifier: Modifier = Modifier, onDone: () -> Unit = {}) {
    val th = theme()
    var focused by remember { mutableStateOf(false) }
    Box(
        modifier.fillMaxWidth().heightIn(min = 88.bp).clip(radius()).background(th.panel)
            .border(stroke(), if (focused) th.accent else th.line, radius()),
        contentAlignment = Alignment.CenterStart,
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).padding(start = 28.bp)) {
                if (value.isEmpty()) OText(placeholder, color = th.muted)
                BasicTextField(
                    value, onChange, Modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused },
                    singleLine = true,
                    textStyle = TextStyle(color = th.text, fontSize = BODY.bsp, fontFamily = bodyFamily()),
                    cursorBrush = SolidColor(th.accent),
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Search),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSearch = { onDone() }),
                )
            }
            if (value.isNotEmpty()) {
                Box(Modifier.width(88.bp).height(88.bp).clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { onChange("") },
                    contentAlignment = Alignment.Center) { OText("✕", color = th.muted) }
            }
        }
    }
}

/** The built-in glyphs of the speed bar when the theme has no game sprite (SpeedGlyph.qml). */
@Composable
fun SpeedGlyph(kind: String, tint: Color, size: Dp) {
    val w = when (kind) { "speed2" -> size * 1.25f; "speed3" -> size * 1.6f; else -> size }
    Canvas(Modifier.size(w, size)) {
        val h = this.size.height
        val width = this.size.width
        if (kind == "pause") {
            val bw = h * 0.28f
            drawRect(tint, Offset(h * 0.16f, h * 0.14f), Size(bw, h * 0.72f))
            drawRect(tint, Offset(h * 0.56f, h * 0.14f), Size(bw, h * 0.72f))
            return@Canvas
        }
        val n = when (kind) { "speed2" -> 2; "speed3" -> 3; else -> 1 }
        val tw = if (n == 1) h * 0.62f else h * 0.46f
        val step = h * 0.34f
        val total = tw + step * (n - 1)
        var x = (width - total) / 2
        repeat(n) {
            val p = Path().apply {
                moveTo(x, h * 0.16f); lineTo(x + tw, h * 0.5f); lineTo(x, h * 0.84f); close()
            }
            drawPath(p, tint, style = Fill)
            x += step
        }
    }
}

@Composable
fun ProvideSession(session: OniSession, content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalSession provides session, content = content)
}
