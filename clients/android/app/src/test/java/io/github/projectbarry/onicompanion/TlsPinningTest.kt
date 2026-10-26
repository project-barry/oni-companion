package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.net.ApiClient
import io.github.projectbarry.onicompanion.net.ApiException
import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.net.PinMismatchException
import io.github.projectbarry.onicompanion.net.PinnedConnection
import io.github.projectbarry.onicompanion.net.Prober
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

/** A real TLS server with a self-signed certificate; checks the pin, the token and the 401 rule. */
class TlsPinningTest {
    private lateinit var server: MockWebServer
    private lateinit var cert: HeldCertificate
    private lateinit var fp: String

    @Before fun up() {
        cert = HeldCertificate.Builder().commonName("test-instance").ecdsa256().build()
        fp = Fingerprint.sha256Hex(cert.certificate.encoded)
        val hc = HandshakeCertificates.Builder().heldCertificate(cert).build()
        server = MockWebServer().apply { useHttps(hc.sslSocketFactory(), false); start() }
    }

    @After fun down() { server.shutdown() }

    private fun conn(pin: String, token: String? = "tok") = PinnedConnection(listOf(server.hostName), server.port, pin, token)

    @Test fun pinnedCertificateWorksAndTokenIsSent() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        val o = ApiClient(conn(fp)).get("/status")
        assertEquals("true", o["ok"].toString())
        val req = server.takeRequest()
        assertEquals("tok", req.getHeader("X-Oni-Device"))
        assertEquals("/api/v1/status", req.path)
        assertNull(req.getHeader("X-Oni-Token"))
    }

    @Test fun wrongCertificateGetsNoRequestAtAll() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        val other = Fingerprint.sha256Hex(HeldCertificate.Builder().ecdsa256().build().certificate.encoded)
        try {
            ApiClient(conn(other)).get("/status")
            fail("must not connect")
        } catch (e: PinMismatchException) { /* good */ }
        // The handshake failed, so the server never saw a request line, let alone the token.
        assertEquals(0, server.requestCount)
    }

    @Test fun probeReadsTheFingerprintFromTls() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"instanceId":"3f6c1b2e-8a4d-4c5e-9b7a-1d2e3f405162","name":"spiffy-raccoon","fingerprint":"${"0".repeat(64)}","fingerprintTag":"0000","apiVersion":1,"coreVersion":"1.4.0"}"""))
        val r = Prober.probe(server.hostName, server.port)
        assertEquals(fp, r.fingerprint)            // from the handshake, not the (lying) body
        assertEquals(Fingerprint.tag(fp), r.tag)
        assertEquals("spiffy-raccoon", r.identity?.name)
        assertNull(server.takeRequest().getHeader("X-Oni-Device"))
    }

    @Test fun errorBodyBecomesApiException() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"error":{"code":"unauthorized","message":"Not paired."}}"""))
        try { ApiClient(conn(fp)).get("/status"); fail() } catch (e: ApiException) {
            assertTrue(e.unauthorized); assertEquals("unauthorized", e.code)
        }
    }

    @Test fun eventsLongPollParses() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"seq":42,"changed":["colony","status"]}"""))
        val ev = ApiClient(conn(fp)).events(41, 1)
        assertEquals(42L, ev.seq); assertEquals(listOf("colony", "status"), ev.changed)
        assertTrue(server.takeRequest().path!!.startsWith("/api/v1/events?since=41"))
    }

    @Test fun postSendsJsonBodyAndDeleteWorks() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"seq":7}"""))
        server.enqueue(MockResponse().setBody("""{}"""))
        val api = ApiClient(conn(fp))
        api.post("/actions/focus", kotlinx.serialization.json.JsonObject(mapOf("x" to kotlinx.serialization.json.JsonPrimitive(1))))
        val r1 = server.takeRequest(); assertEquals("POST", r1.method); assertEquals("""{"x":1}""", r1.body.readUtf8())
        api.delete("/connect/devices/d-1"); assertEquals("DELETE", server.takeRequest().method)
    }

    @Test fun redirectsAreNotFollowed() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://evil.example/"))
        try { ApiClient(conn(fp)).get("/status"); fail() } catch (e: ApiException) { assertEquals(302, e.status) }
    }
}
