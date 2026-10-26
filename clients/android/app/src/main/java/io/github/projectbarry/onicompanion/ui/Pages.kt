package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.projectbarry.onicompanion.session.LookupController
import io.github.projectbarry.onicompanion.session.LookupEntry
import io.github.projectbarry.onicompanion.session.PageController
import io.github.projectbarry.onicompanion.session.ScreenEntry
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

private val PAGE_MAX get() = 1160.bp

/** The line under a page title that says where its numbers come from (Barry's sourceLine). */
fun sourceLine(src: String?, asOf: String?): String {
    if (src.isNullOrEmpty()) return ""
    val names = mapOf(
        "mod-live" to "Live from the game", "save" to "From your newest save", "header" to "From the save header",
        "mod-export" to "From the game's own numbers", "yaml" to "From game files", "none" to "No data",
    )
    var out = names[src] ?: src
    if (!asOf.isNullOrEmpty()) {
        runCatching {
            val t = Instant.parse(asOf).atZone(ZoneId.systemDefault())
            out += " - " + DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT).format(t)
        }
    }
    return out
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScreenPageView(page: PageController) {
    val s = LocalSession.current
    val th = s.theme
    val entry = page.entry
    val sc = page.screen
    Box(Modifier.fillMaxSize().background(th.bg)) {
        CompositionLocalProvider(LocalPage provides page) {
            BoxWithConstraints(Modifier.fillMaxSize().padding(bottom = if (entry.closeBar) 150.dp else 0.dp)) {
                // Full width so a swipe beside the content still scrolls; on a wide window the side padding centers
                // the content at PAGE_MAX.
                val side = maxOf(Fit.px(32, 18).bp, (maxWidth - PAGE_MAX) / 2)
                LazyColumn(
                    Modifier.fillMaxSize(), state = page.listState,
                    contentPadding = PaddingValues(start = side, end = side, top = 24.bp, bottom = 60.bp),
                    verticalArrangement = Arrangement.spacedBy(24.bp),
                ) {
                    if (sc != null) {
                        item(key = "head") {
                            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.bp)) {
                                OText(sc.title, color = th.title, size = 52, weight = FontWeight.Bold)
                                if (!sc.subtitle.isNullOrEmpty()) OText(sc.subtitle, color = th.muted)
                                val src = sourceLine(sc.source, sc.asOf)
                                if (src.isNotEmpty()) OText(src, size = SMALL, color = th.accent)
                            }
                        }
                        sc.worldSwitcher?.let { ws ->
                            item(key = "worlds") {
                                FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.bp), verticalArrangement = Arrangement.spacedBy(12.bp)) {
                                    for (w in ws.worlds) {
                                        val on = ws.active == w.id
                                        TapBox(
                                            Modifier.heightIn(min = 72.bp), base = if (on) th.accent.withAlpha(0.25f) else th.buttonNormal,
                                            shape = RoundedCornerShape(50), border = androidx.compose.foundation.BorderStroke(stroke(), if (on) th.accent else th.line),
                                            onTap = { if (!on) page.pickWorld(w.id) },
                                        ) {
                                            OText(w.name, Modifier.padding(horizontal = 24.bp, vertical = 14.bp), size = SMALL + 2,
                                                color = if (on) th.title else th.muted, weight = FontWeight.SemiBold)
                                        }
                                    }
                                }
                            }
                        }
                        if (sc.filterPlaceholder != null) {
                            item(key = "filter") {
                                var raw by remember { mutableStateOf("") }
                                SearchField(raw, sc.filterPlaceholder, { raw = it; s.filterText = it.trim().lowercase() })
                            }
                        }
                        items(sc.blocks.size, key = { it }) { i -> BlockItem(sc.blocks[i]) }
                    } else {
                        item(key = "msg") {
                            Column(Modifier.fillMaxWidth().padding(top = 60.bp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(24.bp)) {
                                OText(if (page.failed) page.error else "Loading...", color = th.muted, align = TextAlign.Center)
                                if (page.failed) Btn("Try again", primary = true, onTap = { page.load(false) })
                            }
                        }
                    }
                }
            }
        }
        if (entry.closeBar) {
            Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(th.bg).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Btn("Re-sync art & fonts", Modifier.fillMaxWidth(), onTap = { s.openSync("full") })
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Btn("Refresh", Modifier.weight(1f), onTap = { page.load(true) })
                    Btn("Back to devices", Modifier.weight(1f), onTap = { s.onLeave() })
                }
            }
        }
        if (page.failed && sc != null) {
            Box(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(start = 24.bp, end = 24.bp, bottom = (if (entry.closeBar) 150.dp else 24.bp))
                    .clip(radius()).background(androidx.compose.ui.graphics.Color(0xFF3A1A1C)).border(stroke(), th.bad, radius())
                    .tapNoRipple { page.dismissError() }.padding(24.bp),
            ) { OText(page.error, color = th.pageText) }
        }
    }
}

@Composable
fun LookupPageView(c: LookupController) {
    val s = LocalSession.current
    val th = s.theme
    val q = c.query.trim()
    Box(Modifier.fillMaxSize().background(th.bg), contentAlignment = Alignment.TopCenter) {
        Column(Modifier.widthIn(max = PAGE_MAX + 64.bp).fillMaxSize().padding(start = Fit.px(32, 18).bp, end = Fit.px(32, 18).bp, top = 32.bp)) {
            SearchField(c.query, "Search elements, critters, plants...", { c.onQuery(it) }, onDone = { c.search() })
            LazyColumn(
                Modifier.fillMaxSize().padding(top = 24.bp), state = c.listState,
                contentPadding = PaddingValues(bottom = 80.bp), verticalArrangement = Arrangement.spacedBy(12.bp),
            ) {
                if (c.status.isNotEmpty()) item(key = "status") {
                    OText(c.status, Modifier.fillMaxWidth().padding(top = 30.bp), color = th.muted, align = TextAlign.Center)
                }
                if (q.isEmpty()) {
                    items(c.kinds.size, key = { "k" + c.kinds[it].kind }) { i ->
                        val k = c.kinds[i]
                        NavRow(k.label, badge = k.count.toString(), onTap = { s.push("list/" + io.github.projectbarry.onicompanion.session.NavState.enc(k.kind)) })
                    }
                    if (c.tools.isNotEmpty()) {
                        item(key = "calc") { OText("Calculators", Modifier.padding(top = 16.bp), size = SMALL, color = th.muted, weight = FontWeight.SemiBold, caps = true) }
                        items(c.tools.size, key = { "t" + c.tools[it].id }) { i ->
                            val t = c.tools[i]
                            NavRow(t.title, subtitle = t.summary.ifEmpty { null }, onTap = { s.push("tools/" + io.github.projectbarry.onicompanion.session.NavState.enc(t.id)) })
                        }
                    }
                } else {
                    items(c.results.size, key = { "r" + c.results[it].kind + ":" + c.results[it].id }) { i ->
                        val r = c.results[i]
                        NavRow(r.name, subtitle = s.kindLabel(r.kind) + (if (r.subtitle.isNotEmpty()) " - " + r.subtitle else ""),
                            badge = r.dlc.joinToString(", ").ifEmpty { null },
                            onTap = { s.openRef(io.github.projectbarry.onicompanion.screen.Ref(r.kind, r.id)) })
                    }
                }
            }
        }
    }
}

/** ElementPicker.qml: pick an element by searching. */
@Composable
fun ElementPickerView() {
    val s = LocalSession.current
    val th = s.theme
    val p = s.picker
    Box(Modifier.fillMaxSize().background(th.bg).tapNoRipple { }, contentAlignment = Alignment.TopCenter) {
        Column(Modifier.widthIn(max = PAGE_MAX + 64.bp).fillMaxSize().padding(Fit.px(32, 18).bp), verticalArrangement = Arrangement.spacedBy(20.bp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.bp), verticalAlignment = Alignment.CenterVertically) {
                SearchField(p.query, "Search elements...", { p.onQuery(it) }, Modifier.weight(1f), onDone = { p.search() })
                Btn("Cancel", onTap = { s.pickCancelled() })
            }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 60.bp), verticalArrangement = Arrangement.spacedBy(12.bp)) {
                if (p.status.isNotEmpty()) item(key = "status") { OText(p.status, Modifier.fillMaxWidth().padding(top = 30.bp), color = th.muted, align = TextAlign.Center) }
                items(p.results.size, key = { p.results[it].id }) { i ->
                    val r = p.results[i]
                    NavRow(r.name, subtitle = r.subtitle.ifEmpty { null }, onTap = { s.picked(r.id, r.name) })
                }
            }
        }
    }
}

/** SyncPage.qml: "Sync art & fonts from your game". Every word and number comes from GET /sync. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SyncPageView() {
    val s = LocalSession.current
    val th = s.theme
    val info = s.sync
    val running = info.state == "running"
    val queued = info.queued && !running
    val canStart = info.canStart
    fun num(n: Int) = java.text.NumberFormat.getIntegerInstance().format(n)
    fun seconds(ms: Long) = Math.max(1, Math.round(ms / 1000.0))
    val headline = when {
        running -> "Syncing art & fonts"
        queued -> "Sync is waiting for the game"
        info.state == "done" && !info.needed -> "Sync finished"
        info.state == "failed" -> "The sync did not finish"
        else -> "Sync art & fonts from your game"
    }
    val explain = when {
        running -> if (info.total > 0) "Drawing the pictures from your own copy of the game. The game is paused until this is done, then it goes on at the speed it had."
                   else "Waiting for the game to start..."
        queued -> if (info.message != null) info.message + " The sync starts by itself when it can. You can leave this screen."
                  else if (info.reason == "menu") "The game is at its menu. The sync starts by itself when you load a colony. You can leave this screen."
                  else "The sync starts by itself when you load a colony in Oxygen Not Included with the ONI Companion Link mod on. You can leave this screen."
        info.state == "done" && !info.needed ->
            num(info.total) + " items checked" + (if (info.elapsedMs > 0) " in " + seconds(info.elapsedMs) + " s" else "") + "." +
                (if (info.errors > 0) " " + info.errors + " could not be drawn." else "")
        info.state == "failed" -> info.lastError ?: "Something went wrong. You can try again."
        info.neededReason == "new_build" -> "The game was updated. Its pictures and fonts are copied again."
        info.neededReason == "new_dlc" -> "A DLC was added. Only what is new is copied."
        else -> "This app shows the pictures and fonts of your own game. They are copied from it once, and nothing from the game is stored in the app itself."
    }
    Box(Modifier.fillMaxSize().background(th.bg).tapNoRipple { }) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(32.bp), verticalArrangement = Arrangement.spacedBy(28.bp)) {
            OText(headline, color = th.pageText, size = (BODY * 1.2f).toInt(), weight = FontWeight.Bold)
            OText(explain, color = th.muted)
            if (!running && !canStart && !queued) {
                Column(Modifier.fillMaxWidth().clip(radius()).background(th.warn.withAlpha(0.14f)).border(stroke(), th.warn, radius()).padding(24.bp), verticalArrangement = Arrangement.spacedBy(6.bp)) {
                    OText("No colony is running yet", color = th.warn, weight = FontWeight.Bold)
                    OText(
                        if (info.message != null) info.message + " Tap Start sync now: it begins when a colony is running."
                        else if (info.reason == "menu") "The game is at its menu. Tap Start sync now: it begins when you load a colony."
                        else "Tap Start sync now: it begins when you start the game with the ONI Companion Link mod on and load a colony.",
                        size = SMALL + 2, color = th.pageText,
                    )
                }
            }
            if (running && info.total > 0) {
                Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.bp)) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        OText(info.current ?: "", Modifier.weight(1f), size = SMALL, color = th.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        OText(num(info.done) + " / " + num(info.total), color = th.pageText, weight = FontWeight.SemiBold)
                    }
                    Box(Modifier.fillMaxWidth().heightIn(min = 16.bp).clip(RoundedCornerShape(50)).background(th.progressTrack)) {
                        Box(Modifier.fillMaxWidth((info.done.toFloat() / Math.max(1, info.total)).coerceIn(0f, 1f)).heightIn(min = 16.bp).background(th.progressFill))
                    }
                }
            }
            if (running && info.errors > 0)
                OText(info.errors.toString() + " could not be drawn" + (info.lastError?.let { ": $it" } ?: ""), size = SMALL + 2, color = th.warn)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(20.bp), verticalArrangement = Arrangement.spacedBy(12.bp)) {
                if (!running && !queued)
                    Btn(if (info.state == "failed") "Try again" else if (info.state == "done" && !info.needed) "Sync again" else "Start sync",
                        primary = true, onTap = { s.startSync(s.syncScope) })
                Btn(if (running || queued) "Hide" else if (info.state == "done" && !info.needed) "Close" else "Not now", onTap = { s.syncOpen = false })
                if (queued) Btn("Cancel sync", onTap = { s.cancelSync() })
            }
        }
    }
}

@Composable
fun PageFor(entry: io.github.projectbarry.onicompanion.session.Entry) {
    val s = LocalSession.current
    when (entry) {
        is ScreenEntry -> ScreenPageView(s.pageFor(entry))
        is LookupEntry -> LookupPageView(s.lookupFor(entry))
    }
}
