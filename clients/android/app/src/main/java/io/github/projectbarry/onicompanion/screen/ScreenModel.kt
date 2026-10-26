package io.github.projectbarry.onicompanion.screen

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

/** blocks.schema.json Ref: points at one entry (GET /entry/<kind>/<id>). */
data class Ref(val kind: String, val id: String, val art: String? = null)

/** blocks.schema.json Action: a button. `args` is posted as the body of POST /actions/<id>. */
data class Action(
    val id: String,
    val label: String,
    val args: JsonObject = JsonObject(emptyMap()),
    val trigger: String = "tap",
    val danger: Boolean = false,
    val active: Boolean = false,
    val confirm: String? = null,
    val enabled: Boolean = true,
    val reason: String? = null,
) {
    val longPress get() = trigger == "longPress"
}

/** One run of text. [type] is plain, bold, ref or link. */
data class Span(
    val type: String,
    val text: String,
    val color: String? = null,
    val icon: String? = null,
    val action: Action? = null,
    val ref: Ref? = null,
    val url: String? = null,
) {
    val bold get() = type == "bold"
}

data class StatRow(val label: String, val value: String, val hint: String?, val ref: Ref?, val tone: String?)
data class Meter(val label: String, val value: Double, val max: Double, val unit: String?, val tone: String?)
data class Badge(val level: String, val label: String)
data class Chip(val label: String, val style: String, val ref: Ref?)
data class ListItem(
    val ref: Ref?, val title: String, val subtitle: String?, val badge: String?, val tone: String?,
    val art: String?, val actions: List<Action>,
)
data class Card(
    val title: String, val subtitle: String?, val badge: String?, val ref: Ref?, val tone: String?,
    val stats: List<StatRow>, val meters: List<Meter>, val art: String?, val badges: List<Badge>, val actions: List<Action>,
)
data class Port(val label: String, val element: Ref?, val rate: Double?, val unit: String?, val conduit: String?, val note: String?)
data class PhaseState(val state: String, val label: String, val range: String?, val target: Ref?)
data class Cell(val text: String, val ref: Ref?, val tone: String?)
data class FieldUnit(val id: String, val label: String)
data class FieldOption(val value: String, val label: String)
data class Field(
    val kind: String, val name: String, val label: String,
    val default: String?, val unit: String?, val units: List<FieldUnit>, val defaultUnit: String?,
    val filter: String?, val options: List<FieldOption>, val defaultToggle: Boolean,
)
data class PickerOption(
    val id: String, val name: String, val art: String?, val ref: Ref?,
    val needKg: Double, val haveKg: Double, val enabled: Boolean, val selected: Boolean,
)
data class PickerSlot(val label: String, val needKg: Double, val options: List<PickerOption>, val empty: String?)

sealed interface Block {
    data class Heading(val text: String, val level: Int, val art: String?) : Block
    data class Text(val spans: List<Span>) : Block
    data class Stats(val title: String?, val rows: List<StatRow>) : Block
    data class Chips(val chips: List<Chip>) : Block
    data class Items(val title: String?, val variant: String?, val items: List<ListItem>, val empty: String?) : Block
    data class Grid(val title: String?, val variant: String?, val cards: List<Card>) : Block
    data class Ports(val title: String?, val inputs: List<Port>, val outputs: List<Port>) : Block
    data class Phases(val title: String?, val states: List<PhaseState>) : Block
    data class Progress(val label: String, val value: Double, val max: Double, val unit: String?, val tone: String?) : Block
    data class Table(val title: String?, val columns: List<String>, val rows: List<List<Cell>>) : Block
    data class Notice(val level: String, val title: String?, val text: String) : Block
    data class Form(
        val tool: String, val title: String?, val submitLabel: String, val endpoint: String?, val fields: List<Field>,
    ) : Block
    data class Link(val label: String, val url: String) : Block
    data class Image(val art: String, val caption: String?, val alt: String?, val size: String) : Block
    data class Picker(val title: String?, val slots: List<PickerSlot>, val action: Action) : Block
    data object Divider : Block
    data class Group(val title: String, val collapsed: Boolean, val blocks: List<Block>) : Block
    /** A block type this app version does not draw (the contract: show the "update the app" notice). */
    data class Unknown(val type: String) : Block
}

data class WorldOption(val id: Int, val name: String)
data class WorldSwitcher(val active: Int, val worlds: List<WorldOption>)
data class OnOpen(val action: String, val args: JsonObject)

data class ScreenModel(
    val title: String,
    val subtitle: String?,
    val source: String?,
    val asOf: String?,
    val refreshOn: Set<String>,
    val onOpen: List<OnOpen>,
    val filterPlaceholder: String?,
    val worldSwitcher: WorldSwitcher?,
    val blocks: List<Block>,
)

/** Reads a Screen (screen.schema.json) into plain Kotlin. All wording comes from the core. */
object ScreenParser {
    fun parse(o: JsonObject): ScreenModel = ScreenModel(
        title = o.str("title") ?: "",
        subtitle = o.str("subtitle"),
        source = o.str("source"),
        asOf = o.str("asOf"),
        refreshOn = o.arr("refreshOn").mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.toSet(),
        onOpen = o.arr("onOpen").mapNotNull { e ->
            val x = e as? JsonObject ?: return@mapNotNull null
            OnOpen(x.str("action") ?: return@mapNotNull null, x.obj("args") ?: JsonObject(emptyMap()))
        },
        filterPlaceholder = o.obj("filter")?.str("placeholder"),
        worldSwitcher = o.obj("worldSwitcher")?.let { w ->
            WorldSwitcher(w.int("active") ?: 0, w.arr("worlds").mapNotNull { e ->
                val x = e as? JsonObject ?: return@mapNotNull null
                WorldOption(x.int("id") ?: return@mapNotNull null, x.str("name") ?: "")
            })
        },
        blocks = o.arr("blocks").map { block(it) },
    )

    // ---- json helpers ----
    internal fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull && it.isString }?.contentOrNull
    internal fun JsonObject.num(k: String): Double? = (this[k] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull?.toDoubleOrNull()
    internal fun JsonObject.int(k: String): Int? = num(k)?.toInt()
    internal fun JsonObject.bool(k: String): Boolean? = (this[k] as? JsonPrimitive)?.booleanOrNull
    internal fun JsonObject.obj(k: String): JsonObject? = this[k] as? JsonObject
    internal fun JsonObject.arr(k: String): List<JsonElement> = (this[k] as? JsonArray) ?: emptyList()
    /** A value shown as the core wrote it: strings as is, numbers without a trailing ".0". */
    internal fun JsonElement?.display(): String {
        val p = this as? JsonPrimitive ?: return ""
        if (p is JsonNull) return ""
        if (p.isString) return p.content
        val d = p.contentOrNull?.toDoubleOrNull() ?: return p.contentOrNull ?: ""
        return if (d == Math.rint(d) && Math.abs(d) < 1e15) d.toLong().toString() else p.content
    }

    fun ref(e: JsonElement?): Ref? {
        val o = e as? JsonObject ?: return null
        return Ref(o.str("kind") ?: return null, o.str("id") ?: return null, o.str("art"))
    }

    fun action(e: JsonElement?): Action? {
        val o = e as? JsonObject ?: return null
        return Action(
            id = o.str("id") ?: return null, label = o.str("label") ?: "",
            args = o.obj("args") ?: JsonObject(emptyMap()), trigger = o.str("trigger") ?: "tap",
            danger = o.bool("danger") == true, active = o.bool("active") == true, confirm = o.str("confirm"),
            enabled = o.bool("enabled") != false, reason = o.str("reason"),
        )
    }

    private fun actions(o: JsonObject) = o.arr("actions").mapNotNull { action(it) }

    private fun span(e: JsonElement): Span? {
        val o = e as? JsonObject ?: return null
        val type = o.str("type") ?: "plain"
        val text = o.str("text") ?: ""
        val icon = o.str("icon")
        if (text.isEmpty() && icon == null) return null
        return Span(type, text, o.str("color"), icon, action(o["action"]), ref(o["ref"]), o.str("url"))
    }

    private fun stat(e: JsonElement): StatRow {
        val o = e as? JsonObject ?: return StatRow("", "", null, null, null)
        val unit = o.str("unit")
        val v = o["value"].display()
        return StatRow(o.str("label") ?: "", if (unit.isNullOrEmpty()) v else "$v $unit", o.str("hint"), ref(o["ref"]), o.str("tone"))
    }

    private fun meter(e: JsonElement): Meter? {
        val o = e as? JsonObject ?: return null
        return Meter(o.str("label") ?: "", o.num("value") ?: 0.0, o.num("max") ?: 0.0, o.str("unit"), o.str("tone"))
    }

    private fun port(e: JsonElement): Port? {
        val o = e as? JsonObject ?: return null
        return Port(o.str("label") ?: "", ref(o["element"]), o.num("rate"), o.str("unit"), o.str("conduit"), o.str("note"))
    }

    private fun cell(c: JsonElement): Cell = when (c) {
        is JsonObject -> Cell(c.str("text") ?: "", ref(c["ref"]), c.str("tone"))
        else -> Cell(c.display(), null, null)
    }

    private fun field(e: JsonElement): Field? {
        val o = e as? JsonObject ?: return null
        val kind = o.str("kind") ?: return null
        val dflt = o["default"]
        return Field(
            kind = kind, name = o.str("name") ?: return null, label = o.str("label") ?: "",
            default = if (kind == "toggle") null else dflt?.display()?.takeIf { dflt !is JsonNull },
            unit = o.str("unit"),
            units = o.arr("units").mapNotNull { u -> (u as? JsonObject)?.let { FieldUnit(it.str("id") ?: return@let null, it.str("label") ?: "") } },
            defaultUnit = o.str("defaultUnit"), filter = o.str("filter"),
            options = o.arr("options").mapNotNull { u -> (u as? JsonObject)?.let { FieldOption(it.str("value") ?: return@let null, it.str("label") ?: "") } },
            defaultToggle = (dflt as? JsonPrimitive)?.booleanOrNull == true,
        )
    }

    private fun pickerOption(e: JsonElement): PickerOption? {
        val o = e as? JsonObject ?: return null
        return PickerOption(
            id = o.str("id") ?: return null, name = o.str("name") ?: "", art = o.str("art"), ref = ref(o["ref"]),
            needKg = o.num("needKg") ?: 0.0, haveKg = o.num("haveKg") ?: 0.0,
            enabled = o.bool("enabled") != false, selected = o.bool("selected") == true,
        )
    }

    fun block(e: JsonElement): Block {
        val o = e as? JsonObject ?: return Block.Unknown("?")
        return when (val type = o.str("type") ?: "?") {
            "heading" -> Block.Heading(o.str("text") ?: "", o.int("level") ?: 2, o.str("art"))
            "text" -> Block.Text(o.arr("spans").mapNotNull { span(it) })
            "stats" -> Block.Stats(o.str("title"), o.arr("rows").map { stat(it) })
            "chips" -> Block.Chips(o.arr("chips").mapNotNull { c ->
                val co = c as? JsonObject ?: return@mapNotNull null
                Chip(co.str("label") ?: return@mapNotNull null, co.str("style") ?: "plain", ref(co["ref"]))
            })
            "list" -> Block.Items(o.str("title"), o.str("variant"), o.arr("items").mapNotNull { i ->
                val io = i as? JsonObject ?: return@mapNotNull null
                ListItem(ref(io["ref"]), io.str("title") ?: "", io.str("subtitle"), io.str("badge"), io.str("tone"), io.str("art"), actions(io))
            }, o.str("empty"))
            "grid" -> Block.Grid(o.str("title"), o.str("variant"), o.arr("cards").mapNotNull { c ->
                val co = c as? JsonObject ?: return@mapNotNull null
                Card(
                    co.str("title") ?: "", co.str("subtitle"), co.str("badge"), ref(co["ref"]), co.str("tone"),
                    co.arr("stats").map { stat(it) }, co.arr("meters").mapNotNull { meter(it) }, co.str("art"),
                    co.arr("badges").mapNotNull { b -> (b as? JsonObject)?.let { Badge(it.str("level") ?: "info", it.str("label") ?: "") } },
                    actions(co),
                )
            })
            "ports" -> Block.Ports(o.str("title"), o.arr("inputs").mapNotNull { port(it) }, o.arr("outputs").mapNotNull { port(it) })
            "phases" -> Block.Phases(o.str("title"), o.arr("states").mapNotNull { s ->
                val so = s as? JsonObject ?: return@mapNotNull null
                PhaseState(so.str("state") ?: "vacuum", so.str("label") ?: "", so.str("range"), ref(so["target"]))
            })
            "progress" -> Block.Progress(o.str("label") ?: "", o.num("value") ?: 0.0, o.num("max") ?: 0.0, o.str("unit"), o.str("tone"))
            "table" -> Block.Table(o.str("title"), o.arr("columns").map { it.display() },
                o.arr("rows").map { row -> ((row as? JsonArray) ?: emptyList()).map { cell(it) } })
            "notice" -> Block.Notice(o.str("level") ?: "info", o.str("title"), o.str("text") ?: "")
            "form" -> Block.Form(o.str("tool") ?: "", o.str("title"), o.str("submitLabel") ?: "Go", o.str("endpoint"),
                o.arr("fields").mapNotNull { field(it) })
            "link" -> Block.Link(o.str("label") ?: "", o.str("url") ?: "")
            "image" -> Block.Image(o.str("art") ?: "", o.str("caption"), o.str("alt"), o.str("size") ?: "medium")
            "picker" -> Block.Picker(o.str("title"),
                o.arr("slots").mapNotNull { s ->
                    val so = s as? JsonObject ?: return@mapNotNull null
                    PickerSlot(so.str("label") ?: "", so.num("needKg") ?: 0.0, so.arr("options").mapNotNull { pickerOption(it) }, so.str("empty"))
                },
                action(o["action"]) ?: return Block.Unknown(type))
            "divider" -> Block.Divider
            "group" -> Block.Group(o.str("title") ?: "", o.bool("collapsed") == true, o.arr("blocks").map { block(it) })
            else -> Block.Unknown(type)
        }
    }
}
