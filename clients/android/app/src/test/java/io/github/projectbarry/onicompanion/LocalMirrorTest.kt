package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.local.FileSharedFs
import io.github.projectbarry.onicompanion.local.LocalFresh
import io.github.projectbarry.onicompanion.local.Mirror
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.Instant

class LocalMirrorTest {
    private lateinit var tmp: File
    private lateinit var shared: File
    private lateinit var priv: File
    private val events = ArrayList<String>()
    private lateinit var mirror: Mirror

    @Before fun setUp() {
        tmp = Files.createTempDirectory("a3").toFile()
        shared = File(tmp, "shared").apply { mkdirs() }
        priv = File(tmp, "priv").apply { mkdirs() }
        mirror = Mirror(FileSharedFs(shared), priv) { f, removed -> events.add((if (removed) "-" else "+") + f.name) }
    }
    @After fun tearDown() { tmp.deleteRecursively() }

    private fun put(rel: String, text: String) { File(shared, rel).apply { parentFile.mkdirs() }.writeText(text) }

    @Test fun modFilesComeDownAndAreReportedOnce() {
        put("companion/live/live.json", "{\"a\":1}")
        put("companion/export/gamedata-1.json", "{}")
        put("companion/art/p.png.tmp", "half")
        mirror.syncDown()
        assertEquals("{\"a\":1}", File(priv, "live/live.json").readText())
        assertTrue(File(priv, "export/gamedata-1.json").exists())
        assertFalse(File(priv, "art/p.png.tmp").exists())
        assertEquals(setOf("+live.json", "+gamedata-1.json"), events.toSet())
        events.clear()
        mirror.syncDown()                                   // nothing changed: no copy, no event
        assertTrue(events.isEmpty())
        put("companion/live/live.json", "{\"a\":22}")       // size changes: copied again
        mirror.syncDown()
        assertEquals(listOf("+live.json"), events)
    }

    @Test fun filesTheModDeletedAreDeletedHere() {
        put("companion/acks/ack-1.json", "{}")
        mirror.syncDown(); events.clear()
        File(shared, "companion/acks/ack-1.json").delete()
        mirror.syncDown()
        assertFalse(File(priv, "acks/ack-1.json").exists())
        assertEquals(listOf("-ack-1.json"), events)
    }

    @Test fun commandsGoUpOnceAndAreDroppedWhenTheModConsumesThem() {
        put("companion/live/live.json", "{}")
        mirror.syncDown()
        File(priv, "commands").mkdirs()
        File(priv, "commands/cmd-5.json").writeText("{\"seq\":5}")
        File(priv, "commands/cmd-6.json.tmp").writeText("half")
        assertEquals(1, mirror.syncUp())
        assertEquals("{\"seq\":5}", File(shared, "companion/commands/cmd-5.json").readText())
        assertFalse(File(shared, "companion/commands/cmd-6.json.tmp").exists())
        assertEquals(0, mirror.syncUp())
        File(shared, "companion/commands/cmd-5.json").delete()   // the mod took it
        mirror.syncDown()
        assertFalse(File(priv, "commands/cmd-5.json").exists())
        assertTrue(File(shared, "companion/commands").list()!!.isEmpty())
    }

    @Test fun anExpiredCommandIsPulledBackFromTheSharedFolder() {
        File(priv, "commands").mkdirs()
        File(priv, "commands/cmd-9.json").writeText("{}")
        mirror.syncUp()
        File(priv, "commands/cmd-9.json").delete()
        mirror.syncUp()
        assertFalse(File(shared, "companion/commands/cmd-9.json").exists())
    }

    @Test fun freshness() {
        val now = Instant.parse("2026-10-25T12:00:30Z").toEpochMilli()
        fun live(at: String, paused: Boolean = false, state: String = "running") =
            "{\"state\":\"$state\",\"writtenAt\":\"$at\",\"paused\":$paused}".toByteArray()
        assertTrue(LocalFresh.fresh(live("2026-10-25T12:00:20Z"), now))
        assertFalse(LocalFresh.fresh(live("2026-10-25T12:00:00Z"), now))                 // 30 s old, running
        assertTrue(LocalFresh.fresh(live("2026-10-25T12:00:00Z", paused = true), now))   // paused: 180 s window
        assertFalse(LocalFresh.fresh(live("2026-10-25T12:00:20Z", state = "menu"), now))
        assertFalse(LocalFresh.fresh("nope".toByteArray(), now))
        assertFalse(LocalFresh.fresh(null, now))
    }

    @Test fun markerCheck() {
        assertTrue(LocalFresh.isMarker("{\"schema\":1,\"app\":\"oni-companion\",\"createdAt\":\"2026-10-25T00:00:00Z\"}".toByteArray()))
        assertFalse(LocalFresh.isMarker("{\"schema\":1,\"app\":\"other\"}".toByteArray()))
        assertFalse(LocalFresh.isMarker(null))
    }
}
