package io.github.projectbarry.onicompanion.net

import okhttp3.OkHttpClient
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** The server's certificate is not the one that was pinned. */
class PinMismatchException(message: String) : CertificateException(message)

/**
 * Accepts exactly one certificate: the one whose SHA-256 fingerprint equals the pinned value.
 * No CA, no host name, no date check: the pin is the identity (plan 4.1). The check runs in
 * the TLS handshake, so no request byte (and no device token) is sent before it passes.
 */
class PinnedTrustManager(private val pin: String) : X509TrustManager {
    init { require(Fingerprint.isValid(pin.lowercase())) { "pin must be 64 hex digits" } }

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        if (chain.isNullOrEmpty()) throw PinMismatchException("no certificate")
        val fp = Fingerprint.sha256Hex(chain[0].encoded)
        if (!Fingerprint.same(fp, pin)) throw PinMismatchException("certificate is not the pinned one")
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("client certificates are not used")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

/**
 * Accepts any certificate and only records its fingerprint. Used ONLY by [Prober] to read
 * the public GET /identity of a service we have not pinned yet; it never carries a token or a
 * pairing code (those go through a pinned client).
 */
class CapturingTrustManager : X509TrustManager {
    @Volatile var fingerprint: String? = null
        private set

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        if (chain.isNullOrEmpty()) throw CertificateException("no certificate")
        fingerprint = Fingerprint.sha256Hex(chain[0].encoded)
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("client certificates are not used")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

object Tls {
    private fun base(): OkHttpClient.Builder = OkHttpClient.Builder()
        .followRedirects(false)
        .followSslRedirects(false)
        .retryOnConnectionFailure(false)
        .connectTimeout(java.time.Duration.ofSeconds(4))
        .readTimeout(java.time.Duration.ofSeconds(15))

    private fun withTrust(tm: X509TrustManager): OkHttpClient.Builder {
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(tm), SecureRandom())
        // The certificate has no usable host name; the pin (or the capture) is what counts.
        return base().sslSocketFactory(ctx.socketFactory, tm).hostnameVerifier { _, _ -> true }
    }

    fun pinnedClient(pin: String): OkHttpClient = withTrust(PinnedTrustManager(pin)).build()

    fun captureClient(): Pair<OkHttpClient, CapturingTrustManager> {
        val tm = CapturingTrustManager()
        return withTrust(tm).build() to tm
    }

    /** A client for loopback plain HTTP (dev/local mode); never used for a network address. */
    fun plainClient(): OkHttpClient = base().build()
}
