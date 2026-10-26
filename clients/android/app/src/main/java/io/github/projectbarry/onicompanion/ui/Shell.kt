package io.github.projectbarry.onicompanion.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.Image
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.projectbarry.onicompanion.session.FatalText
import io.github.projectbarry.onicompanion.session.OniSession
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.foundation.layout.width as railWidth
import io.github.projectbarry.onicompanion.session.SpeedLogic

/**
 * The whole view of one connected gaming device (main.qml): header with the game state, the speed bar, the page of the
 * open tab, the six tabs, the sync screen, the toast and the Yes / No question. It draws the state of [OniSession];
 * all decisions are made there and in the core.
 */
@Composable
fun ServiceShell(session: OniSession, onLeave: () -> Unit) {
    val context = LocalContext.current
    DisposableEffect(session) {
        session.onLeave = onLeave
        session.urlOpener = { url -> runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } }
        onDispose { }
    }
    ProvideSession(session) {
        val th = session.theme
        BackHandler(enabled = session.pickerOpen || session.syncOpen || session.nav.canGoBack) {
            when {
                session.pickerOpen -> session.pickCancelled()
                session.syncOpen -> session.syncOpen = false
                else -> session.pop()
            }
        }
        Box(
            Modifier.fillMaxSize().background(th.bg).pointerInput(Unit) {
                // v1.2: a tap anywhere else hides a long-pressed row's revealed buttons (not the press that revealed them).
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                    val at = System.nanoTime()
                    val up = waitForUpOrCancellation(PointerEventPass.Initial)
                    if (up != null) session.pressedAt(at)
                }
            },
        ) {
            val compact = LocalConfiguration.current.screenHeightDp < 480      // phone on its side: tabs go to the left edge
            val body: @Composable (Modifier) -> Unit = { m ->
                Column(m) {
                    HeaderBar()
                    Box(Modifier.weight(1f).fillMaxWidth()) {
                        Column(Modifier.fillMaxSize()) {
                            SpeedBar()
                            Box(Modifier.weight(1f).fillMaxWidth().background(th.bg)) {
                                val top = session.nav.top
                                androidx.compose.runtime.key(top.id) { PageFor(top) }
                            }
                        }
                        if (session.syncOpen) SyncPageView()
                        Toast()
                    }
                    if (!compact) TabBar(false)
                }
            }
            if (compact) Row(Modifier.fillMaxSize()) { TabBar(true); body(Modifier.weight(1f).fillMaxHeight()) }
            else body(Modifier.fillMaxSize())
            AskBox()
            if (session.pickerOpen) ElementPickerView()
        }
    }
}

@Composable
private fun HeaderBar() {
    val s = LocalSession.current
    val th = s.theme
    val canBack = s.nav.canGoBack
    val game = if (s.connected) s.controls?.game else null
    Box(Modifier.fillMaxWidth().heightIn(min = 52.dp).background(th.header)) {
        SkinLayer("header")
        Row(Modifier.fillMaxWidth().heightIn(min = 52.dp), verticalAlignment = Alignment.CenterVertically) {
            if (canBack) {
                TapBox(Modifier.heightIn(min = 52.dp).widthIn(min = 90.bp), onTap = { s.pop() }) {
                    OText("‹  Back", Modifier.align(Alignment.Center).padding(horizontal = 16.bp), color = if (th.game) th.title else th.accent, weight = FontWeight.SemiBold)
                }
            }
            HeaderText(
                s.nav.current.label, Modifier.weight(1f).padding(start = if (canBack) 8.bp else 28.bp), color = th.title,
                weight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
            val info = s.sync
            if (!s.syncOpen && (info.state == "running" || info.needed || info.queued)) {
                val label = if (info.state == "running") (if (info.total > 0) "Syncing " + Math.round(100.0 * info.done / info.total) + "%" else "Syncing...")
                            else if (info.queued) "Sync waiting" else "Sync art & fonts"
                TapBox(
                    Modifier.padding(end = 10.bp).heightIn(min = 56.bp), base = th.accent.withAlpha(0.25f), shape = RoundedCornerShape(50),
                    border = BorderStroke(stroke(), th.accent), onTap = { s.openSync("") },
                ) {
                    OText(label, Modifier.padding(horizontal = 18.bp, vertical = 8.bp), size = SMALL, color = if (th.game) th.title else th.accent, weight = FontWeight.SemiBold, maxLines = 1)
                }
            }
            Row(Modifier.padding(end = 20.bp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.bp)) {
                val dot = when {
                    game == null -> th.bad
                    game.tone == "good" -> th.good
                    game.tone == "warn" -> th.warn
                    else -> th.muted
                }
                Box(Modifier.size(16.bp).background(dot, CircleShape))
                OText(
                    FatalText.headerState(s.connected, game?.label), Modifier.widthIn(max = 150.dp),
                    size = SMALL, color = if (th.game) th.title else th.muted, maxLines = 2, overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun SpeedBar() {
    val s = LocalSession.current
    val th = s.theme
    if (s.controlsHidden) return
    val c = s.controls
    val usable = s.connected && c != null && c.available
    val paused = SpeedLogic.paused(c, s.pendingBtn)
    val selected = SpeedLogic.selected(c, s.pendingBtn)
    Column(Modifier.fillMaxWidth().background(th.panel)) {
        Box(Modifier.fillMaxWidth().heightIn(min = 52.dp), contentAlignment = Alignment.Center) {
            Row(Modifier.alpha(if (usable) 1f else 0.38f), horizontalArrangement = Arrangement.spacedBy(14.bp)) {
                for (key in listOf("pause", "speed1", "speed2", "speed3")) {
                    val on = if (key == "pause") paused else selected == key.removePrefix("speed").toInt()
                    val sprite = rememberIcon(if (key == "pause") "speedPause" else key)
                    TapBox(
                        Modifier.size(width = 120.bp, height = 44.dp), enabled = usable,
                        base = if (on) th.accent.withAlpha(0.30f) else th.buttonNormal, hi = th.buttonPressed, shape = radius(),
                        border = BorderStroke(stroke(), if (on) th.accent else th.line),
                        onTap = { s.setSpeed(key) },
                    ) { pressed ->
                        if (!on) SkinLayer(if (pressed) "buttonPressed" else "button")
                        Box(Modifier.align(Alignment.Center)) {
                            if (sprite != null) Image(sprite, key, Modifier.size(44.bp), contentScale = ContentScale.Fit)
                            else SpeedGlyph(key, if (on) th.pageText else th.buttonText, 44.bp)
                        }
                    }
                }
            }
        }
        Box(Modifier.fillMaxWidth().height(hairline()).background(th.line))
    }
}

@Composable
private fun TabBar(rail: Boolean) {
    val s = LocalSession.current
    val th = s.theme
    if (rail) Column(Modifier.fillMaxHeight().railWidth(112.dp).background(th.tabBg)) {
        s.nav.tabs.indices.forEach { i -> TabItem(i, Modifier.weight(1f).fillMaxWidth()) }
    } else Row(Modifier.fillMaxWidth().background(th.tabBg)) {
        s.nav.tabs.indices.forEach { i -> TabItem(i, Modifier.weight(1f).heightIn(min = 56.dp)) }
    }
}

@Composable
private fun TabItem(i: Int, mod: Modifier) {
    val s = LocalSession.current
    val th = s.theme
    val nav = s.nav
    val t = nav.tabs[i]
    val on = nav.tab == i
    TapBox(mod, base = if (on) th.tabActiveBg else th.tabBg, onTap = { s.goTab(i) }) {
        SkinLayer(if (on) "tabActive" else "tab")
        if (on) Box(Modifier.align(Alignment.TopCenter).fillMaxWidth(0.5f).height(6.bp).clip(RoundedCornerShape(50)).background(th.accent))
        OText(
            t.label, Modifier.align(Alignment.Center).padding(horizontal = 2.dp), size = Fit.px(24, 21), color = if (on) th.tabTextActive else th.tabText,
            weight = if (on) FontWeight.Bold else FontWeight.Normal, maxLines = 1, overflow = TextOverflow.Ellipsis, align = TextAlign.Center,
        )
    }
}

/** Short messages, e.g. an action the game could not run, or why a button is greyed. */
@Composable
private fun Toast() {
    val s = LocalSession.current
    val th = s.theme
    if (s.toastText.isEmpty()) return
    Box(Modifier.fillMaxSize().padding(bottom = 24.bp), contentAlignment = Alignment.BottomCenter) {
        Box(
            Modifier.padding(horizontal = 32.bp).clip(radius()).background(if (s.toastBad) Color(0xFF3A1A1C) else th.panel)
                .border(stroke(), if (s.toastBad) th.bad else th.accent, radius()).tapNoRipple { s.clearToast() }.padding(horizontal = 28.bp, vertical = 16.bp),
        ) { OText(s.toastText, size = SMALL + 2, color = th.text, align = TextAlign.Center) }
    }
}

/** The Yes / No question (ask first). */
@Composable
private fun AskBox() {
    val s = LocalSession.current
    val th = s.theme
    val a = s.askState ?: return
    Box(Modifier.fillMaxSize().background(Color(0x99000000)).tapNoRipple { }, contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(horizontal = 48.bp).widthIn(max = 900.bp).clip(radius()).background(th.panel).border(stroke(), th.accent, radius()).padding(32.bp),
            verticalArrangement = Arrangement.spacedBy(28.bp),
        ) {
            OText(a.text, color = th.text)
            Row(horizontalArrangement = Arrangement.spacedBy(20.bp)) {
                Btn("Yes", primary = true, minWidth = 200.bp, onTap = { s.askState = null; a.yes() })
                Btn("No", minWidth = 200.bp, onTap = { s.askState = null })
            }
        }
    }
}
