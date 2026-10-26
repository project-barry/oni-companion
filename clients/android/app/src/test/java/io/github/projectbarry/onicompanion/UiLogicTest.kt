package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.net.ApiJson
import io.github.projectbarry.onicompanion.screen.Block
import io.github.projectbarry.onicompanion.screen.Ref
import io.github.projectbarry.onicompanion.screen.ScreenParser
import io.github.projectbarry.onicompanion.session.Controls
import io.github.projectbarry.onicompanion.session.LookupEntry
import io.github.projectbarry.onicompanion.session.NavState
import io.github.projectbarry.onicompanion.session.ScreenEntry
import io.github.projectbarry.onicompanion.session.SpeedLogic
import io.github.projectbarry.onicompanion.session.SyncInfo
import io.github.projectbarry.onicompanion.session.Tab
import io.github.projectbarry.onicompanion.theme.GameTheme
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

class UiLogicTest {
    private fun obj(s: String) = ApiJson.parseToJsonElement(s).jsonObject

    // ---- back stacks, one per tab ----
    @Test fun stacksAreKeptPerTab() {
        var n = NavState.initial()
        assertEquals(6, n.tabs.size)
        n = n.push("entry/building/Ladder").push("entry/element/Water")
        assertEquals(3, n.stacks[0].size)
        n = n.goTab(2)
        assertEquals(1, n.stacks[2].size)
        n = n.goTab(0)
        assertEquals("entry/element/Water", (n.top as ScreenEntry).path)
        n = n.pop()
        assertEquals("entry/building/Ladder", (n.top as ScreenEntry).path)
    }

    @Test fun tappingTheOpenTabGoesToItsFirstPage() {
        var n = NavState.initial().push("a").push("b")
        n = n.goTab(0)
        assertFalse(n.canGoBack)
        assertEquals(0, n.tab)
    }

    @Test fun databaseTabIsTheLookupPage() {
        val n = NavState.initial()
        val e = n.stacks[4][0]
        assertTrue(e is LookupEntry)
        assertEquals(listOf("building"), (e as LookupEntry).excludeKinds)
        assertTrue(e.tools)
        assertTrue((n.stacks[5][0] as ScreenEntry).closeBar)     // Settings
    }

    @Test fun newTabsFromTheCoreRestartTheStacks() {
        val n = NavState.initial().push("x")
        val same = n.withTabs(n.tabs)
        assertEquals(n, same)
        val m = n.withTabs(listOf(Tab("colony", "Colony", "colony"), Tab("settings", "Settings", "settings")))
        assertEquals(2, m.tabs.size)
        assertEquals(1, m.stacks[0].size)
    }

    @Test fun refsOpenEntryPages() {
        val n = NavState.initial().openRef(Ref("building", "Ladder & Co"))
        assertEquals("entry/building/Ladder%20%26%20Co", (n.top as ScreenEntry).path)
    }

    // ---- speed bar ----
    @Test fun speedBarFollowsTheGameAndShowsPressesAtOnce() {
        val running = Controls.parse(obj("""{"available":true,"paused":false,"speed":2,"game":{"state":"running","label":"Running","tone":"good"}}"""))
        assertEquals(2, SpeedLogic.selected(running, ""))
        assertFalse(SpeedLogic.paused(running, ""))
        assertTrue(SpeedLogic.paused(running, "pause"))               // a toggle: shows the opposite at once
        assertEquals(3, SpeedLogic.selected(running, "speed3"))
        val pausedC = Controls.parse(obj("""{"available":true,"paused":true,"speed":1}"""))
        assertTrue(SpeedLogic.paused(pausedC, ""))
        assertFalse(SpeedLogic.paused(pausedC, "pause"))
        assertEquals("pause", SpeedLogic.body(running, "pause")["state"].toString().trim('"'))
        assertEquals("play", SpeedLogic.body(pausedC, "pause")["state"].toString().trim('"'))
        assertEquals("3", SpeedLogic.body(running, "speed3")["speed"].toString())
        assertEquals("Running", running.game?.label)
        val off = Controls.parse(obj("""{"available":false,"game":{"state":"not_running","label":"Game not running","tone":"neutral"}}"""))
        assertEquals(0, SpeedLogic.selected(off, ""))
    }

    // ---- theme ----
    @Test fun colorsReadEightDigitHexAsRrggbbaa() {
        val c = GameTheme.color("#11223380")!!
        assertEquals(0x11 / 255f, c.red, 0.01f); assertEquals(0x80 / 255f, c.alpha, 0.01f)
        assertNull(GameTheme.color("red"))
    }

    @Test fun themeKeepsBuiltInValuesForMissingTokens() {
        val t = GameTheme.fromJson(obj("""{"source":"game","colors":{"background":"#494949","textTitle":"#FFFFFF"},
            "slices":[{"name":"panel","art":"/api/v1/art/ui/panel","width":9,"height":9,"insets":{"left":3,"top":3,"right":3,"bottom":3}}],
            "icons":[{"name":"speed1","art":"/api/v1/art/ui/s1","width":16,"height":16}],
            "font":{"roles":{"body":{"family":"Roboto","font":"Roboto-Regular","fallback":["Noto Sans"]}}}}"""))
        assertTrue(t.game)
        assertEquals(GameTheme().accent, t.accent)
        assertNotNull(t.slice("panel")); assertNotNull(t.icon("speed1"))
        assertEquals("Roboto", t.roles["body"]?.family)
        assertEquals(4, t.radiusUnits)
        assertEquals(20, GameTheme().radiusUnits)
    }

    // ---- sync info ----
    @Test fun syncInfoReadsTheCoreReply() {
        val s = SyncInfo.parse(obj("""{"state":"running","done":10,"total":40,"current":"Ladder","errors":1,"queued":false,"canStart":true}"""))
        assertEquals("running", s.state); assertEquals(10, s.done); assertEquals(40, s.total); assertTrue(s.canStart)
    }

    // ---- block types ----
    @Test fun everyBlockTypeHasAParser() {
        val types = listOf(
            """{"type":"heading","text":"A","level":1}""", """{"type":"text","spans":[{"type":"bold","text":"x","color":"warning"}]}""",
            """{"type":"stats","rows":[{"label":"a","value":1.0}]}""", """{"type":"chips","chips":[{"label":"x","style":"dlc"}]}""",
            """{"type":"list","items":[{"title":"t"}]}""", """{"type":"grid","cards":[{"title":"c"}]}""",
            """{"type":"grid","variant":"pad","cards":[{"title":"c","actions":[{"id":"x","label":"y"}]}]}""",
            """{"type":"ports","inputs":[],"outputs":[]}""", """{"type":"phases","states":[]}""",
            """{"type":"progress","label":"a","value":1,"max":2}""", """{"type":"table","columns":["a"],"rows":[["x"]]}""",
            """{"type":"notice","text":"n"}""", """{"type":"form","tool":"t","submitLabel":"Go","fields":[]}""",
            """{"type":"link","label":"l","url":"https://a.b"}""", """{"type":"divider"}""",
            """{"type":"group","title":"g","blocks":[]}""", """{"type":"image","art":"/api/v1/art/ui/x"}""",
            """{"type":"picker","slots":[],"action":{"id":"build","label":"Build"}}""",
        )
        for (t in types) assertFalse(t, ScreenParser.block(ApiJson.parseToJsonElement(t)) is Block.Unknown)
        assertTrue(ScreenParser.block(ApiJson.parseToJsonElement("""{"type":"from-the-future"}""")) is Block.Unknown)
    }

    @Test fun everySyntheticScreenParsesWithoutUnknownBlocks() {
        val found = findFixtures()
        assumeTrue("fixtures/synthetic/screens not found", found != null)
        val dir: File = found!!
        var seen = 0
        for (f in dir.listFiles { x -> x.name.endsWith(".json") }!!.sortedBy { it.name }) {
            val o = ApiJson.parseToJsonElement(f.readText()).jsonObject
            if (o["blocks"] == null) continue
            seen++
            fun check(blocks: List<Block>): Unit = blocks.forEach {
                assertFalse(f.name + " has an unknown block", it is Block.Unknown)
                if (it is Block.Group) check(it.blocks)
            }
            check(ScreenParser.parse(o).blocks)
        }
        assertTrue(seen > 10)
    }

    private fun findFixtures(): File? {
        var d: File? = File(System.getProperty("user.dir")).absoluteFile
        repeat(6) {
            val c = File(d, "fixtures/synthetic/screens")
            if (c.isDirectory) return c
            d = d?.parentFile
        }
        return null
    }
}
