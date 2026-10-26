package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.discovery.Announced
import io.github.projectbarry.onicompanion.discovery.Classifier
import io.github.projectbarry.onicompanion.discovery.Probe
import io.github.projectbarry.onicompanion.discovery.Trust
import io.github.projectbarry.onicompanion.net.ApiJson
import io.github.projectbarry.onicompanion.pair.QrParser
import io.github.projectbarry.onicompanion.pair.QrResult
import io.github.projectbarry.onicompanion.screen.Block
import io.github.projectbarry.onicompanion.screen.ScreenParser
import io.github.projectbarry.onicompanion.store.Pairing
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class LogicTest {
    private val fpA = "a4cc369e78ac5d4cdffd1aedb7d96950d667720032b8e5d9588ae72866331434"
    private val fpB = "7f3a000000000000000000000000000000000000000000000000000000000000"
    private val id = "3f6c1b2e-8a4d-4c5e-9b7a-1d2e3f405162"

    private fun qr(v: Int = 1, t: String = "onic-pair", f: String = fpA, c: String = "ABCD2345") =
        """{"v":$v,"t":"$t","a":["192.168.1.20","100.64.0.5"],"p":47615,"c":"$c","i":"$id","f":"$f","n":"spiffy-raccoon","x":"2026-10-25T12:05:00Z"}"""

    @Test fun qrParses() {
        val r = QrParser.parse(qr()) as QrResult.Ok
        assertEquals(listOf("192.168.1.20", "100.64.0.5"), r.payload.addresses)
        assertEquals(47615, r.payload.port); assertEquals(fpA, r.payload.fingerprint)
        assertTrue(r.payload.isExpired(Instant.parse("2026-10-25T12:06:00Z")))
        assertTrue(!r.payload.isExpired(Instant.parse("2026-10-25T12:00:00Z")))
    }

    @Test fun qrRejects() {
        assertEquals(QrResult.NotOurs, QrParser.parse("https://example.com"))
        assertEquals(QrResult.NotOurs, QrParser.parse(qr(t = "other")))
        assertEquals(QrResult.UpdateApp, QrParser.parse(qr(v = 2)))
        assertTrue(QrParser.parse(qr(f = "abc")) is QrResult.Bad)
        assertTrue(QrParser.parse(qr(c = "ABCD0O1I")) is QrResult.Bad)
        assertTrue(QrParser.parse(qr().replace("192.168.1.20", "a/b")) is QrResult.Bad)
    }

    private fun ann(name: String = "spiffy-raccoon", i: String = id, host: String = "192.168.1.20") =
        Announced("ONI Companion on $name", i, name, "1", "1.4.0", host, 47615)

    private fun pairing(fp: String = fpA, i: String = id) = Pairing(i, "spiffy-raccoon", fp, listOf("10.0.0.9"), 47615, "t", "d-1", "x")

    @Test fun classification() {
        val p = listOf(pairing())
        assertEquals(Trust.Checking, Classifier.classify(ann(), Probe.Pending, p).trust)
        assertEquals(Trust.Unreachable, Classifier.classify(ann(), Probe.Unreachable, p).trust)
        val paired = Classifier.classify(ann(), Probe.Seen(fpA), p)
        assertEquals(Trust.Paired, paired.trust); assertEquals("spiffy-raccoon · A4CC", paired.title)
        // same certificate at a new address is still Paired
        assertEquals(Trust.Paired, Classifier.classify(ann(host = "192.168.1.99"), Probe.Seen(fpA), p).trust)
        // copies the paired name AND id but has another key
        val fake = Classifier.classify(ann(), Probe.Seen(fpB), p)
        assertEquals(Trust.CantVerify, fake.trust); assertEquals("spiffy-raccoon · 7F3A", fake.title)
        // same name, other id, other key: just a different new device
        assertEquals(Trust.New, Classifier.classify(ann(i = "other-id"), Probe.Seen(fpB), p).trust)
        assertEquals(Trust.New, Classifier.classify(ann(), Probe.Seen(fpB), emptyList()).trust)
    }

    @Test fun twoServicesWithTheSameNameStaySeparate() {
        val a = Classifier.classify(ann(i = "x1"), Probe.Seen(fpA), emptyList())
        val b = Classifier.classify(ann(i = "x2", host = "192.168.1.21"), Probe.Seen(fpB), emptyList())
        val dup = Classifier.classify(ann(i = "x1", host = "fe80-other-iface"), Probe.Seen(fpA), emptyList())
        assertEquals(2, Classifier.merge(listOf(a, b, dup)).size)
    }

    @Test fun screenTextBlocks() {
        val o = ApiJson.parseToJsonElement("""{"schema":1,"title":"Colony","subtitle":"Cycle 12","refreshOn":["colony"],"blocks":[
          {"type":"heading","text":"H"},
          {"type":"text","spans":[{"type":"plain","text":"a "},{"type":"bold","text":"b"},{"type":"ref","ref":{"kind":"element","id":"Water"},"text":"Water"}]},
          {"type":"stats","rows":[{"label":"Cycle","value":12},{"label":"Temp","value":20.5,"unit":"C"}]},
          {"type":"notice","level":"warn","text":"careful"},
          {"type":"group","title":"G","collapsed":true,"blocks":[{"type":"divider"}]},
          {"type":"hologram"}]}""").jsonObject
        val s = ScreenParser.parse(o)
        assertEquals("Colony", s.title); assertEquals(setOf("colony"), s.refreshOn)
        assertEquals(6, s.blocks.size)
        assertEquals("a bWater", (s.blocks[1] as Block.Text).spans.joinToString("") { it.text })
        assertEquals("20.5 C", (s.blocks[2] as Block.Stats).rows[1].value)
        assertTrue((s.blocks[4] as Block.Group).collapsed)
        assertEquals(Block.Unknown("hologram"), s.blocks[5])
    }
}
