package io.github.projectbarry.onicompanion.local

import android.content.ContentResolver
import android.database.ContentObserver
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document

/**
 * The folder the user granted through the Storage Access Framework (ACTION_OPEN_DOCUMENT_TREE on `ONICompanion`).
 * This is the least permission that reaches the folder: one tree, nothing else on the device.
 * Document ids are looked up by walking names and cached per path.
 */
class SafTree(private val cr: ContentResolver, val treeUri: Uri) : SharedFs {
    private val ids = HashMap<String, String>()

    private val rootId: String = DocumentsContract.getTreeDocumentId(treeUri)

    private fun docUri(id: String): Uri = DocumentsContract.buildDocumentUriUsingTree(treeUri, id)

    /**
     * Calls [onChange] when something inside [dir] changes. The provider watches a folder only while a query
     * cursor on it is open, so the cursor is kept open until the returned handle is closed.
     */
    fun watch(dir: String, onChange: () -> Unit): AutoCloseable? {
        val id = idOf(dir) ?: return null
        val uri = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, id)
        val c = try { cr.query(uri, arrayOf(Document.COLUMN_DOCUMENT_ID), null, null, null) } catch (e: Exception) { null } ?: return null
        val o = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { onChange() }
        }
        c.registerContentObserver(o)
        return AutoCloseable { c.unregisterContentObserver(o); c.close() }
    }

    private data class Row(val id: String, val entry: SharedEntry, val mime: String)

    private fun query(dirId: String): List<Row>? {
        val uri = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, dirId)
        val cols = arrayOf(Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE,
            Document.COLUMN_SIZE, Document.COLUMN_LAST_MODIFIED)
        return try {
            cr.query(uri, cols, null, null, null)?.use { c ->
                val out = ArrayList<Row>()
                while (c.moveToNext()) {
                    val mime = c.getString(2) ?: ""
                    out.add(Row(c.getString(0), SharedEntry(c.getString(1) ?: "", mime == Document.MIME_TYPE_DIR,
                        if (c.isNull(3)) 0 else c.getLong(3), if (c.isNull(4)) 0 else c.getLong(4)), mime))
                }
                out
            }
        } catch (e: Exception) { null }
    }

    /** Document id of a relative path, or null when a part is missing. */
    private fun idOf(path: String): String? {
        if (path.isEmpty()) return rootId
        ids[path]?.let { return it }
        val parent = path.substringBeforeLast('/', "")
        val name = path.substringAfterLast('/')
        val pid = idOf(parent) ?: return null
        val row = query(pid)?.firstOrNull { it.entry.name == name } ?: return null
        ids[path] = row.id
        return row.id
    }

    override fun list(dir: String): List<SharedEntry>? {
        val id = idOf(dir) ?: return null
        val rows = query(id) ?: run { ids.remove(dir); return null }
        for (r in rows) ids[if (dir.isEmpty()) r.entry.name else "$dir/${r.entry.name}"] = r.id
        return rows.map { it.entry }
    }

    override fun read(path: String): ByteArray? {
        val id = idOf(path) ?: return null
        return try { cr.openInputStream(docUri(id))?.use { it.readBytes() } } catch (e: Exception) { ids.remove(path); null }
    }

    private fun mkdirs(dir: String): String? {
        if (dir.isEmpty()) return rootId
        idOf(dir)?.let { return it }
        val pid = mkdirs(dir.substringBeforeLast('/', "")) ?: return null
        val created = try {
            DocumentsContract.createDocument(cr, docUri(pid), Document.MIME_TYPE_DIR, dir.substringAfterLast('/'))
        } catch (e: Exception) { null } ?: return null
        val id = DocumentsContract.getDocumentId(created)
        ids[dir] = id
        return id
    }

    override fun write(path: String, bytes: ByteArray) {
        val dir = path.substringBeforeLast('/', "")
        val name = path.substringAfterLast('/')
        val pid = mkdirs(dir) ?: return
        delete(path)                                   // createDocument would otherwise name the copy "x (1)"
        val tmpName = "$name.tmp"
        delete(if (dir.isEmpty()) tmpName else "$dir/$tmpName")
        val tmp = DocumentsContract.createDocument(cr, docUri(pid), "application/octet-stream", tmpName) ?: return
        cr.openOutputStream(tmp, "wt")?.use { it.write(bytes) }
        val renamed = DocumentsContract.renameDocument(cr, tmp, name)
        if (renamed != null) ids[path] = DocumentsContract.getDocumentId(renamed)
    }

    override fun delete(path: String) {
        val id = ids.remove(path) ?: idOf(path) ?: return
        ids.remove(path)
        try { DocumentsContract.deleteDocument(cr, docUri(id)) } catch (e: Exception) { /* already gone */ }
    }

    /** Creates `marker.json` (pairing.schema.json#/LocalMarker) when it is not there yet. */
    fun ensureMarker(appVersion: String, emulator: String?) {
        if (idOf("marker.json") != null) return
        val now = java.time.Instant.now().toString().substringBefore('.').removeSuffix("Z") + "Z"
        val em = emulator?.let { ",\"emulator\":\"" + it.replace("\"", "").take(40) + "\"" } ?: ""
        val json = "{\"schema\":1,\"app\":\"oni-companion\",\"createdAt\":\"$now\",\"appVersion\":\"$appVersion\"$em}"
        write("marker.json", json.toByteArray())
        mkdirs("companion")
    }
}
