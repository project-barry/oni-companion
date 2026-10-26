package io.github.projectbarry.onicompanion.net

import java.security.MessageDigest

/** The SHA-256 fingerprint of a service's DER certificate is its real identity (plan 4.1). */
object Fingerprint {
    private val HEX64 = Regex("^[0-9a-f]{64}$")

    fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    fun isValid(fp: String) = HEX64.matches(fp)

    /** First 4 hex digits, uppercase: the short tag shown in lists ("spiffy-raccoon · 7F3A"). */
    fun tag(fp: String) = fp.take(4).uppercase()

    /** Constant-time comparison of two fingerprints (case-insensitive). */
    fun same(a: String, b: String) =
        MessageDigest.isEqual(a.lowercase().toByteArray(), b.lowercase().toByteArray())
}
