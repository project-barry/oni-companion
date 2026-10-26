package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.ui.composed
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.InlineTextContent
import androidx.compose.foundation.text.appendInlineContent
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.Placeholder
import androidx.compose.ui.text.PlaceholderVerticalAlign
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.projectbarry.onicompanion.screen.Action
import io.github.projectbarry.onicompanion.screen.Block
import io.github.projectbarry.onicompanion.screen.Card
import io.github.projectbarry.onicompanion.screen.Field
import io.github.projectbarry.onicompanion.screen.ListItem
import io.github.projectbarry.onicompanion.screen.PickerOption
import io.github.projectbarry.onicompanion.screen.Port
import io.github.projectbarry.onicompanion.screen.StatRow
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.roundToInt

/** Renders a list of blocks top to bottom (BlockView.qml). A type the app does not know shows the "update" notice. */
@Composable
fun BlockList(blocks: List<Block>, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy((20 * 1.2f).bp)) {
        blocks.forEachIndexed { i, b -> androidx.compose.runtime.key(i) { BlockItem(b) } }
    }
}

@Composable
fun BlockItem(b: Block) {
    when (b) {
        is Block.Heading -> HeadingBlockView(b)
        is Block.Text -> TextBlockView(b)
        is Block.Stats -> StatsBlockView(b)
        is Block.Chips -> ChipsBlockView(b)
        is Block.Items -> ListBlockView(b)
        is Block.Grid -> if (b.variant == "pad" || b.variant == "priority") PadGridView(b) else GridBlockView(b)
        is Block.Ports -> PortsBlockView(b)
        is Block.Phases -> PhasesBlockView(b)
        is Block.Progress -> MeterBar(b.label, b.value, b.max, b.unit, b.tone, onPanel = false)
        is Block.Table -> TableBlockView(b)
        is Block.Notice -> NoticeView(b.level, b.title, b.text)
        is Block.Form -> FormBlockView(b)
        is Block.Link -> LinkBlockView(b)
        is Block.Image -> ImageBlockView(b)
        is Block.Picker -> PickerBlockView(b)
        Block.Divider -> Box(Modifier.fillMaxWidth().height(12.bp), contentAlignment = Alignment.Center) {
            Box(Modifier.fillMaxWidth().height(stroke()).background(theme().line))
        }
        is Block.Group -> GroupBlockView(b)
        is Block.Unknown -> UnknownBlockView()
    }
}

@Composable
private fun UnknownBlockView() {
    val th = theme()
    Box(Modifier.fillMaxWidth().clip(radius()).background(th.panel).padding(24.bp)) {
        OText("Update the app to see this.", color = th.muted)
    }
}

@Composable
fun NoticeView(level: String, title: String?, text: String) {
    val th = theme()
    val tint = when (level) { "error" -> th.bad; "warn" -> th.warn; else -> th.accent }
    Column(
        Modifier.fillMaxWidth().clip(radius()).background(tint.withAlpha(0.14f)).border(stroke(), tint, radius()).padding(24.bp),
        verticalArrangement = Arrangement.spacedBy(4.bp),
    ) {
        if (!title.isNullOrEmpty()) OText(title, color = tint, weight = FontWeight.Bold)
        OText(text, color = th.pageText)
    }
}

// ---------------------------------------------------------------- heading, text

@Composable
private fun HeadingBlockView(b: Block.Heading) {
    val th = theme()
    Row(Modifier.fillMaxWidth().padding(vertical = 4.bp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(18.bp)) {
        if (!b.art.isNullOrEmpty()) ArtImage(b.art, b.text, (if (b.level == 1) 96 else 64).bp)
        HeaderText(
            b.text, Modifier.weight(1f), color = if (b.level == 3) th.muted else th.title,
            size = when (b.level) { 1 -> 50; 2 -> 40; else -> 30 },
        )
    }
}

@Composable
private fun TextBlockView(b: Block.Text) {
    val s = LocalSession.current
    val th = s.theme
    val inline = HashMap<String, InlineTextContent>()
    val link = TextLinkStyles(SpanStyle(color = th.accent, textDecoration = TextDecoration.Underline))
    val text: AnnotatedString = buildAnnotatedString {
        b.spans.forEachIndexed { i, sp ->
            if (!sp.icon.isNullOrEmpty()) {
                val id = "icon$i"
                appendInlineContent(id, "*")
                inline[id] = InlineTextContent(Placeholder(BODY.bsp, BODY.bsp, PlaceholderVerticalAlign.TextCenter)) {
                    ArtImage(sp.icon, "", BODY.bp)
                }
            }
            val style = SpanStyle(color = th.token(sp.color) ?: Color.Unspecified, fontWeight = if (sp.bold) FontWeight.Bold else null)
            val ann: LinkAnnotation? = when {
                sp.type == "ref" && sp.ref != null -> LinkAnnotation.Clickable("ref", link) { s.openRef(sp.ref) }
                sp.type == "link" && !sp.url.isNullOrEmpty() -> LinkAnnotation.Clickable("url", link) { s.openUrl(sp.url) }
                sp.action != null -> LinkAnnotation.Clickable("span", link) { s.fire(sp.action) }
                else -> null
            }
            if (ann != null) withLink(ann) { withStyle(style) { append(sp.text) } } else withStyle(style) { append(sp.text) }
        }
    }
    androidx.compose.material3.Text(
        text, Modifier.fillMaxWidth(), color = th.pageText, fontSize = BODY.bsp, lineHeight = (BODY * 1.2f).bsp,
        fontFamily = bodyFamily(), inlineContent = inline,
    )
}

// ---------------------------------------------------------------- stats

@Composable
private fun StatsBlockView(b: Block.Stats) {
    val s = LocalSession.current
    val th = s.theme
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(if (th.game) 0.dp else 6.bp)) {
        BlockTitle(b.title)
        Column(Modifier.fillMaxWidth().clip(radius()).background(th.panel)) {
            b.rows.forEachIndexed { i, r -> StatRowView(r, i > 0) }
        }
    }
}

@Composable
private fun StatRowView(r: StatRow, divider: Boolean) {
    val s = LocalSession.current
    val th = s.theme
    TapBox(Modifier.fillMaxWidth().heightIn(min = 72.bp), onTap = { r.ref?.let { s.openRef(it) } }) {
        if (divider) Box(Modifier.fillMaxWidth().height(hairline()).background(th.line))
        Row(Modifier.fillMaxWidth().padding(horizontal = Fit.px(26, 18).bp, vertical = 14.bp), horizontalArrangement = Arrangement.spacedBy(20.bp)) {
            Column(Modifier.weight(1f)) {
                OText(r.label, color = th.text)
                if (!r.hint.isNullOrEmpty()) OText(r.hint, size = SMALL, color = th.muted)
            }
            OText(r.value, color = if (r.ref != null) th.accent else th.valueTone(r.tone), weight = FontWeight.SemiBold, align = TextAlign.End)
        }
    }
}

// ---------------------------------------------------------------- chips

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChipsBlockView(b: Block.Chips) {
    val s = LocalSession.current
    val th = s.theme
    FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.bp), verticalArrangement = Arrangement.spacedBy(8.bp)) {
        for (c in b.chips) {
            val tint = when (c.style) { "dlc" -> Color(0xFFC08CF0); "state" -> th.accent; "category" -> th.warn; else -> th.muted }
            val m = if (c.ref != null) Modifier.clip(RoundedCornerShape(50)).tapNoRipple { s.openRef(c.ref) } else Modifier
            Pill(c.label, tint, filled = c.style == "dlc" || c.style == "state", modifier = m)
        }
    }
}

fun Modifier.tapNoRipple(onTap: () -> Unit): Modifier = composed {
    clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onTap)
}

// ---------------------------------------------------------------- list

@Composable
private fun ListBlockView(b: Block.Items) {
    val s = LocalSession.current
    val th = s.theme
    val ft = s.filterText
    val shown = if (ft.isEmpty()) b.items else b.items.filter { s.titleMatches(it.title) }
    if (ft.isNotEmpty() && shown.isEmpty()) return
    val alertStyle = th.game && b.variant == "alerts"
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(if (th.game) 0.dp else 6.bp)) {
        BlockTitle(b.title)
        if (shown.isEmpty() && ft.isEmpty()) {
            OText(b.empty ?: "", color = th.muted)
        } else if (shown.isNotEmpty()) {
            Box(Modifier.fillMaxWidth().clip(radius()).background(if (alertStyle) th.alertBg else th.panel)) {
                if (!alertStyle) SkinLayer("panel")
                Column(Modifier.fillMaxWidth()) {
                    shown.forEachIndexed { i, it -> ListRow(it, i, alertStyle) }
                }
            }
        }
    }
}

@Composable
private fun ListRow(item: ListItem, index: Int, alertStyle: Boolean) {
    val s = LocalSession.current
    val th = s.theme
    val acts = item.actions.filter { !it.longPress }
    val hold = item.actions.filter { it.longPress }
    val alertRef = item.ref?.kind == "alert"
    val revealId = if (item.ref != null) "ref:${item.ref.kind}:${item.ref.id}" else "row:${item.title}"
    val revealed = s.revealKey == revealId
    val alertColor = if (item.tone == "bad") th.alertBadText else th.alertText
    val artPath = item.art ?: item.ref?.art
    val hasPic = !artPath.isNullOrEmpty()
    TapBox(
        Modifier.fillMaxWidth().heightIn(min = (if (alertStyle) 60 else 88).bp),
        onLong = if (hold.isNotEmpty() || alertRef) ({ s.reveal(revealId) }) else null,
        onTap = { item.ref?.let { s.openRef(it) } },
    ) {
        if (index > 0 && !alertStyle) Box(Modifier.fillMaxWidth().height(hairline()).background(th.line))
        if (!item.tone.isNullOrEmpty() && item.tone != "neutral" && !alertStyle)
            Box(Modifier.matchParentSize()) { Box(Modifier.width(8.bp).fillMaxHeight().background(th.tone(item.tone))) }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = Fit.px(26, 18).bp, vertical = (if (alertStyle) 9 else 14).bp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(Fit.px(16, 12).bp),
        ) {
            if (alertStyle && !hasPic) OText("•", color = alertColor)
            if (hasPic) ArtImage(artPath, item.title, if (alertStyle) (BODY * 1.1f).bp else 64.bp)
            Column(Modifier.weight(1f)) {
                val countSuffix = if (alertStyle && !item.badge.isNullOrEmpty() && !Regex("\\(\\d+\\)\\s*$").containsMatchIn(item.title))
                    " (" + item.badge.removePrefix("x") + ")" else ""
                OText(item.title + countSuffix, color = if (alertStyle) alertColor else th.text,
                    weight = if (alertStyle) FontWeight.Normal else FontWeight.SemiBold)
                if (!item.subtitle.isNullOrEmpty())
                    OText(item.subtitle, size = SMALL, color = if (alertStyle) alertColor else th.muted, modifier = Modifier.alpha(if (alertStyle) 0.75f else 1f))
                // Under the title, not beside it: on a phone a long badge ("The Frosty Planet Pack") next to the
                // action buttons left the title a few pixels wide, one letter per line.
                if (!item.badge.isNullOrEmpty() && !alertStyle)
                    Pill(item.badge, if (item.tone != null) th.tone(item.tone) else th.muted, filled = true, onPanel = true,
                        compact = true, modifier = Modifier.padding(top = 6.bp))
                if (revealed && hold.isNotEmpty()) {
                    @OptIn(ExperimentalLayoutApi::class)
                    FlowRow(Modifier.padding(top = 8.bp, bottom = 6.bp), horizontalArrangement = Arrangement.spacedBy(12.bp)) {
                        hold.forEach { ActionBtn(it) }
                    }
                }
                if (revealed && hold.isEmpty() && alertRef)
                    OText("This alert can't be dismissed in the game", size = SMALL, color = alertColor, italic = true,
                        modifier = Modifier.padding(top = 6.bp).alpha(0.85f))
            }
            acts.forEach { ActionBtn(it) }
            if (item.ref != null) OText("›", size = 44, color = th.muted)
        }
    }
}

// ---------------------------------------------------------------- action button

/** ActionBtn.qml: one tap sends one command: "Sent", then "Done" or the error. Tapping again sends again. */
@Composable
fun ActionBtn(action: Action, modifier: Modifier = Modifier) {
    val s = LocalSession.current
    val th = s.theme
    var phase by remember(action.id, action.args) { mutableStateOf("idle") }
    val usable = action.enabled
    val ended = phase == "done" || phase == "failed"
    val fill = when (phase) { "failed" -> th.bad; "done" -> th.good; else -> th.buttonNormal }

    fun doSend() {
        if (phase == "sent") return
        phase = "sent"
        s.scope.launch {
            val res = try { withTimeout(15000) { s.runAction(action) } } catch (e: TimeoutCancellationException) { "The game did not answer." }
            if (res == null) phase = "done" else { phase = "failed"; s.toast(res.ifEmpty { "That did not work." }) }
            delay(3500)
            if (phase != "sent") phase = "idle"
        }
    }
    fun why() = s.notify(action.reason ?: "Not available right now.")
    fun send() {
        if (phase == "sent") return
        if (!usable) { why(); return }
        val c = action.confirm
        if (c != null) { s.ask(c) { doSend() }; return }
        doSend()
    }
    val lum = 0.299f * fill.red + 0.587f * fill.green + 0.114f * fill.blue
    val border = when (phase) { "failed" -> th.bad; "done" -> th.good; else -> if (action.danger) th.bad else th.accent }
    TapBox(
        modifier.heightIn(min = 72.bp).widthIn(min = Fit.px(180, 150).bp).alpha(if (usable) 1f else 0.45f),
        base = fill, hi = if (ended) fill else th.buttonPressed, shape = radius(), border = BorderStroke(stroke(), border),
        onLong = if (!usable) ({ why() }) else null, onTap = { send() },
    ) { pressed ->
        if (!ended) SkinLayer(if (pressed) "buttonPressed" else "button")
        Box(Modifier.padding(horizontal = Fit.px(24, 16).bp, vertical = 10.bp).heightIn(min = 52.bp), contentAlignment = Alignment.Center) {
            OText(
                when (phase) { "sent" -> "Sent"; "done" -> "Done"; "failed" -> "Failed"; else -> action.label },
                size = SMALL + 2, weight = FontWeight.SemiBold, align = TextAlign.Center,
                color = if (ended) (if (lum > 0.55f) Color.Black else Color.White) else if (action.danger && phase == "idle") th.bad else th.buttonText,
            )
        }
    }
}

// ---------------------------------------------------------------- grid (cards)

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GridBlockView(b: Block.Grid) {
    val s = LocalSession.current
    val th = s.theme
    val ft = s.filterText
    val shown = if (ft.isEmpty()) b.cards else b.cards.filter { s.titleMatches(it.title) }
    if (ft.isNotEmpty() && shown.isEmpty()) return
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.bp)) {
        BlockTitle(b.title)
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val gap = 18.bp
            val cols = max(1, floor((maxWidth.value + gap.value) / (380.bp.value + gap.value)).toInt())
            val cardW = (maxWidth - gap * (cols - 1)) / cols - 0.5.dp
            FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(gap), verticalArrangement = Arrangement.spacedBy(gap)) {
                shown.forEach { CardView(it, Modifier.width(cardW)) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CardView(c: Card, modifier: Modifier) {
    val s = LocalSession.current
    val th = s.theme
    val hold = c.actions.filter { it.longPress }
    val revealId = if (c.ref != null) "ref:${c.ref.kind}:${c.ref.id}" else "card:${c.title}"
    val artPath = c.art ?: c.ref?.art
    TapBox(modifier, base = th.panel, shape = radius(), onLong = if (hold.isNotEmpty()) ({ s.reveal(revealId) }) else null,
        onTap = { c.ref?.let { s.openRef(it) } }) {
        SkinLayer("panel")
        if (!c.tone.isNullOrEmpty() && c.tone != "neutral")
            Box(Modifier.matchParentSize().padding(vertical = th.radiusUnits.bp), contentAlignment = Alignment.CenterStart) {
                Box(Modifier.width(8.bp).fillMaxHeight().background(th.tone(c.tone)))
            }
        Column(Modifier.fillMaxWidth().padding(start = 24.bp, end = 24.bp, top = 18.bp, bottom = 18.bp), verticalArrangement = Arrangement.spacedBy(10.bp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.bp)) {
                if (!artPath.isNullOrEmpty()) ArtImage(artPath, c.title, 112.bp)
                Column(Modifier.weight(1f)) {
                    OText(c.title, size = 34, color = th.text, weight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    if (!c.subtitle.isNullOrEmpty()) OText(c.subtitle, size = SMALL, color = th.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (!c.badge.isNullOrEmpty()) Pill(c.badge, th.tone(c.tone), filled = true, onPanel = true)
            }
            if (c.badges.isNotEmpty())
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.bp), verticalArrangement = Arrangement.spacedBy(8.bp)) {
                    c.badges.forEach { Pill(it.label, th.level(it.level), filled = true, onPanel = true) }
                }
            c.meters.forEach { MeterBar(it.label, it.value, it.max, it.unit, it.tone ?: "neutral", onPanel = true) }
            c.stats.forEach { st ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.bp)) {
                    OText(st.label, Modifier.widthIn(max = 160.bp), size = SMALL, color = th.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    OText(st.value, Modifier.weight(1f), size = SMALL, color = th.valueTone(st.tone), weight = FontWeight.SemiBold, align = TextAlign.End)
                }
            }
            val tapActs = c.actions.filter { !it.longPress }
            val shownHold = if (s.revealKey == revealId) hold else emptyList()
            if (tapActs.isNotEmpty() || shownHold.isNotEmpty())
                FlowRow(horizontalArrangement = Arrangement.spacedBy(12.bp), verticalArrangement = Arrangement.spacedBy(8.bp)) {
                    tapActs.forEach { ActionBtn(it) }
                    shownHold.forEach { ActionBtn(it) }
                }
        }
    }
}

// ---------------------------------------------------------------- pad / priority

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PadGridView(b: Block.Grid) {
    val th = theme()
    val bar = b.variant == "priority"
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.bp)) {
        BlockTitle(b.title)
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val gap = (if (bar) 8 else 14).bp
            val cols = if (bar) max(1, b.cards.size) else max(2, floor((maxWidth.value + gap.value) / (200.bp.value + gap.value)).toInt())
            val cellW = ((maxWidth - gap * (cols - 1)) / cols) - 0.5.dp
            val busy = remember { mutableStateOf("") }
            FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(gap), verticalArrangement = Arrangement.spacedBy(gap)) {
                b.cards.forEach { PadButton(it, bar, Modifier.width(cellW), busy) }
            }
        }
    }
}

@Composable
private fun PadButton(card: Card, bar: Boolean, modifier: Modifier, busy: androidx.compose.runtime.MutableState<String>) {
    val s = LocalSession.current
    val th = s.theme
    val act = card.actions.firstOrNull()
    val usable = act != null && act.enabled
    val on = act?.active == true
    val key = if (act != null) act.id + "|" + act.args.toString() else ""
    val working = busy.value == key && key.isNotEmpty()
    val hasPic = !bar && !card.art.isNullOrEmpty()
    fun press() {
        if (act == null) return
        if (!usable) { s.notify(act.reason ?: "Not available right now."); return }
        if (working) return
        busy.value = key
        s.scope.launch {
            val res = try { withTimeout(15000) { s.runAction(act) } } catch (e: TimeoutCancellationException) { "The game did not answer." }
            if (busy.value == key) busy.value = ""
            if (res != null) s.toast(res.ifEmpty { "That did not work." })
        }
    }
    TapBox(
        modifier.height((if (bar) 96 else if (hasPic) 178 else 120).bp).alpha(if (usable) 1f else 0.4f),
        base = if (on) th.accent.withAlpha(0.30f) else th.buttonNormal, hi = th.buttonPressed, shape = radius(),
        border = BorderStroke(max(if (on) 3f else 1f, (if (on) 3 else 2) * SCALE).dp, if (on) th.accent else if (working) th.warn else th.line),
        onLong = if (!usable && act != null) ({ s.notify(act.reason ?: "Not available right now.") }) else null,
        onTap = { press() },
    ) { pressed ->
        if (!on) SkinLayer(if (pressed) "buttonPressed" else "button")
        if (!bar && !card.subtitle.isNullOrEmpty())
            OText(card.subtitle, Modifier.align(Alignment.TopEnd).padding(end = 12.bp, top = 8.bp), size = (SMALL * 0.85f).roundToInt(), color = th.muted)
        Column(Modifier.align(Alignment.Center).fillMaxWidth().padding(10.bp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.bp)) {
            if (hasPic) ArtImage(card.art, card.title, 84.bp)
            OText(
                card.title, Modifier.fillMaxWidth(), size = if (bar) 40 else SMALL, weight = FontWeight.SemiBold, align = TextAlign.Center,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
                color = if (on) th.title else if (bar && card.title == "!") th.bad else th.buttonText,
            )
        }
    }
}

// ---------------------------------------------------------------- ports, phases

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PortsBlockView(b: Block.Ports) {
    val th = theme()
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.bp)) {
        BlockTitle(b.title)
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val wide = maxWidth.value > 900.bp.value
            val colW = if (wide) (maxWidth - 18.bp) / 2 else maxWidth
            FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(18.bp), verticalArrangement = Arrangement.spacedBy(18.bp)) {
                PortBox("Inputs", b.inputs, Modifier.width(colW))
                PortBox("Outputs", b.outputs, Modifier.width(colW))
            }
        }
    }
}

@Composable
private fun PortBox(head: String, list: List<Port>, modifier: Modifier) {
    val s = LocalSession.current
    val th = s.theme
    Column(modifier.clip(radius()).background(th.panel).padding(start = 24.bp, end = 24.bp, top = 16.bp, bottom = 12.bp), verticalArrangement = Arrangement.spacedBy(4.bp)) {
        OText(head, size = SMALL, color = th.muted, weight = FontWeight.Bold)
        if (list.isEmpty()) OText("None", color = th.muted)
        list.forEach { p ->
            val hasConduit = !p.conduit.isNullOrEmpty() && p.conduit != "none"
            TapBox(Modifier.fillMaxWidth().heightIn(min = 72.bp), onTap = { p.element?.let { s.openRef(it) } }) {
                Row(Modifier.fillMaxWidth().padding(vertical = 8.bp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.bp)) {
                    if (hasConduit) Box(Modifier.size(14.bp).background(th.conduitColor(p.conduit), CircleShape))
                    Column(Modifier.weight(1f)) {
                        OText(p.label, color = if (p.element != null) th.accent else th.text)
                        if (hasConduit || !p.note.isNullOrEmpty())
                            OText((if (hasConduit) p.conduit!! else "") + (if (!p.note.isNullOrEmpty()) (if (hasConduit) " - " else "") + p.note else ""),
                                size = SMALL, color = th.muted)
                    }
                    if (p.rate != null) OText(fmtNum(p.rate) + (if (p.unit.isNullOrEmpty()) "" else " ${p.unit}"), color = th.text, weight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun PhasesBlockView(b: Block.Phases) {
    val s = LocalSession.current
    val th = s.theme
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.bp)) {
        BlockTitle(b.title)
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.bp)) {
            b.states.forEach { ph ->
                TapBox(Modifier.fillMaxWidth().heightIn(min = 88.bp), base = th.panel, shape = radius(), onTap = { ph.target?.let { s.openRef(it) } }) {
                    Box(Modifier.matchParentSize()) { Box(Modifier.width(22.bp).fillMaxHeight().background(th.stateColor(ph.state))) }
                    Row(Modifier.fillMaxWidth().padding(start = 52.bp, end = 24.bp, top = 14.bp, bottom = 14.bp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.bp)) {
                        Column(Modifier.weight(1f)) {
                            OText(ph.label, color = th.text, weight = FontWeight.SemiBold)
                            if (!ph.range.isNullOrEmpty()) OText(ph.range, size = SMALL, color = th.muted)
                        }
                        if (ph.target != null) OText("→ " + ph.target.id, size = SMALL, color = th.accent)
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- table

@Composable
private fun TableBlockView(b: Block.Table) {
    val s = LocalSession.current
    val th = s.theme
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(if (th.game) 0.dp else 6.bp)) {
        BlockTitle(b.title)
        Column(Modifier.fillMaxWidth().clip(radius()).background(th.panel)) {
            Row(Modifier.fillMaxWidth()) {
                b.columns.forEach { OText(it, Modifier.weight(1f).heightIn(min = 64.bp).padding(start = 18.bp, top = 16.bp), size = SMALL, color = th.muted, weight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            }
            b.rows.forEach { row ->
                Box(Modifier.fillMaxWidth()) {
                    Box(Modifier.fillMaxWidth().height(hairline()).background(th.line))
                    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                        row.forEach { cell ->
                            TapBox(Modifier.weight(1f).fillMaxHeight().heightIn(min = 72.bp), onTap = { cell.ref?.let { s.openRef(it) } }) {
                                OText(
                                    cell.text, Modifier.align(Alignment.CenterStart).padding(start = 18.bp, end = 8.bp, top = 12.bp, bottom = 12.bp),
                                    size = SMALL + 2, color = if (cell.ref != null) th.accent else th.valueTone(cell.tone),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- link, image

@Composable
private fun LinkBlockView(b: Block.Link) {
    val s = LocalSession.current
    val th = s.theme
    TapBox(Modifier.fillMaxWidth().heightIn(min = 88.bp), base = th.panel, shape = radius(), border = BorderStroke(stroke(), th.line), onTap = { s.openUrl(b.url) }) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 26.bp, vertical = 14.bp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.bp)) {
            OText(b.label.ifEmpty { b.url }, Modifier.weight(1f), color = th.accent, weight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            OText("↗", color = th.accent)
        }
    }
}

@Composable
private fun ImageBlockView(b: Block.Image) {
    val th = theme()
    val px = (when (b.size) { "small" -> 120; "large" -> 300; else -> 200 }).bp
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.bp)) {
        ArtImage(b.art, b.caption ?: b.alt ?: "", px)
        if (!b.caption.isNullOrEmpty()) OText(b.caption, Modifier.fillMaxWidth(), color = th.muted, align = TextAlign.Center)
    }
}

// ---------------------------------------------------------------- group

@Composable
private fun GroupBlockView(b: Block.Group) {
    val s = LocalSession.current
    val th = s.theme
    val key = s.nav.tab.toString() + "|" + b.title.replace(Regex("[:(].*$"), "")
    val userOpen = s.groupOpen[key] ?: !b.collapsed
    val open = userOpen || s.filterText.isNotEmpty()
    if (s.filterText.isNotEmpty() && !s.blockHasMatch(b)) return
    Column(Modifier.fillMaxWidth().clip(radius()).border(stroke(), th.line, radius())) {
        TapBox(
            Modifier.fillMaxWidth().heightIn(min = 88.bp), base = if (th.game) th.sectionHeader else th.header,
            onTap = { s.groupOpen[key] = !userOpen },
        ) {
            SkinLayer(if (th.game) "sectionHeader" else "header")
            Row(Modifier.fillMaxWidth().padding(horizontal = Fit.px(26, 18).bp, vertical = 14.bp), verticalAlignment = Alignment.CenterVertically) {
                OText(b.title, Modifier.weight(1f), color = if (th.game) th.sectionHeaderText else th.title, weight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                OText(if (open) "▾" else "▸", color = if (th.game) th.sectionHeaderText else th.muted)
            }
        }
        if (open) Box(Modifier.padding(horizontal = Fit.px(18, 8).bp, vertical = 12.bp)) { BlockList(b.blocks) }
    }
}

// ---------------------------------------------------------------- picker (material choice)

private fun kg(v: Double): String {
    val r = if (v >= 100) Math.round(v).toDouble() else Math.round(v * 10) / 10.0
    val nf = java.text.NumberFormat.getNumberInstance(java.util.Locale.US).apply { maximumFractionDigits = if (r % 1.0 == 0.0) 0 else 1; minimumFractionDigits = 0 }
    return nf.format(r) + " kg"
}

@Composable
private fun PickerBlockView(b: Block.Picker) {
    val s = LocalSession.current
    val th = s.theme
    val choice = remember { mutableStateMapOf<Int, String>() }
    fun chosenId(i: Int): String {
        val opts = b.slots.getOrNull(i)?.options.orEmpty()
        val u = choice[i]
        if (u != null && opts.any { it.id == u && it.enabled }) return u
        opts.firstOrNull { it.selected }?.let { return it.id }
        return opts.firstOrNull()?.id ?: ""
    }
    fun chosen(i: Int): PickerOption? = b.slots.getOrNull(i)?.options.orEmpty().firstOrNull { it.id == chosenId(i) }
    val materials = b.slots.indices.map { chosenId(it) }
    var blocker = ""
    for (i in b.slots.indices) {
        val o = chosen(i)
        if (o == null) { blocker = b.slots[i].empty ?: "No ${b.slots[i].label} to build with yet."; break }
        if (!o.enabled) { blocker = "Not enough ${o.name}."; break }
    }
    val args = JsonObject(b.action.args + ("materials" to JsonArray(materials.map { JsonPrimitive(it) })))
    var act = b.action.copy(args = args)
    if (act.enabled && blocker.isNotEmpty()) act = act.copy(enabled = false, reason = blocker)
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.bp)) {
        BlockTitle(b.title)
        b.slots.forEachIndexed { si, slot ->
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.bp)) {
                OText(slot.label + "  -  " + kg(slot.needKg), color = th.pageText, weight = FontWeight.SemiBold)
                if (slot.options.isEmpty()) OText(slot.empty ?: "Nothing to choose from yet.", size = SMALL, color = th.muted)
                slot.options.forEach { o ->
                    val on = o.id == chosenId(si)
                    TapBox(
                        Modifier.fillMaxWidth().heightIn(min = 100.bp),
                        base = if (on) th.accent.withAlpha(0.25f) else th.panel, shape = radius(),
                        border = BorderStroke(max(if (on) 3f else 1f, (if (on) 3 else 2) * SCALE).dp, if (on) th.accent else th.line),
                        onTap = {
                            if (o.enabled) choice[si] = o.id
                            else s.notify("Not enough ${o.name}: you have ${kg(o.haveKg)}, it needs ${kg(o.needKg)}.")
                        },
                    ) {
                        if (!on) SkinLayer("panel")
                        Row(Modifier.fillMaxWidth().padding(20.bp).alpha(if (o.enabled) 1f else 0.4f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.bp)) {
                            Box(Modifier.size(30.bp).clip(CircleShape).background(if (on) th.accent else Color.Transparent).border(max(2f, 3 * SCALE).dp, if (on) th.accent else th.muted, CircleShape))
                            val artPath = o.art ?: o.ref?.art
                            if (!artPath.isNullOrEmpty()) ArtImage(artPath, o.name, 68.bp)
                            OText(o.name, Modifier.weight(1f), color = th.text, weight = if (on) FontWeight.Bold else FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Column(horizontalAlignment = Alignment.End) {
                                OText("Needs " + kg(o.needKg), size = SMALL, color = th.muted)
                                OText("Have " + kg(o.haveKg), size = SMALL, color = if (o.enabled) th.text else th.bad, weight = FontWeight.SemiBold)
                            }
                        }
                    }
                }
            }
        }
        ActionBtn(act, Modifier.fillMaxWidth())
    }
}

// ---------------------------------------------------------------- form

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FormBlockView(b: Block.Form) {
    val s = LocalSession.current
    val th = s.theme
    val page = LocalPage.current
    val values = remember(b.tool) { mutableStateMapOf<String, String>() }
    val toggles = remember(b.tool) { mutableStateMapOf<String, Boolean>() }
    val units = remember(b.tool) { mutableStateMapOf<String, String>() }
    val names = remember(b.tool) { mutableStateMapOf<String, String>() }
    val bad = remember(b.tool) { mutableStateMapOf<String, Boolean>() }
    var busy by remember(b.tool) { mutableStateOf(false) }
    // starting values, once
    remember(b.tool) {
        for (f in b.fields) when (f.kind) {
            "number" -> { values[f.name] = f.default ?: ""; if (f.units.isNotEmpty()) units[f.name] = f.defaultUnit ?: f.units[0].id }
            "toggle" -> toggles[f.name] = f.defaultToggle
            "choice" -> values[f.name] = f.default ?: f.options.firstOrNull()?.value ?: ""
            "element" -> if (!f.default.isNullOrEmpty()) {
                values[f.name] = f.default
                s.scope.launch { s.nameOf("element", f.default)?.let { names[f.name] = it } }
            }
        }
        true
    }
    fun submit() {
        val out = HashMap<String, kotlinx.serialization.json.JsonElement>()
        var any = false
        bad.clear()
        for (f in b.fields) {
            when (f.kind) {
                "number" -> {
                    val n = values[f.name]?.toDoubleOrNull()
                    if (n == null) { bad[f.name] = true; any = true; continue }
                    val num: kotlinx.serialization.json.JsonElement = if (n == Math.rint(n) && Math.abs(n) < 1e15) JsonPrimitive(n.toLong()) else JsonPrimitive(n)
                    out[f.name] = if (f.units.isNotEmpty()) JsonObject(mapOf("value" to num, "unit" to JsonPrimitive(units[f.name] ?: f.units[0].id))) else num
                }
                "toggle" -> out[f.name] = JsonPrimitive(toggles[f.name] == true)
                else -> values[f.name]?.let { out[f.name] = JsonPrimitive(it) }
            }
        }
        if (any) return
        busy = true
        s.scope.launch {
            try { s.submitTool(page, b.tool, JsonObject(out), b.endpoint) } finally { busy = false }
        }
    }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(22.bp)) {
        if (!b.title.isNullOrEmpty()) OText(b.title, color = th.pageText, size = 34, weight = FontWeight.Bold)
        b.fields.forEach { f ->
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.bp)) {
                OText(f.label, size = SMALL, color = if (bad[f.name] == true) th.bad else th.muted, weight = FontWeight.SemiBold)
                when (f.kind) {
                    "number" -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.bp), verticalAlignment = Alignment.CenterVertically) {
                        var focused by remember { mutableStateOf(false) }
                        Box(
                            Modifier.weight(1f).heightIn(min = 88.bp).clip(radius()).background(th.panel)
                                .border(stroke(), if (bad[f.name] == true) th.bad else if (focused) th.accent else th.line, radius()).padding(horizontal = 26.bp),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            BasicTextField(
                                values[f.name] ?: "", { values[f.name] = it }, Modifier.fillMaxWidth().onFocusChanged { focused = it.isFocused },
                                singleLine = true, textStyle = TextStyle(color = th.text, fontSize = BODY.bsp, fontFamily = bodyFamily()),
                                cursorBrush = SolidColor(th.accent), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            )
                        }
                        if (f.units.isEmpty() && !f.unit.isNullOrEmpty()) OText(f.unit, color = th.muted)
                        if (f.units.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(8.bp)) {
                            f.units.forEach { u -> Btn(u.label, primary = units[f.name] == u.id, minWidth = 96.bp, onTap = { units[f.name] = u.id }) }
                        }
                    }
                    "element" -> TapBox(Modifier.fillMaxWidth().heightIn(min = 88.bp), base = th.panel, shape = radius(), border = BorderStroke(stroke(), th.line),
                        onTap = { s.pickElement(f.filter ?: "any") { id, name -> values[f.name] = id; names[f.name] = name } }) {
                        Row(Modifier.fillMaxWidth().padding(horizontal = 26.bp, vertical = 14.bp), verticalAlignment = Alignment.CenterVertically) {
                            val shown = names[f.name] ?: values[f.name]
                            OText(shown ?: "Choose...", Modifier.weight(1f), color = if (shown != null) th.text else th.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            OText("▾", color = th.muted)
                        }
                    }
                    "choice" -> FlowRow(horizontalArrangement = Arrangement.spacedBy(10.bp), verticalArrangement = Arrangement.spacedBy(10.bp)) {
                        f.options.forEach { o -> Btn(o.label, primary = values[f.name] == o.value, onTap = { values[f.name] = o.value }) }
                    }
                    "toggle" -> {
                        val on = toggles[f.name] == true
                        TapBox(Modifier.fillMaxWidth().heightIn(min = 76.bp), onTap = { toggles[f.name] = !on }) {
                            Row(Modifier.align(Alignment.CenterStart), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(20.bp)) {
                                Box(Modifier.width(110.bp).height(56.bp).clip(RoundedCornerShape(50)).background(if (on) th.accent else th.line)) {
                                    Box(Modifier.align(if (on) Alignment.CenterEnd else Alignment.CenterStart).padding(6.bp).size(44.bp).background(Color.White, CircleShape))
                                }
                                OText(if (on) "On" else "Off", color = th.pageText)
                            }
                        }
                    }
                }
            }
        }
        Btn(if (busy) "Working..." else b.submitLabel, Modifier.fillMaxWidth(), primary = true, dim = busy, onTap = { if (!busy) submit() })
    }
}
