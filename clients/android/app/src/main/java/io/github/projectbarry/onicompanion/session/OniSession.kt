package io.github.projectbarry.onicompanion.session

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.projectbarry.onicompanion.art.ArtRepo
import io.github.projectbarry.onicompanion.art.FontRepo
import io.github.projectbarry.onicompanion.net.ApiClient
import io.github.projectbarry.onicompanion.net.ApiException
import io.github.projectbarry.onicompanion.net.PinMismatchException
import io.github.projectbarry.onicompanion.net.UnreachableException
import io.github.projectbarry.onicompanion.screen.Action
import io.github.projectbarry.onicompanion.screen.Ref
import io.github.projectbarry.onicompanion.theme.GameTheme
import io.github.projectbarry.onicompanion.screen.Block
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import java.io.File

/** The service answered, or this describes why it did not. status 0 = no connection. */
sealed interface Reply {
    data class Ok(val json: JsonObject) : Reply
    data class Err(val status: Int, val message: String) : Reply
}

/** Why the whole service view is replaced by a message. */
sealed interface Fatal {
    data object Unpaired : Fatal
    data object CantVerify : Fatal
}

/** GET /sync (api.schema.json Sync). Every word shown on the sync screen comes from here. */
data class SyncInfo(
    val state: String = "idle", val needed: Boolean = false, val neededReason: String? = null, val canStart: Boolean = false,
    val queued: Boolean = false, val reason: String? = null, val done: Int = 0, val total: Int = 0, val current: String? = null,
    val errors: Int = 0, val lastError: String? = null, val elapsedMs: Long = 0, val message: String? = null,
) {
    companion object {
        fun parse(o: JsonObject): SyncInfo {
            fun s(k: String) = (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            fun n(k: String) = (o[k] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()
            fun b(k: String) = (o[k] as? JsonPrimitive)?.booleanOrNull == true
            return SyncInfo(s("state") ?: "idle", b("needed"), s("neededReason"), b("canStart"), b("queued"), s("reason"),
                n("done")?.toInt() ?: 0, n("total")?.toInt() ?: 0, s("current"), n("errors")?.toInt() ?: 0, s("lastError"), n("elapsedMs")?.toLong() ?: 0, s("message"))
        }
    }
}

class Ask(val text: String, val yes: () -> Unit)

/**
 * Everything the screens show about one connected gaming device, and everything they ask it to do. The front end
 * (Compose) only draws this state and forwards taps: all wording, numbers and rules come from the core.
 * One long-poll (GET /events) drives refreshes; nothing is polled.
 */
class OniSession(
    val api: ApiClient,
    parent: CoroutineScope,
    cacheDir: File,
    cacheKey: String,
) {
    private val job = SupervisorJob(parent.coroutineContext[Job])
    val scope = CoroutineScope(parent.coroutineContext + job)

    val art = ArtRepo(api, File(cacheDir, "art/$cacheKey"))
    val fonts = FontRepo(api, File(cacheDir, "fonts/$cacheKey"))

    // ---- state the screens draw ----
    var nav by mutableStateOf(NavState.initial()); private set
    var theme by mutableStateOf(GameTheme()); private set
    var controls by mutableStateOf<Controls?>(null); private set
    var controlsHidden by mutableStateOf(false); private set
    var pendingBtn by mutableStateOf(""); private set
    var connected by mutableStateOf(false); private set
    /** Failed attempts in a row since the last answer; the screens say "no answer" once it is long enough. */
    var failures by mutableStateOf(0); private set
    var fatal by mutableStateOf<Fatal?>(null); private set
    var sync by mutableStateOf(SyncInfo()); private set
    var syncOpen by mutableStateOf(false)
    var syncScope by mutableStateOf("")
    var toastText by mutableStateOf(""); private set
    var toastBad by mutableStateOf(true); private set
    var askState by mutableStateOf<Ask?>(null)
    var kindLabels by mutableStateOf<Map<String, String>>(emptyMap()); private set
    var filterText by mutableStateOf("")
    var revealKey by mutableStateOf(""); private set
    private var revealedAt = 0L
    val groupOpen = mutableStateMapOf<String, Boolean>()

    private val eventFlow = MutableSharedFlow<List<String>>(extraBufferCapacity = 64)
    /** The names `GET /events` reported (and the initial full refresh after a (re)connect). */
    val events: SharedFlow<List<String>> = eventFlow

    private val pages = HashMap<Long, PageController>()
    private val lookups = HashMap<Long, LookupController>()
    private var syncAsked = false
    private var toastJob: Job? = null
    private var pendingJob: Job? = null
    private val pendingActions = HashMap<Long, CompletableDeferred<String?>>()

    // ---- service calls ----
    suspend fun get(path: String): Reply = call { api.get(path) }
    suspend fun post(path: String, body: JsonElement? = null): Reply = call { api.post(path, body) }

    private suspend fun call(block: suspend () -> JsonObject): Reply = try {
        Reply.Ok(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: PinMismatchException) {
        fatal = Fatal.CantVerify; Reply.Err(0, "Can't verify this device")
    } catch (e: ApiException) {
        if (e.unauthorized) fatal = Fatal.Unpaired
        Reply.Err(e.status, e.message ?: "Something went wrong (${e.status}).")
    } catch (e: UnreachableException) {
        Reply.Err(0, "Can't reach the ONI Companion service.")
    } catch (e: java.io.IOException) {
        Reply.Err(0, "Can't reach the ONI Companion service.")
    }

    fun errorText(r: Reply.Err) = if (r.status == 0) "Can't reach the ONI Companion service." else r.message

    // ---- start / stop ----
    fun start() {
        scope.launch { loadTabs() }
        scope.launch { loadKinds() }
        scope.launch { loadTheme() }
        scope.launch { loadControls() }
        scope.launch { eventLoop() }
    }

    fun stop() { job.cancel() }

    // ---- hooks the Android shell sets ----
    /** Opens an https link in the browser (set by the activity). */
    var urlOpener: (String) -> Unit = {}
    /** Leaves the service view (Settings: "Back to devices"). */
    var onLeave: () -> Unit = {}

    fun openUrl(url: String) { if (url.startsWith("https://")) urlOpener(url) }

    // ---- the element picker overlay (a form's element field) ----
    val picker = PickerController(this)
    var pickerOpen by mutableStateOf(false); private set
    private var pickerCb: ((String, String) -> Unit)? = null
    fun pickElement(filter: String, cb: (String, String) -> Unit) { pickerCb = cb; picker.open(); pickerOpen = true }
    fun picked(id: String, name: String) { pickerOpen = false; pickerCb?.invoke(id, name); pickerCb = null }
    fun pickCancelled() { pickerOpen = false; pickerCb = null }

    private suspend fun eventLoop() {
        var seq = 0L
        while (true) {
            try {
                val ev = api.events(seq)
                if (!connected) {
                    connected = true
                    handle(listOf("colony", "gamedata", "status", "sync", "controls"))
                }
                val first = seq == 0L
                seq = ev.seq
                failures = 0
                if (!first && ev.changed.isNotEmpty()) handle(ev.changed)
            } catch (e: CancellationException) {
                throw e
            } catch (e: PinMismatchException) {
                connected = false; fatal = Fatal.CantVerify; return
            } catch (e: ApiException) {
                connected = false
                if (e.unauthorized) { fatal = Fatal.Unpaired; return }
                failures++; delay(retryDelay(failures))
            } catch (e: java.io.IOException) {
                connected = false
                failures++; delay(retryDelay(failures))
            }
        }
    }

    // Reconnect backoff after a failure; data itself is never polled (events are a long-poll).
    private fun retryDelay(n: Int) = (1500L * n).coerceAtMost(15000L)

    private fun handle(names: List<String>) {
        if ("action" in names) for (seq in pendingActions.keys.toList()) scope.launch { checkAction(seq) }
        if ("gamedata" in names) scope.launch { loadTheme() }
        if ("sync" in names) scope.launch { loadSync() }
        if ("controls" in names) scope.launch { loadControls() }
        if ("art" in names) art.bumpGeneration()
        eventFlow.tryEmit(names)
    }

    // ---- loads ----
    private suspend fun loadTabs() {
        val r = get("/tabs") as? Reply.Ok ?: return
        val list = (r.json["tabs"] as? JsonArray).orEmpty().mapNotNull { e ->
            val o = e as? JsonObject ?: return@mapNotNull null
            fun s(k: String) = (o[k] as? JsonPrimitive)?.contentOrNull
            Tab(s("id") ?: return@mapNotNull null, s("label") ?: "", s("path") ?: return@mapNotNull null,
                (o["excludeKinds"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                (o["includesTools"] as? JsonPrimitive)?.booleanOrNull == true)
        }
        if (list.isNotEmpty()) applyNav(nav.withTabs(list))
    }

    private suspend fun loadKinds() {
        val r = get("/kinds") as? Reply.Ok ?: return
        kindLabels = (r.json["kinds"] as? JsonArray).orEmpty().mapNotNull { e ->
            val o = e as? JsonObject ?: return@mapNotNull null
            val k = (o["kind"] as? JsonPrimitive)?.contentOrNull ?: return@mapNotNull null
            k to ((o["label"] as? JsonPrimitive)?.contentOrNull ?: k)
        }.toMap()
    }

    fun kindLabel(k: String): String = kindLabels[k] ?: k.replaceFirstChar { it.uppercase() }

    suspend fun loadTheme() {
        val r = get("/theme") as? Reply.Ok ?: return
        theme = GameTheme.fromJson(r.json, theme)
        fonts.refresh(theme.roles)
    }

    suspend fun loadControls() {
        when (val r = get("/controls")) {
            is Reply.Ok -> {
                controlsHidden = false
                val c = Controls.parse(r.json)
                controls = c
                if (c.pending == null) pendingBtn = ""      // the command is settled: show the game's real state
            }
            is Reply.Err -> if (r.status == 404) { controlsHidden = true; controls = null } else controls = Controls(false, null, null, null, null)
        }
    }

    suspend fun loadSync() {
        val r = get("/sync") as? Reply.Ok ?: return
        val was = sync.state == "running"
        val info = SyncInfo.parse(r.json)
        sync = info
        if (!syncAsked && info.needed) { syncAsked = true; syncOpen = true }
        if (was && info.state != "running") {          // the sync wrote new pictures, theme and fonts
            art.clear(); art.bumpGeneration()
            loadTheme()
        }
    }

    // ---- navigation ----
    private fun applyNav(n: NavState) {
        nav = n
        val keep = n.idsOn()
        pages.entries.removeAll { (id, c) -> (id !in keep).also { gone -> if (gone) c.dispose() } }
        lookups.entries.removeAll { (id, c) -> (id !in keep).also { gone -> if (gone) c.dispose() } }
    }

    fun push(path: String) { revealKey = ""; filterText = ""; applyNav(nav.push(path)) }
    fun pop() { revealKey = ""; filterText = ""; applyNav(nav.pop()) }
    fun goTab(i: Int) { syncOpen = false; revealKey = ""; filterText = ""; applyNav(nav.goTab(i)) }
    fun openRef(ref: Ref) { revealKey = ""; filterText = ""; applyNav(nav.openRef(ref)) }
    fun pageFor(e: ScreenEntry): PageController = pages.getOrPut(e.id) { PageController(this, e) }
    fun lookupFor(e: LookupEntry): LookupController = lookups.getOrPut(e.id) { LookupController(this, e) }
    fun currentPage(): PageController? = (nav.top as? ScreenEntry)?.let { pages[it.id] }

    // ---- reveal (a long press shows an action's buttons) ----
    fun reveal(key: String) { revealKey = key; revealedAt = System.nanoTime() }
    fun hideReveal() { if (revealKey != "") revealKey = "" }
    /** A press at [pressNanos] that is not the one that revealed the buttons hides them. */
    fun pressedAt(pressNanos: Long) { if (revealKey != "" && revealedAt < pressNanos) revealKey = "" }

    // ---- toast and questions ----
    fun toast(text: String) { showToast(text, true) }
    fun notify(text: String) { showToast(text, false) }
    private fun showToast(text: String, bad: Boolean) {
        toastText = text; toastBad = bad
        toastJob?.cancel()
        toastJob = scope.launch { delay(4500); toastText = "" }
    }
    fun clearToast() { toastText = "" }
    fun ask(text: String, yes: () -> Unit) { askState = Ask(text, yes) }

    // ---- actions ----
    /**
     * Sends one action (POST /actions/<id>) and suspends until the game answers: null = done, otherwise the
     * message to show. One tap = one call; the caller adds its own timeout.
     */
    suspend fun runAction(action: Action): String? {
        val r = post("/actions/" + NavState.enc(action.id), action.args)
        if (r is Reply.Err) return errorText(r)
        val seq = ((r as Reply.Ok).json["seq"] as? JsonPrimitive)?.contentOrNull?.toLongOrNull() ?: return "That did not work."
        val d = CompletableDeferred<String?>()
        pendingActions[seq] = d
        checkAction(seq)
        val result = try { d.await() } finally { pendingActions.remove(seq) }
        if (result == null && action.id == "alert_dismiss") {
            // A dismissed alert's own page is gone: go back to the list.
            val top = nav.top
            if (top is ScreenEntry && top.path.startsWith("entry/alert/")) pop()
        }
        return result
    }

    private suspend fun checkAction(seq: Long) {
        val d = pendingActions[seq] ?: return
        when (val r = get("/actions/$seq")) {
            is Reply.Err -> d.complete(errorText(r))
            is Reply.Ok -> {
                val state = (r.json["state"] as? JsonPrimitive)?.contentOrNull
                val msg = (r.json["message"] as? JsonPrimitive)?.contentOrNull
                when (state) {
                    "pending" -> {}
                    "done" -> d.complete(null)
                    "expired" -> d.complete(msg ?: "The game did not answer.")
                    else -> d.complete(msg ?: "That did not work.")
                }
            }
        }
    }

    /** Fire and forget with a toast on failure (a tapped span, onOpen). */
    fun fire(action: Action) {
        scope.launch { runAction(action)?.let { toast(it) } }
    }

    // ---- speed ----
    fun setSpeed(key: String) {
        val c = controls ?: return
        if (!c.available) return
        pendingBtn = key
        pendingJob?.cancel()
        pendingJob = scope.launch { delay(10000); pendingBtn = "" }
        scope.launch {
            when (val r = post("/controls", SpeedLogic.body(c, key))) {
                is Reply.Ok -> controls = Controls.parse(r.json)
                is Reply.Err -> { pendingBtn = ""; toast(errorText(r)) }
            }
        }
    }

    // ---- sync ----
    fun openSync(scopeName: String = "") { syncScope = scopeName; syncOpen = true; scope.launch { loadSync() } }
    fun startSync(scopeName: String) {
        scope.launch {
            val body = if (scopeName.isEmpty()) JsonObject(emptyMap()) else JsonObject(mapOf("scope" to JsonPrimitive(scopeName)))
            when (val r = post("/sync", body)) {
                is Reply.Ok -> sync = SyncInfo.parse(r.json)
                is Reply.Err -> toast(errorText(r))
            }
        }
    }
    fun cancelSync() {
        scope.launch {
            val r = post("/sync", JsonObject(mapOf("cancel" to JsonPrimitive(true))))
            if (r is Reply.Ok) sync = SyncInfo.parse(r.json)
        }
    }

    // ---- tools / forms ----
    /** Submits a form (tool or settings endpoint) and hands the reply Screen to [page]. */
    suspend fun submitTool(page: PageController?, tool: String, values: JsonObject, endpoint: String?) {
        val path = if (endpoint != null) endpoint else "/tools/" + NavState.enc(tool)
        when (val r = post(path, JsonObject(mapOf("values" to values)))) {
            is Reply.Ok -> if (r.json["blocks"] != null) page?.setResult(r.json) else page?.toolFailed("Something went wrong.")
            is Reply.Err -> page?.toolFailed(errorText(r))
        }
    }

    suspend fun nameOf(kind: String, id: String): String? {
        val r = get("/search?q=" + NavState.enc(id) + "&kind=" + kind + "&limit=10") as? Reply.Ok ?: return null
        for (x in (r.json["results"] as? JsonArray).orEmpty()) {
            val o = x as? JsonObject ?: continue
            if ((o["id"] as? JsonPrimitive)?.contentOrNull == id) return (o["name"] as? JsonPrimitive)?.contentOrNull
        }
        return null
    }

    fun titleMatches(t: String?) = filterText.isEmpty() || (t ?: "").lowercase().contains(filterText)

    /** True when a list, grid or group (recursively) holds a title that matches the filter. */
    fun blockHasMatch(b: Block): Boolean = when (b) {
        is Block.Items -> b.items.any { titleMatches(it.title) }
        is Block.Grid -> b.cards.any { titleMatches(it.title) }
        is Block.Group -> b.blocks.any { blockHasMatch(it) }
        else -> false
    }
}
