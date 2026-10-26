package io.github.projectbarry.onicompanion.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val ApiJson = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }

@Serializable
data class Identity(
    val instanceId: String,
    val name: String,
    val fingerprint: String,
    val fingerprintTag: String,
    val apiVersion: Int = 1,
    val coreVersion: String = "",
)

@Serializable
data class ClaimPost(val code: String, val label: String, val platform: String = "android")

@Serializable
data class ClaimReply(val deviceToken: String, val deviceId: String, val identity: Identity)

@Serializable
data class EventsReply(val seq: Long, val changed: List<String> = emptyList())
