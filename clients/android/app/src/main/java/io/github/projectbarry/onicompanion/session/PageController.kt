package io.github.projectbarry.onicompanion.session

import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.projectbarry.onicompanion.screen.ScreenModel
import io.github.projectbarry.onicompanion.screen.ScreenParser
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * ScreenPage.qml: fetches one Screen path, keeps it, and fetches again when /events names something the Screen
 * lists in `refreshOn`. The world switcher re-fetches with `?world=`; `onOpen` actions run once, the first time the
 * page shows (not on a refresh, not when Back returns to it). Lives as long as its entry is on a back stack.
 */
class PageController(private val session: OniSession, val entry: ScreenEntry) {
    var screen by mutableStateOf<ScreenModel?>(null); private set
    var failed by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set
    var world by mutableStateOf<Int?>(null); private set
    val listState = LazyListState()

    private var lastJson: JsonObject? = null
    private var opened = false
    private val watcher: Job

    init {
        load(false)
        watcher = session.scope.launch {
            session.events.collect { names ->
                val ro = screen?.refreshOn.orEmpty()
                if (names.any { it in ro }) load(true)
            }
        }
    }

    fun dispose() { watcher.cancel() }

    private fun url(): String {
        val w = world ?: return "/" + entry.path
        return "/" + entry.path + (if (entry.path.contains('?')) "&" else "?") + "world=" + w
    }

    private fun show(json: JsonObject) {
        val model = ScreenParser.parse(json)
        screen = model
        if (!opened) {
            opened = true
            for (a in model.onOpen) session.fire(io.github.projectbarry.onicompanion.screen.Action(a.action, "", a.args))
        }
    }

    fun load(silent: Boolean) {
        if (!silent && screen == null) { failed = false; error = "" }
        session.scope.launch {
            when (val r = session.get(url())) {
                is Reply.Ok -> if (r.json["blocks"] is JsonArray) {
                    failed = false
                    if (r.json != lastJson) { lastJson = r.json; show(r.json) }
                } else if (!silent || screen == null) { failed = true; error = "Something went wrong." }
                is Reply.Err -> if (!silent || screen == null) { failed = true; error = session.errorText(r) }
            }
        }
    }

    fun pickWorld(id: Int) { world = id; lastJson = null; load(true) }

    /** The answer of a tool or settings form: it replaces the page's content. */
    fun setResult(json: JsonObject) { failed = false; lastJson = json; show(json) }
    fun toolFailed(message: String) { failed = true; error = message }
    fun dismissError() { failed = false }
}

/** LookupPage.qml: a search box; with no text, the kinds and calculators; with text, ranked results. */
class LookupController(private val session: OniSession, val entry: LookupEntry) {
    data class KindRow(val kind: String, val label: String, val count: Int)
    data class ToolRow(val id: String, val title: String, val summary: String)
    data class ResultRow(val kind: String, val id: String, val name: String, val subtitle: String, val dlc: List<String>)

    var query by mutableStateOf(""); private set
    var kinds by mutableStateOf<List<KindRow>>(emptyList()); private set
    var tools by mutableStateOf<List<ToolRow>>(emptyList()); private set
    var results by mutableStateOf<List<ResultRow>>(emptyList()); private set
    var status by mutableStateOf(""); private set
    val listState = LazyListState()

    private var debounce: Job? = null
    private val watcher: Job

    init {
        loadKinds(); loadTools()
        watcher = session.scope.launch {
            session.events.collect { names ->
                if ("gamedata" in names) { loadKinds(); if (query.isNotBlank()) search() }
            }
        }
    }

    fun dispose() { watcher.cancel(); debounce?.cancel() }

    private fun keep(kind: String) = kind !in entry.excludeKinds

    private fun loadKinds() {
        session.scope.launch {
            when (val r = session.get("/kinds")) {
                is Reply.Ok -> {
                    kinds = (r.json["kinds"] as? JsonArray).orEmpty().mapNotNull { e ->
                        val o = e as? JsonObject ?: return@mapNotNull null
                        val k = str(o, "kind") ?: return@mapNotNull null
                        if (!keep(k)) null else KindRow(k, str(o, "label") ?: k, (o["count"] as? JsonPrimitive)?.content?.toDoubleOrNull()?.toInt() ?: 0)
                    }
                    if (query.isEmpty()) status = ""
                }
                is Reply.Err -> if (query.isEmpty()) status = session.errorText(r)
            }
        }
    }

    private fun loadTools() {
        if (!entry.tools) return
        session.scope.launch {
            val r = session.get("/tools") as? Reply.Ok ?: return@launch
            tools = (r.json["tools"] as? JsonArray).orEmpty().mapNotNull { e ->
                val o = e as? JsonObject ?: return@mapNotNull null
                val id = str(o, "id") ?: return@mapNotNull null
                ToolRow(id, str(o, "title") ?: id, str(o, "summary") ?: "")
            }
        }
    }

    fun onQuery(text: String) {
        query = text
        debounce?.cancel()
        if (text.isBlank()) { results = emptyList(); status = ""; return }
        debounce = session.scope.launch { kotlinx.coroutines.delay(150); search() }
    }

    fun search() {
        val q = query.trim()
        if (q.isEmpty()) { results = emptyList(); status = ""; return }
        session.scope.launch {
            val r = session.get("/search?q=" + NavState.enc(q) + "&limit=40")
            if (query.trim() != q) return@launch          // a stale answer
            when (r) {
                is Reply.Ok -> {
                    results = (r.json["results"] as? JsonArray).orEmpty().mapNotNull { e ->
                        val o = e as? JsonObject ?: return@mapNotNull null
                        val kind = str(o, "kind") ?: return@mapNotNull null
                        val id = str(o, "id") ?: return@mapNotNull null
                        if (!keep(kind)) null
                        else ResultRow(kind, id, str(o, "name") ?: id, str(o, "subtitle") ?: "",
                            (o["dlc"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.content })
                    }
                    status = if (results.isEmpty()) "Nothing found." else ""
                }
                is Reply.Err -> { results = emptyList(); status = session.errorText(r) }
            }
        }
    }

    private fun str(o: JsonObject, k: String) = (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.content
}

/** ElementPicker.qml: pick an element by searching. */
class PickerController(private val session: OniSession) {
    data class Row(val id: String, val name: String, val subtitle: String)

    var query by mutableStateOf(""); private set
    var results by mutableStateOf<List<Row>>(emptyList()); private set
    var status by mutableStateOf("Type to search."); private set
    private var debounce: Job? = null

    fun open() {
        query = ""; results = emptyList(); status = "Type to search."
        session.scope.launch {
            val r = session.get("/list/element") as? Reply.Ok ?: return@launch
            if (query.isNotEmpty()) return@launch
            val out = ArrayList<Row>()
            for (b in (r.json["blocks"] as? JsonArray).orEmpty()) {
                val bo = b as? JsonObject ?: continue
                if ((bo["type"] as? JsonPrimitive)?.content != "list") continue
                for (it in (bo["items"] as? JsonArray).orEmpty()) {
                    val io = it as? JsonObject ?: continue
                    val ref = io["ref"] as? JsonObject ?: continue
                    val id = (ref["id"] as? JsonPrimitive)?.content ?: continue
                    out.add(Row(id, (io["title"] as? JsonPrimitive)?.content ?: id, (io["subtitle"] as? JsonPrimitive)?.content ?: ""))
                }
            }
            if (out.isNotEmpty()) { results = out; status = "" }
        }
    }

    fun onQuery(text: String) {
        query = text
        debounce?.cancel()
        if (text.isBlank()) { results = emptyList(); status = "Type to search."; return }
        debounce = session.scope.launch { kotlinx.coroutines.delay(150); search() }
    }

    fun search() {
        val q = query.trim()
        if (q.isEmpty()) return
        session.scope.launch {
            val r = session.get("/search?q=" + NavState.enc(q) + "&kind=element&limit=40")
            if (query.trim() != q) return@launch
            when (r) {
                is Reply.Ok -> {
                    results = (r.json["results"] as? JsonArray).orEmpty().mapNotNull { e ->
                        val o = e as? JsonObject ?: return@mapNotNull null
                        val id = (o["id"] as? JsonPrimitive)?.content ?: return@mapNotNull null
                        Row(id, (o["name"] as? JsonPrimitive)?.content ?: id, (o["subtitle"] as? JsonPrimitive)?.content ?: "")
                    }
                    status = if (results.isEmpty()) "Nothing found." else ""
                }
                is Reply.Err -> { results = emptyList(); status = session.errorText(r) }
            }
        }
    }
}
