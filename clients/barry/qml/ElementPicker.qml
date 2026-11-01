// Overlay: pick an element by searching. Calls picked(id, name).
import QtQuick
import Barry.Input

Rectangle {
    id: o
    property var app
    property string filter: "any"
    property var results: []
    property string status: ""
    signal picked(string id, string name)
    signal cancelled()
    color: app.theme.bg

    function open(flt) {
        filter = flt
        box.text = ""
        results = []
        status = "Type to search."
        // a full list when the core offers one for elements
        app.get("list/element", function(st, r) {
            if (st !== 200 || !r || box.text !== "") return
            const out = []
            for (const b of (r.blocks || []))
                if (b.type === "list") for (const it of (b.items || []))
                    if (it.ref) out.push({ "id": it.ref.id, "name": it.title, "subtitle": it.subtitle || "" })
            if (out.length) { results = out; status = "" }
        })
        box.inputItem.forceActiveFocus()
    }
    function search() {
        const q = box.text.trim()
        if (q === "") { results = []; status = "Type to search."; return }
        app.get("search?q=" + encodeURIComponent(q) + "&kind=element&limit=40", function(st, r) {
            if (box.text.trim() !== q) return
            if (st === 200 && r) {
                results = (r.results || []).map(function(x) { return { "id": x.id, "name": x.name, "subtitle": x.subtitle || "" } })
                status = results.length ? "" : "Nothing found."
            } else { results = []; status = app.errorText(st, r) }
        })
    }
    MouseArea { anchors.fill: parent }   // swallow taps
    Timer { id: deb; interval: 150; onTriggered: o.search() }
    Row {
        id: top
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 * o.app.s }
        spacing: 16 * o.app.s
        SearchField {
            id: box
            app: o.app
            width: parent.width - cancel.width - parent.spacing
            placeholder: "Search elements..."
            onEdited: deb.restart()
            onAccepted: o.search()
        }
        Btn { id: cancel; app: o.app; label: "Cancel"; height: box.height; onTapped: o.cancelled() }
    }
    TouchScroll {   // Barry's touch rules scroll it (Barry.Input)
        anchors { left: parent.left; right: parent.right; top: top.bottom; bottom: parent.bottom; topMargin: 20 * o.app.s }
        Flickable {
            anchors.fill: parent
            contentHeight: col.implicitHeight + 60 * o.app.s
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: col
                x: 32 * o.app.s
                width: parent.width - 64 * o.app.s
                spacing: 12 * o.app.s
                Text {
                    visible: !!o.status
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    topPadding: 30 * o.app.s
                    text: o.status
                    color: o.app.theme.muted
                    font { family: o.app.theme.font; pixelSize: o.app.theme.body }
                }
                Repeater {
                    model: o.results
                    delegate: NavRow {
                        required property var modelData
                        app: o.app
                        width: col.width
                        title: modelData.name
                        subtitle: modelData.subtitle
                        onTapped: o.picked(modelData.id, modelData.name)
                    }
                }
            }
        }
    }
}
