package io.github.projectbarry.onicompanion.ui

import android.app.Application
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.projectbarry.onicompanion.OniApp
import io.github.projectbarry.onicompanion.discovery.DiscoveryRepository
import io.github.projectbarry.onicompanion.discovery.NsdDiscovery
import io.github.projectbarry.onicompanion.net.ApiClient
import io.github.projectbarry.onicompanion.net.ApiException
import io.github.projectbarry.onicompanion.net.Connection
import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.net.LoopbackConnection
import io.github.projectbarry.onicompanion.net.PinMismatchException
import io.github.projectbarry.onicompanion.net.Prober
import io.github.projectbarry.onicompanion.net.UnreachableException
import io.github.projectbarry.onicompanion.pair.PairOutcome
import io.github.projectbarry.onicompanion.pair.Pairer
import io.github.projectbarry.onicompanion.pair.QrParser
import io.github.projectbarry.onicompanion.pair.QrResult
import io.github.projectbarry.onicompanion.session.OniSession
import io.github.projectbarry.onicompanion.store.Pairing
import android.net.Uri
import android.content.Intent
import io.github.projectbarry.onicompanion.net.LocalConnection
import io.github.projectbarry.onicompanion.local.LocalFresh
import io.github.projectbarry.onicompanion.local.LocalSession
import io.github.projectbarry.onicompanion.local.PythonLocalApi
import io.github.projectbarry.onicompanion.local.SafTree
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Where the user is. The view model holds all logic; the composables only draw this. */
sealed interface Route {
    data object Devices : Route
    /** Typing host and code by hand. */
    data class Manual(val host: String = "", val code: String = "") : Route
    /** Probed a typed address: the user compares name and tag with the Connect a phone window. */
    data class Confirm(val host: String, val port: Int, val code: String, val fingerprint: String, val name: String?) : Route
    data class Working(val text: String) : Route
    data class Message(val text: String, val cantVerify: Boolean = false, val title: String? = null) : Route
    /** Local mode set-up (4.2): which emulator app, its drive steps, and the folder picker. */
    data class LocalSetup(val emulator: String?) : Route
    /** Folder granted; waiting for the mod's first fresh write. */
    data class LocalWaiting(val emulator: String?) : Route
    data class Service(val title: String, val pairing: Pairing?) : Route
}

const val LOCAL_TITLE = "This device"

enum class LocalState { None, Granted, Fresh }

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val store = (app as OniApp).store
    val discovery = DiscoveryRepository(store, viewModelScope)
    private val nsd = NsdDiscovery(app, discovery::onFound, discovery::onLost)
    private val pairer = Pairer(store)

    var route by mutableStateOf<Route>(Route.Devices); private set
    var pairings by mutableStateOf(store.all()); private set
    var session by mutableStateOf<OniSession?>(null); private set
    private val localStore = (app as OniApp).localStore
    private var local: LocalSession? = null
    private var localJob: Job? = null
    private var autoOpened = false
    var localState by mutableStateOf(LocalState.None); private set
    var bottomScreen by mutableStateOf(localStore.bottomScreen); private set
    val emulators = listOf("Winlator", "GameNative", "GameHub", "Other")

    init { detectLocal() }

    private val phoneLabel get() = (Build.MODEL ?: "Android").take(40)

    fun startDiscovery() = nsd.start()
    fun stopDiscovery() { nsd.stop(); discovery.clear() }

    fun go(r: Route) { route = r }
    fun home() { closeSession(); stopLocal(); route = Route.Devices; detectLocal() }

    private fun reloadPairings() { pairings = store.all(); discovery.refresh() }

    // ---- pairing ----

    fun onQr(text: String) {
        when (val r = QrParser.parse(text)) {
            QrResult.NotOurs -> route = Route.Message(title = "Not an ONI Companion code", text = "That QR code is not from ONI Companion.")
            QrResult.UpdateApp -> route = Route.Message(title = "Update needed", text = "Update the app to pair with this device.")
            is QrResult.Bad -> route = Route.Message(title = "Can't use this code", text = "This QR code can't be used (${r.why}).")
            is QrResult.Ok -> {
                val p = r.payload
                route = Route.Working("Pairing with ${p.name} · ${Fingerprint.tag(p.fingerprint)}")
                viewModelScope.launch { finish(pairer.claim(p.addresses, p.port, p.fingerprint, p.instanceId, p.code, phoneLabel)) }
            }
        }
    }

    /** Step 1 of typed pairing: read the certificate so the user can compare its tag. */
    fun checkTyped(hostText: String, code: String) {
        val (host, port) = parseHostPort(hostText) ?: run { route = Route.Message(title = "Check the address", text = "Type the address like 192.168.1.20 or 192.168.1.20:47615."); return }
        route = Route.Working("Looking for $host")
        viewModelScope.launch {
            try {
                val pr = Prober.probe(host, port)
                route = Route.Confirm(host, port, code, pr.fingerprint, pr.identity?.name)
            } catch (e: Exception) {
                route = Route.Message(title = "Can't reach the device", text = "Can't reach $host:$port. Is Connect a phone on, and are both devices on the same network?")
            }
        }
    }

    /** Step 2: the user said the tag matches. The claim is pinned to the fingerprint just shown. */
    fun confirmTyped(c: Route.Confirm) {
        route = Route.Working("Pairing")
        viewModelScope.launch { finish(pairer.claim(listOf(c.host), c.port, c.fingerprint, null, c.code, phoneLabel)) }
    }

    private fun finish(o: PairOutcome) {
        reloadPairings()
        when (o) {
            is PairOutcome.Paired -> open(o.pairing)
            is PairOutcome.Failed -> route = Route.Message(o.message, o.cantVerify)
        }
    }

    /** The device was reset (or replaced): drop the old pairing and go to typed pairing with its address filled in. */
    fun pairAgain(p: Pairing) {
        forget(p); closeSession()
        route = Route.Manual(p.hosts.firstOrNull()?.let { "$it:${p.port}" } ?: "", "")
    }

    fun forget(p: Pairing) { store.remove(p.fingerprint); reloadPairings() }

    fun parseHostPort(text: String): Pair<String, Int>? {
        val t = text.trim()
        if (t.isEmpty() || t.any { it.isWhitespace() || it == '/' }) return null
        if (t.startsWith("[")) {
            val end = t.indexOf(']'); if (end < 0) return null
            val port = t.substring(end + 1).removePrefix(":").ifEmpty { "47615" }.toIntOrNull() ?: return null
            return t.substring(1, end) to port
        }
        if (t.count { it == ':' } > 1) return t to 47615   // bare IPv6
        val host = t.substringBefore(':')
        val port = t.substringAfter(':', "47615").toIntOrNull() ?: return null
        return if (host.isEmpty() || port !in 1..65535) null else host to port
    }

    // ---- service view ----

    fun open(p: Pairing) { openConnection(p.title, p, p.connection()) }

    /** Debug builds only: a plain-HTTP loopback service reached through adb reverse. */
    fun openLoopback(port: Int, token: String) =
        openConnection("This phone (127.0.0.1:$port)", null, LoopbackConnection("127.0.0.1", port, token))

    private fun openConnection(title: String, p: Pairing?, conn: Connection) {
        closeSession()
        route = Route.Service(title, p)
        val key = p?.fingerprint ?: "loopback"
        val sess = OniSession(ApiClient(conn), viewModelScope, getApplication<Application>().cacheDir, key.take(16))
        session = sess
        sess.start()
    }

    private fun closeSession() { session?.stop(); session = null }

    override fun onCleared() { nsd.stop(); closeSession(); stopLocal() }

    // ---- local mode (plan 4.2) ----

    private val ctx get() = getApplication<Application>()

    private fun grantedTree(): Uri? {
        val u = localStore.treeUri ?: return null
        val ok = ctx.contentResolver.persistedUriPermissions.any { it.uri == u && it.isReadPermission && it.isWritePermission }
        return if (ok) u else null
    }

    /** Looks at the granted folder once: no grant, a grant with no fresh files, or a game that is writing now. */
    fun detectLocal(openIfFresh: Boolean = true) {
        val tree = grantedTree() ?: run { localState = LocalState.None; return }
        viewModelScope.launch {
            val fresh = withContext(Dispatchers.IO) {
                val fs = SafTree(ctx.contentResolver, tree)
                LocalFresh.isMarker(fs.read("marker.json")) && LocalFresh.fresh(fs.read("companion/live/live.json"), System.currentTimeMillis())
            }
            localState = if (fresh) LocalState.Fresh else LocalState.Granted
            if (fresh && openIfFresh && route == Route.Devices && !autoOpened) { autoOpened = true; openLocal() }
        }
    }
    fun startLocalSetup(emulator: String? = localStore.emulator) { localStore.emulator = emulator; route = Route.LocalSetup(emulator) }
    fun chooseEmulator(name: String) { localStore.emulator = name; route = Route.LocalSetup(name) }

    fun changeBottomScreen(on: Boolean) { localStore.bottomScreen = on; bottomScreen = on }

    /** The user picked the ONICompanion folder in the system picker. */
    fun onTreePicked(uri: Uri?, flags: Int) {
        if (uri == null) return
        val name = Uri.decode(uri.lastPathSegment ?: "").substringAfterLast(':').substringAfterLast('/')
        if (name != "ONICompanion") {
            route = Route.Message(title = "Wrong folder", text = "Pick the folder named ONICompanion. Create it in the picker if it is not there: open the menu, choose New folder, name it ONICompanion, then Use this folder.")
            return
        }
        val take = flags and (Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        try { ctx.contentResolver.takePersistableUriPermission(uri, take) } catch (e: SecurityException) { route = Route.Message(title = "Folder not kept", text = "Android did not keep access to the folder. Try again."); return }
        localStore.treeUri = uri
        val emu = localStore.emulator
        route = Route.LocalWaiting(emu)
        viewModelScope.launch {
            withContext(Dispatchers.IO) { SafTree(ctx.contentResolver, uri).ensureMarker("1.4.0", emu) }
            openLocal(waitForGame = true)
        }
    }

    fun openLocal(waitForGame: Boolean = false) {
        val tree = grantedTree() ?: run { startLocalSetup(); return }
        closeSession(); stopLocal()
        if (!waitForGame) route = Route.Service(LOCAL_TITLE, null)
        localJob = viewModelScope.launch {
            val ls = withContext(Dispatchers.IO) {
                LocalSession(ctx, SafTree(ctx.contentResolver, tree), PythonLocalApi.load(ctx)).also { it.start() }
            }
            local = ls
            val api = ApiClient(LocalConnection(ls.api))
            if (waitForGame) {
                // Set-up screen stays until the mod's files are fresh. Events wake this; nothing polls.
                var seq = 0L
                while (true) {
                    val fresh = runCatching { api.get("/status")["mod"]?.jsonObject?.get("liveFresh")?.jsonPrimitive?.boolean }.getOrNull() == true
                    if (fresh) break
                    val next = runCatching { api.events(seq).seq }.getOrDefault(seq)
                    if (next == seq) delay(500)          // never spin if the bus has not moved
                    seq = next
                }
                route = Route.Service(LOCAL_TITLE, null)
            }
            val sess = OniSession(api, viewModelScope, ctx.cacheDir, "local")
            session = sess
            sess.start()
        }
    }

    /** Debug builds only: "GET /status" or "POST /actions/focus {json}" against the local core; the answer goes to logcat (tag OniLocal). */
    fun debugLocalCall(spec: String) {
        viewModelScope.launch(Dispatchers.IO) {
            var waited = 0
            while (local == null && waited++ < 100) delay(100)       // the session starts a moment after the app does
            val api = local?.api ?: run { android.util.Log.i("OniLocal", "no local session"); return@launch }
            val parts = spec.split(" ", limit = 3)
            val r = api.call(parts[0], parts[1], parts.getOrNull(2))
            android.util.Log.i("OniLocal", "${parts[0]} ${parts[1]} -> ${r.status} ${r.body.decodeToString().take(600)}")
        }
    }

    fun refreshLocal() { local?.refresh() }

    /** The app went to the background / came back: local mode runs only while the app is on screen. */
    fun appVisible(visible: Boolean) {
        if (visible) {
            if (local == null && route is Route.Service && (route as Route.Service).title == LOCAL_TITLE) openLocal()
            (route as? Route.LocalWaiting)?.let { if (local == null) openLocal(waitForGame = true) }
            local?.refresh()
        } else if (local != null) {
            closeSession(); stopLocal()
        }
    }

    private fun stopLocal() { localJob?.cancel(); localJob = null; local?.stop(); local = null }
}
