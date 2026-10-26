package io.github.projectbarry.onicompanion.session

import io.github.projectbarry.onicompanion.screen.Ref
import java.net.URLEncoder

/** One tab from GET /tabs. The path `kinds` is the look-up page (kinds, search, calculators). */
data class Tab(
    val id: String, val label: String, val path: String,
    val excludeKinds: List<String> = emptyList(), val includesTools: Boolean = false,
) {
    val isLookup get() = path == "kinds"
    val isSettings get() = id == "settings"
}

/** A page on a tab's back stack. Ids are unique per entry so page state can be kept and dropped. */
sealed interface Entry { val id: Long }
data class ScreenEntry(override val id: Long, val path: String, val closeBar: Boolean = false) : Entry
data class LookupEntry(override val id: Long, val excludeKinds: List<String>, val tools: Boolean) : Entry

/** The tabs used until GET /tabs answers (or against an older core): the six of v1.3. */
val DEFAULT_TABS = listOf(
    Tab("colony", "Colony", "colony"),
    Tab("resources", "Resources", "resources"),
    Tab("buildings", "Buildings", "buildings"),
    Tab("actions", "Actions", "pad"),
    Tab("codex", "Database", "kinds", listOf("building"), true),
    Tab("settings", "Settings", "settings"),
)

/**
 * Tabs and one back stack per tab (like Barry's main.qml). Immutable: every move returns a new state.
 * Pure logic, so it is unit tested without Android.
 */
data class NavState(
    val tabs: List<Tab>,
    val tab: Int,
    val stacks: List<List<Entry>>,
    val nextId: Long,
) {
    val top: Entry get() = stacks[tab].last()
    val canGoBack: Boolean get() = stacks[tab].size > 1
    val current: Tab get() = tabs[tab]

    fun push(path: String): NavState {
        val e = ScreenEntry(nextId, path)
        return copy(stacks = stacks.mapIndexed { i, s -> if (i == tab) s + e else s }, nextId = nextId + 1)
    }

    fun openRef(ref: Ref): NavState = push("entry/" + enc(ref.kind) + "/" + enc(ref.id))

    fun pop(): NavState =
        if (!canGoBack) this else copy(stacks = stacks.mapIndexed { i, s -> if (i == tab) s.dropLast(1) else s })

    /** Tapping the open tab goes back to its first page; another tab just shows that tab as it was left. */
    fun goTab(i: Int): NavState {
        if (i !in tabs.indices) return this
        if (i == tab) return copy(stacks = stacks.mapIndexed { n, s -> if (n == tab) s.take(1) else s })
        return copy(tab = i)
    }

    /** New tab list from the core. Same list: no change. Otherwise every stack starts again. */
    fun withTabs(list: List<Tab>): NavState {
        if (list.isEmpty() || list == tabs) return this
        var id = nextId
        val stacks = list.map { listOf(root(it, id++)) }
        return NavState(list, tab.coerceAtMost(list.size - 1), stacks, id)
    }

    /** Ids of pages that are no longer on any stack (their state can be dropped). */
    fun idsOn(): Set<Long> = stacks.flatten().map { it.id }.toSet()

    companion object {
        fun root(t: Tab, id: Long): Entry =
            if (t.isLookup) LookupEntry(id, t.excludeKinds, t.includesTools) else ScreenEntry(id, t.path, closeBar = t.isSettings)

        fun initial(tabs: List<Tab> = DEFAULT_TABS): NavState {
            var id = 1L
            return NavState(tabs, 0, tabs.map { listOf(root(it, id++)) }, id)
        }

        fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
    }
}
