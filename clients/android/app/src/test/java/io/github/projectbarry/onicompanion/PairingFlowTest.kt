package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.pair.PairOutcome
import io.github.projectbarry.onicompanion.pair.Pairer
import io.github.projectbarry.onicompanion.store.AesGcmBox
import io.github.projectbarry.onicompanion.store.PairingStore
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import javax.crypto.KeyGenerator

class PairingFlowTest {
    @get:Rule val tmp = TemporaryFolder()
    private lateinit var server: MockWebServer
    private lateinit var fp: String
    private lateinit var store: PairingStore

    private fun identityJson(f: String) = """{"instanceId":"3f6c1b2e-8a4d-4c5e-9b7a-1d2e3f405162","name":"spiffy-raccoon","fingerprint":"$f","fingerprintTag":"${Fingerprint.tag(f)}","apiVersion":1,"coreVersion":"1.4.0"}"""

    @Before fun up() {
        val cert = HeldCertificate.Builder().ecdsa256().build()
        fp = Fingerprint.sha256Hex(cert.certificate.encoded)
        server = MockWebServer().apply { useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory(), false); start() }
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        store = PairingStore(tmp.newFile("p.bin").also { it.delete() }, AesGcmBox { key })
    }

    @After fun down() { server.shutdown() }

    private fun claimOk() = MockResponse().setBody("""{"deviceToken":"q3Zk8m1xV0c2Lw7yT9bN4pRfHsJdAeUo5GiXtYvCnMa","deviceId":"d-a1b2c3d4e5f6","identity":${identityJson(fp)}}""")

    @Test fun goodClaimStoresPairingPerService() = runBlocking {
        server.enqueue(claimOk())
        val o = Pairer(store).claim(listOf(server.hostName), server.port, fp, null, "abcd-efgh", "Pixel")
        assertTrue(o is PairOutcome.Paired)
        val req = server.takeRequest()
        assertEquals("/api/v1/connect/claim", req.path)
        assertTrue(req.body.readUtf8().contains("abcd-efgh"))
        assertEquals(null, req.getHeader("X-Oni-Device"))
        val p = store.byFingerprint(fp)!!
        assertEquals("spiffy-raccoon · ${Fingerprint.tag(fp)}", p.title)
        assertEquals("q3Zk8m1xV0c2Lw7yT9bN4pRfHsJdAeUo5GiXtYvCnMa", p.deviceToken)
    }

    @Test fun impostorWithOtherKeyNeverSeesTheCode() = runBlocking {
        val wrongPin = Fingerprint.sha256Hex(HeldCertificate.Builder().ecdsa256().build().certificate.encoded)
        server.enqueue(claimOk())
        val o = Pairer(store).claim(listOf(server.hostName), server.port, wrongPin, null, "ABCDEFGH", "Pixel")
        assertTrue(o is PairOutcome.Failed && o.cantVerify)
        assertEquals(0, server.requestCount)
        assertTrue(store.all().isEmpty())
    }

    @Test fun lyingBodyFingerprintIsRefused() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"deviceToken":"q3Zk8m1xV0c2Lw7yT9bN4pRfHsJdAeUo5GiXtYvCnMa","deviceId":"d-a1b2c3d4e5f6","identity":${identityJson("1".repeat(64))}}"""))
        val o = Pairer(store).claim(listOf(server.hostName), server.port, fp, null, "ABCDEFGH", "Pixel")
        assertTrue(o is PairOutcome.Failed && o.cantVerify)
        assertTrue(store.all().isEmpty())
    }

    @Test fun badCodeAndRateLimitMessages() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"error":{"code":"bad_code","message":"x"}}"""))
        server.enqueue(MockResponse().setResponseCode(429).setBody("""{"error":{"code":"rate_limited","message":"x"}}"""))
        val pr = Pairer(store)
        val a = pr.claim(listOf(server.hostName), server.port, fp, null, "ABCDEFGH", "P") as PairOutcome.Failed
        assertTrue(a.message.contains("wrong, expired or already used"))
        val b = pr.claim(listOf(server.hostName), server.port, fp, null, "ABCDEFGH", "P") as PairOutcome.Failed
        assertTrue(b.message.contains("Too many"))
    }

    @Test fun storeRoundTripsEncryptedAndReplaces() {
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val f = tmp.newFile("q.bin").also { it.delete() }
        val s = PairingStore(f, AesGcmBox { key })
        val p = io.github.projectbarry.onicompanion.store.Pairing("i", "spiffy-raccoon", fp, listOf("1.2.3.4"), 47615, "SECRETTOKEN", "d-1", "t")
        s.put(p); s.put(p.copy(deviceToken = "NEWTOKEN"))
        val again = PairingStore(f, AesGcmBox { key }).all()
        assertEquals(1, again.size); assertEquals("NEWTOKEN", again[0].deviceToken)
        assertTrue(!String(f.readBytes(), Charsets.ISO_8859_1).contains("NEWTOKEN"))   // not plain text on disk
        // a lost key reads as empty, never as garbage
        val other = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        assertTrue(PairingStore(f, AesGcmBox { other }).all().isEmpty())
        s.remove(fp); assertTrue(PairingStore(f, AesGcmBox { key }).all().isEmpty())
    }
}
