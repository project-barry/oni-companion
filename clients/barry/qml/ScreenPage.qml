// Fetches one Screen path, shows it, and re-fetches when /events says it changed.
// v1.1: the world switcher re-fetches with ?world=, and `onOpen` actions run once, the
// first time the page is opened (not on a refresh, and not when Back returns to it).
import QtQuick

Item {
    id: p
    property var app
    property var entry
    property bool failed: false
    property string error: ""
    Rectangle { anchors.fill: parent; color: app.theme.bg; z: -1 }   // opaque, so a page never shows the one before it

    function url() {
        const w = entry.world
        return entry.path + (w === undefined ? "" : (entry.path.indexOf("?") >= 0 ? "&" : "?") + "world=" + w)
    }
    function opened(r) {
        if (entry.opened) return
        entry.opened = true
        for (const a of (r.onOpen || []))
            app.runAction({ "id": a.action, "args": a.args || ({}) }, function(state, msg) {
                if (state === "failed") app.toast(msg)
            })
    }
    function show(r) {
        entry.cache = r
        view.setScreen(r)
        opened(r)
    }
    function load(silent) {
        if (!silent && !view.screen) { failed = false; error = "" }
        app.get(url(), function(st, r) {
            if (st === 200 && r && r.blocks) {
                failed = false
                const js = JSON.stringify(r)
                if (js !== entry.json) { entry.json = js; show(r) }
            } else if (!silent || !view.screen) {
                failed = true
                error = app.errorText(st, r)
            }
        })
    }
    function setResult(r) { entry.json = JSON.stringify(r); show(r) }
    function toolFailed(st, r) { failed = true; error = app.errorText(st, r) }

    Component.onCompleted: {
        app.currentPage = p
        app.filterText = ""
        if (entry.cache) { view.screen = entry.cache; opened(entry.cache) }
        load(!!entry.cache)
    }
    Component.onDestruction: if (app.currentPage === p) app.currentPage = null

    Connections {
        target: p.app
        function onChanged(names) {
            const ro = (view.screen && view.screen.refreshOn) || []
            for (let i = 0; i < ro.length; i++)
                if (names.indexOf(ro[i]) >= 0) { p.load(true); return }
        }
    }

    ScreenView {
        id: view
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: parent.bottom; bottomMargin: p.entry.closeBar ? 352 * p.app.s : 0 }
        app: p.app
        message: p.failed && !screen ? p.error : (!screen ? "Loading..." : "")
        canRetry: p.failed && !screen
        onRetry: p.load(false)
        onWorldPicked: (id) => { p.entry.world = id; p.entry.json = ""; p.load(true) }
    }
    Column {   // Settings page: Connect a phone, Re-sync art & fonts, Refresh and Close app
        id: bar
        visible: !!p.entry.closeBar
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 24 * p.app.s }
        spacing: 16 * p.app.s
        Btn { objectName: "connectButton"; app: p.app; label: "Connect a phone"; width: parent.width; onTapped: p.app.push({ "type": "connect" }) }
        Btn { objectName: "resyncButton"; app: p.app; label: "Re-sync art & fonts"; width: parent.width; onTapped: p.app.openSync("full") }
        Row {
            width: parent.width
            spacing: 16 * p.app.s
            Btn { app: p.app; label: "Refresh"; width: (parent.width - parent.spacing) / 2; onTapped: p.load(true) }
            Btn { app: p.app; label: "Close app"; width: (parent.width - parent.spacing) / 2; onTapped: p.app.barry.close() }
        }
    }
    Rectangle {   // error from a form submit, over the content
        visible: p.failed && !!view.screen
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 24 * p.app.s; bottomMargin: (p.entry.closeBar ? 352 : 24) * p.app.s }
        height: et.implicitHeight + 36 * p.app.s
        radius: p.app.theme.radius
        color: "#3a1a1c"
        border.color: p.app.theme.bad
        Text {
            id: et
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 24 * p.app.s }
            wrapMode: Text.Wrap
            text: p.error
            color: p.app.theme.pageText
            font { family: p.app.theme.font; pixelSize: p.app.theme.body }
        }
        TapHandler { onTapped: p.failed = false }
    }
}
