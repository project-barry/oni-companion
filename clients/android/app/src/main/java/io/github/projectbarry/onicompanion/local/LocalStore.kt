package io.github.projectbarry.onicompanion.local

import android.content.Context
import android.net.Uri

/** What local mode remembers: the granted folder, the emulator the user named, the bottom-screen choice. */
class LocalStore(ctx: Context) {
    private val p = ctx.getSharedPreferences("local-mode", Context.MODE_PRIVATE)

    var treeUri: Uri?
        get() = p.getString("tree", null)?.let(Uri::parse)
        set(v) { p.edit().apply { if (v == null) remove("tree") else putString("tree", v.toString()) }.apply() }

    var emulator: String?
        get() = p.getString("emulator", null)
        set(v) { p.edit().putString("emulator", v).apply() }

    /** Open on the second display when there is one (plan 4.2). On by default. */
    var bottomScreen: Boolean
        get() = p.getBoolean("bottom", true)
        set(v) { p.edit().putBoolean("bottom", v).apply() }
}
