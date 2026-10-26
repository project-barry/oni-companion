package io.github.projectbarry.onicompanion.local

import java.io.File

/** One entry of a folder in the shared ONICompanion tree. */
data class SharedEntry(val name: String, val isDir: Boolean, val size: Long, val modified: Long)

/**
 * The shared ONICompanion folder as the mirror sees it. Paths are relative with "/" ("live/live.json", "" = the
 * folder itself). The real one is [SafTree] (Storage Access Framework); [FileSharedFs] stands in for it in unit tests.
 */
interface SharedFs {
    fun list(dir: String): List<SharedEntry>?          // null = the folder does not exist
    fun read(path: String): ByteArray?
    /** Creates the file, atomically for readers: they see the whole file or none (temp name, then rename). */
    fun write(path: String, bytes: ByteArray)
    fun delete(path: String)
}

class FileSharedFs(private val root: File) : SharedFs {
    override fun list(dir: String): List<SharedEntry>? {
        val d = if (dir.isEmpty()) root else File(root, dir)
        val files = d.listFiles() ?: return null
        return files.map { SharedEntry(it.name, it.isDirectory, it.length(), it.lastModified()) }
    }
    override fun read(path: String): ByteArray? = File(root, path).takeIf { it.isFile }?.readBytes()
    override fun write(path: String, bytes: ByteArray) {
        val f = File(root, path)
        f.parentFile?.mkdirs()
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.writeBytes(bytes)
        tmp.renameTo(f)
    }
    override fun delete(path: String) { File(root, path).delete() }
}
