package io.github.projectbarry.onicompanion.local

import java.io.File

/**
 * Keeps a private copy of the shared ONICompanion tree so the embedded core can use plain file paths.
 *
 * Down: files the mod wrote (live, acks, sync, export, art, fonts, theme) are copied to [companion]; each change is
 * reported through [onFile] (the core's file watcher replacement). Up: the core writes `commands/cmd-N.json` in
 * [companion]; this copies each to the shared tree (temp name, then rename, the mod's rule). A command the mod has
 * consumed (gone from the shared folder) is removed from the private folder, as the mod would on a normal device.
 * Nothing here polls: callers run [syncDown] and [syncUp] when told that something changed.
 */
class Mirror(
    private val shared: SharedFs,
    private val companion: File,
    private val onFile: (File, removed: Boolean) -> Unit,
) {
    private val seen = HashMap<String, Pair<Long, Long>>()     // relative path -> (size, modified) last copied
    private val sentUp = HashSet<String>()                      // commands already copied to the shared folder
    /** Shared folders (relative) seen by the last [syncDown]; callers observe each of them. */
    @Volatile var folders: Set<String> = emptySet()
        private set

    /** The folder inside the shared tree that holds the mod's files. */
    private val base = "companion"

    @Synchronized
    fun syncDown() {
        val dirs = LinkedHashSet<String>()
        val present = HashSet<String>()
        walk(base, "", 0, dirs, present)
        // Files that vanished from the shared tree vanish here too (never commands/: those are ours until consumed).
        for (rel in seen.keys.toList()) {
            if (rel !in present && !rel.startsWith("commands/")) {
                seen.remove(rel)
                val f = File(companion, rel)
                if (f.delete()) onFile(f, true)
            }
        }
        if (shared.list("$base/commands") != null) dirs.add("$base/commands")   // watched, not mirrored down
        folders = dirs
        dropConsumedCommands()
    }

    private fun walk(shDir: String, rel: String, depth: Int, dirs: MutableSet<String>, present: MutableSet<String>) {
        val list = shared.list(shDir) ?: return
        dirs.add(shDir)
        for (e in list) {
            val childRel = if (rel.isEmpty()) e.name else "$rel/${e.name}"
            val childSh = "$shDir/${e.name}"
            if (e.isDir) {
                if (childRel == "commands" || depth >= 3) continue
                walk(childSh, childRel, depth + 1, dirs, present)
            } else if (!e.name.endsWith(".tmp")) {
                present.add(childRel)
                val stamp = e.size to e.modified
                if (seen[childRel] == stamp) continue
                val bytes = shared.read(childSh) ?: continue
                val f = File(companion, childRel)
                f.parentFile?.mkdirs()
                val tmp = File(f.parentFile, f.name + ".tmp")
                tmp.writeBytes(bytes)
                tmp.renameTo(f)
                seen[childRel] = stamp
                onFile(f, false)
            }
        }
    }

    /** Copies new commands up. Returns how many were sent. */
    @Synchronized
    fun syncUp(): Int {
        val dir = File(companion, "commands")
        val names = dir.list()?.filter { it.endsWith(".json") && !it.endsWith(".tmp") } ?: return 0
        var n = 0
        for (name in names.sorted()) {
            if (name in sentUp) continue
            val bytes = File(dir, name).takeIf { it.isFile }?.readBytes() ?: continue
            shared.write("$base/commands/$name", bytes)
            sentUp.add(name)
            n++
        }
        // A command the core deleted (expired) must not be picked up late by the mod.
        for (name in sentUp.toList()) {
            if (name !in names) { shared.delete("$base/commands/$name"); sentUp.remove(name) }
        }
        return n
    }

    private fun dropConsumedCommands() {
        val inbox = shared.list("$base/commands")?.map { it.name }?.toSet() ?: return
        for (name in sentUp.toList()) {
            if (name !in inbox) {
                sentUp.remove(name)
                File(companion, "commands/$name").delete()
            }
        }
    }
}
