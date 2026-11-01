// Look-up tab: a search box; with no text, the kinds; with text, ranked results.
import QtQuick
import Barry.Input

Item {
    id: p
    property var app
    property var entry
    Rectangle { anchors.fill: parent; color: app.theme.bg; z: -1 }   // opaque, so a page never shows the one before it
    property var kinds: []
    property var results: []
    property string status: ""
    property string shownQuery: ""
    property var tools: []                           // the calculators (shown under the kinds)
    readonly property var excluded: entry.excludeKinds || []
    function keep(k) { return excluded.indexOf(k) < 0 }

    function doSearch() {
        const q = box.text.trim()
        entry.q = box.text
        if (q === "") { results = []; status = ""; shownQuery = ""; return }
        app.get("search?q=" + encodeURIComponent(q) + "&limit=40", function(st, r) {
            if (box.text.trim() !== q) return            // stale answer
            shownQuery = q
            if (st === 200 && r) { results = (r.results || []).filter(function(x) { return keep(x.kind) }); status = results.length === 0 ? "Nothing found." : "" }
            else { results = []; status = app.errorText(st, r) }
        })
    }
    function loadKinds() {
        app.get("kinds", function(st, r) {
            if (st === 200 && r) { kinds = (r.kinds || []).filter(function(x) { return keep(x.kind) }); if (!entry.q) status = "" }
            else if (!entry.q) status = app.errorText(st, r)
        })
    }
    function loadTools() {
        if (!entry.tools) return
        app.get("tools", function(st, r) { if (st === 200 && r) tools = r.tools || [] })
    }
    Component.onCompleted: {
        box.text = entry.q || ""
        loadKinds()
        loadTools()
        if (box.text) doSearch()
    }
    Connections {
        target: p.app
        function onChanged(names) { if (names.indexOf("gamedata") >= 0) { p.loadKinds(); if (box.text.trim()) p.doSearch() } }
    }
    Timer { id: deb; interval: 150; onTriggered: p.doSearch() }

    SearchField {
        id: box
        objectName: "searchField"
        app: p.app
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 32 * p.app.s }
        placeholder: "Search elements, critters, plants..."
        onEdited: deb.restart()
        onAccepted: p.doSearch()
    }

    TouchScroll {   // Barry's touch rules scroll it (Barry.Input)
        anchors { left: parent.left; right: parent.right; top: box.bottom; bottom: parent.bottom; topMargin: 24 * p.app.s }
        Flickable {
            anchors.fill: parent
            contentHeight: list.implicitHeight + 80 * p.app.s
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: list
                x: 32 * p.app.s
                width: parent.width - 64 * p.app.s
                spacing: 12 * p.app.s
                Text {
                    visible: !!p.status
                    width: parent.width
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    topPadding: 30 * p.app.s
                    text: p.status
                    color: p.app.theme.muted
                    font { family: p.app.theme.font; pixelSize: p.app.theme.body }
                }
                Repeater {
                    model: box.text.trim() === "" ? p.kinds : []
                    delegate: NavRow {
                        required property var modelData
                        app: p.app
                        width: list.width
                        title: modelData.label || modelData.kind
                        badge: String(modelData.count)
                        onTapped: p.app.push({ "type": "screen", "path": "list/" + encodeURIComponent(modelData.kind) })
                    }
                }
                Text {
                    visible: box.text.trim() === "" && p.tools.length > 0
                    width: parent.width
                    topPadding: 16 * p.app.s
                    text: "Calculators"
                    color: p.app.theme.muted
                    font { family: p.app.theme.font; pixelSize: p.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
                }
                Repeater {
                    model: box.text.trim() === "" ? p.tools : []
                    delegate: NavRow {
                        required property var modelData
                        app: p.app
                        width: list.width
                        title: modelData.title || modelData.id
                        subtitle: modelData.summary || ""
                        onTapped: p.app.push({ "type": "screen", "path": "tools/" + encodeURIComponent(modelData.id) })
                    }
                }
                Repeater {
                    model: box.text.trim() === "" ? [] : p.results
                    delegate: NavRow {
                        required property var modelData
                        app: p.app
                        width: list.width
                        title: modelData.name || modelData.id
                        subtitle: (p.app.kindLabel(modelData.kind)) + (modelData.subtitle ? " - " + modelData.subtitle : "")
                        badge: (modelData.dlc || []).join(", ")
                        onTapped: p.app.openRef({ "kind": modelData.kind, "id": modelData.id })
                    }
                }
            }
        }
    }
}
