// ONI Companion for Barry. QML only renders blocks and navigates: every
// page, number and word of the content comes from the core (service.py).
import QtQuick
import "qml"

Rectangle {
    id: root
    objectName: "oniRoot"
    required property var barry
    readonly property real s: barry.scale
    property var theme: themeObj
    color: theme.bg

    Theme { id: themeObj; s: root.s }
    GameFonts { id: gameFonts; app: root }
    property alias fonts: gameFonts

    // ---- state ----
    // The tabs come from the core (GET /tabs: names, order, paths); until it answers (or against an older core)
    // the six of v1.3 below are used. A path "kinds" is the encyclopedia (look-up + calculators).
    readonly property var defaultTabs: [
        { "id": "colony", "label": "Colony", "path": "colony" },
        { "id": "resources", "label": "Resources", "path": "resources" },
        { "id": "buildings", "label": "Buildings", "path": "buildings" },
        { "id": "actions", "label": "Actions", "path": "pad" },
        { "id": "codex", "label": "Database", "path": "kinds", "excludeKinds": ["building"], "includesTools": true },
        { "id": "settings", "label": "Settings", "path": "settings" } ]
    property var tabList: defaultTabs
    readonly property var tabNames: tabList.map(function(t) { return t.label })
    property int tab: 0
    function rootEntry(t) {
        if (t.path === "kinds") return { "type": "lookup", "excludeKinds": t.excludeKinds || [], "tools": t.includesTools === true }
        return t.id === "settings" ? { "type": "screen", "path": t.path, "closeBar": true } : { "type": "screen", "path": t.path }
    }
    property var stacks: defaultTabs.map(function(t) { return [rootEntry(t)] })
    function applyTabs(list) {
        if (!list || list.length === 0 || JSON.stringify(list) === JSON.stringify(tabList)) return
        tabList = list
        tab = Math.min(tab, list.length - 1)
        stacks = list.map(function(t) { return [rootEntry(t)] })
        showTop()
    }
    property string filterText: ""        // the open page's filter field (lower case)
    property var groupOpen: ({})          // group open/closed choices, kept across live refreshes
    property var pendingActions: ({})     // seq -> callback, until the game's answer arrives
    property string toastText: ""
    property bool toastBad: true          // false: a plain note (why a button is greyed), not an error
    property var askState: null           // { text, yes }: the Yes / No question over the page
    property var currentPage: null
    property bool connected: false
    property int seq: 0
    // ---- v1.2: art & font sync (qml/SyncPage.qml) ----
    property var syncInfo: ({})           // GET /sync
    property bool syncOpen: false         // the sync screen is over the pages
    property bool syncAsked: false        // it opened by itself once already in this run
    property string syncScope: ""         // "" = the core's suggestion, "full" = from Settings
    // v1.2: the game's speed control (GET /controls) and a long-pressed row's revealed buttons
    property var controls: null           // last /controls reply
    property bool controlsHidden: false   // the core has no /controls (older core): no bar
    property string pendingBtn: ""        // the pressed button until the game confirms it
    property string revealKey: ""
    property real revealedAt: 0
    property var kindLabels: ({})
    signal changed(var names)

    readonly property var topEntry: stacks[tab][stacks[tab].length - 1]
    readonly property bool canGoBack: stacks[tab].length > 1

    // ---- service calls ----
    function get(path, done) { barry.request("GET", "api/v1/" + path, null, done) }
    function post(path, body, done) { barry.request("POST", "api/v1/" + path, body, done) }
    function errorText(st, r) {
        if (st === 0) return "Can't reach the ONI Companion service."
        if (r && r.error && r.error.message) return r.error.message
        return "Something went wrong (" + st + ")."
    }

    // ---- navigation ----
    function showTop() {
        hideReveal()
        const t = topEntry
        const f = t.type === "lookup" ? "LookupPage.qml" : t.type === "connect" ? "ConnectPage.qml" : "ScreenPage.qml"
        pageLoader.setSource("qml/" + f, { "app": root, "entry": t })
    }
    function setStack(i, arr) {
        const x = stacks.slice(); x[i] = arr; stacks = x
        showTop()
    }
    function push(entry) { setStack(tab, stacks[tab].concat([entry])) }
    function pop() { if (canGoBack) setStack(tab, stacks[tab].slice(0, -1)) }
    function goTab(i) {
        syncOpen = false                  // leaving the sync screen: it keeps running, the header chip brings it back
        hideReveal()
        if (i === tab) { if (canGoBack) setStack(tab, stacks[tab].slice(0, 1)); return }
        tab = i
        showTop()
    }
    function openRef(ref) {
        if (ref && ref.kind && ref.id !== undefined)
            push({ "type": "screen", "path": "entry/" + encodeURIComponent(ref.kind) + "/" + encodeURIComponent(ref.id) })
    }
    function reveal(key) { revealKey = key; revealedAt = Date.now() }
    function hideReveal() { if (revealKey !== "") revealKey = "" }
    function openUrl(url) { if (/^https:\/\//.test(url)) Qt.openUrlExternally(url) }
    function activateLink(link) {
        if (link.indexOf("ref:") === 0) {
            const p = link.substring(4).split(":")
            openRef({ "kind": decodeURIComponent(p[0]), "id": decodeURIComponent(p.slice(1).join(":")) })
        } else openUrl(link)
    }

    // ---- tools ----
    // endpoint (v1.1, from a form block): post there instead of tools/<tool>, e.g. "/settings"
    function submitTool(tool, values, done, endpoint) {
        post(endpoint ? endpoint.replace(/^\//, "") : "tools/" + encodeURIComponent(tool), { "values": values }, function(st, r) {
            if (done) done()
            if (!currentPage) return
            if (st === 200 && r && r.blocks) { currentPage.failed = false; currentPage.setResult(r) }
            else currentPage.toolFailed(st, r)
        })
    }
    function pickElement(filter, cb) {
        picker.cb = cb
        picker.visible = true
        picker.open(filter)
    }
    function nameOf(kind, id, cb) {
        get("search?q=" + encodeURIComponent(id) + "&kind=" + kind + "&limit=10", function(st, r) {
            if (st !== 200 || !r) return
            for (const x of (r.results || [])) if (x.id === id) { cb(x.name); return }
        })
    }

    // ---- v1.1: art, actions, filter, toast ----
    // An art path from the core ("/api/v1/art/...") as an Image source (the token rides in the query).
    function artUrl(path) {
        if (!path || !barry.serviceUrl) return ""
        return barry.serviceUrl.replace(/\/$/, "") + path + "?token=" + encodeURIComponent(barry.serviceToken)
    }
    // Sends one action. cb(state, message): "sent" at once, then "done" or "failed".
    function runAction(action, cb0) {
        const dismissing = action.id === "alert_dismiss"
        const cb = function(state, msg) {
            cb0(state, msg)
            // A dismissed alert's own page is gone: go back to the list.
            if (dismissing && state === "done" && /^entry\/alert\//.test(topEntry.path || "")) pop()
        }
        post("actions/" + encodeURIComponent(action.id), action.args || ({}), function(st, r) {
            if (st === 200 && r && r.seq) {
                cb("sent", "")
                const x = pendingActions; x[r.seq] = cb; pendingActions = x
                checkAction(r.seq)
            } else cb("failed", errorText(st, r))
        })
    }
    function checkAction(seq) {
        get("actions/" + seq, function(st, r) {
            const cb = pendingActions[seq]
            if (!cb) return
            if (st !== 200 || !r) { drop(seq); cb("failed", errorText(st, r)); return }
            if (r.state === "pending") return
            drop(seq)
            if (r.state === "done") cb("done", "")
            else cb("failed", r.message || (r.state === "expired" ? "The game did not answer." : "That did not work."))
        })
    }
    function drop(seq) { const x = pendingActions; delete x[seq]; pendingActions = x }
    function toast(text) { toastBad = true; toastText = text; toastTimer.restart() }
    function notify(text) { toastBad = false; toastText = text; toastTimer.restart() }   // a greyed button's reason
    // Asks first (Yes / No); `yes` runs only on Yes. Used for the one action that writes into the game's folder.
    function ask(text, yes) { askState = { "text": text, "yes": yes } }
    function titleMatches(t) { return filterText === "" || String(t || "").toLowerCase().indexOf(filterText) >= 0 }
    function blockHasMatch(b) {
        if (!b) return false
        if (b.type === "list") return (b.items || []).some(function(i) { return titleMatches(i.title) })
        if (b.type === "grid") return (b.cards || []).some(function(i) { return titleMatches(i.title) })
        if (b.type === "group") return (b.blocks || []).some(blockHasMatch)
        return false
    }
    function loadSync() {
        get("sync", function(st, r) {
            if (st !== 200 || !r) return
            const wasRunning = syncInfo.state === "running"
            syncInfo = r
            if (!syncAsked && r.needed) { syncAsked = true; syncOpen = true }
            if (wasRunning && r.state !== "running") loadTheme()     // the sync wrote a new theme
        })
    }
    function openSync(scope) { syncScope = scope || ""; syncOpen = true; loadSync() }
    function startSync(scope) {
        post("sync", scope ? { "scope": scope } : ({}), function(st, r) {
            if (st === 200 && r) syncInfo = r
            else toast(errorText(st, r))
        })
    }
    function cancelSync() {
        post("sync", { "cancel": true }, function(st, r) { if (st === 200 && r) syncInfo = r })
    }
    // ---- v1.2: speed control ----
    // Pause and the speed buttons are highlighted on their own, like the game: Pause while paused, and the selected
    // speed always. A pressed button shows at once (pending) and then follows the real state.
    function speedPaused() {
        if (pendingBtn === "pause") return !(controls && controls.paused)       // a toggle: the opposite of the state it was pressed in
        if (!controls || controls.available !== true) return false
        if (controls.pending && controls.pending.state !== "speed") return controls.pending.state === "pause"
        return controls.paused === true
    }
    function speedSelected() {
        if (pendingBtn.indexOf("speed") === 0) return Number(pendingBtn.substring(5))
        if (!controls || controls.available !== true) return 0
        if (controls.pending && controls.pending.speed) return controls.pending.speed
        return controls.speed || 0
    }
    function loadControls() {
        get("controls", function(st, r) {
            if (st === 404) { controlsHidden = true; controls = null; return }
            controlsHidden = false
            if (st === 200 && r) {
                controls = r
                if (!r.pending) pendingBtn = ""     // the command is settled: show the game's real state
            } else controls = { "available": false }
        })
    }
    function setSpeed(key) {
        if (!controls || controls.available !== true) return
        const body = key === "pause" ? { "state": controls.paused ? "play" : "pause" } : { "state": "speed", "speed": Number(key.substring(5)) }
        pendingBtn = key
        pendingTimer.restart()
        post("controls", body, function(st, r) {
            if (st === 200 && r) controls = r
            else { pendingBtn = ""; toast(errorText(st, r)) }
        })
    }
    Timer { id: pendingTimer; interval: 10000; onTriggered: root.pendingBtn = "" }
    function loadTheme() {
        get("theme", function(st, r) { if (st === 200 && r) { themeObj.apply(r); gameFonts.refresh() } })
    }
    onChanged: (names) => {
        if (names.indexOf("action") >= 0) for (const k of Object.keys(pendingActions)) checkAction(Number(k))
        if (names.indexOf("gamedata") >= 0) loadTheme()
        if (names.indexOf("sync") >= 0) loadSync()
        if (names.indexOf("controls") >= 0) loadControls()
    }
    Timer { id: toastTimer; interval: 4500; onTriggered: root.toastText = "" }

    // ---- small helpers for blocks ----
    function fmt(v) { return (v === undefined || v === null) ? "" : String(v) }
    function esc(t) { return String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function kindLabel(k) {
        if (kindLabels[k]) return kindLabels[k]
        return k ? k.charAt(0).toUpperCase() + k.slice(1) : ""
    }
    function conduitColor(c) {
        switch (c) {
        case "gas": return "#7fcfd8"
        case "liquid": return "#3f7fd0"
        case "solid": return "#a08a68"
        case "power": return "#e8b44a"
        case "logic": return "#4cc38a"
        default: return theme.muted
        }
    }
    function sourceLine(src, asOf) {
        if (!src) return ""
        const names = { "mod-live": "Live from the game", "save": "From your newest save",
                        "header": "From the save header", "mod-export": "From the game's own numbers",
                        "yaml": "From game files", "none": "No data" }
        let out = names[src] || src
        if (asOf) {
            const d = new Date(asOf)
            if (!isNaN(d.getTime())) out += " - " + d.toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
        }
        return out
    }

    // ---- events: long-poll, no polling ----
    function poll() {
        get("events?since=" + seq + "&timeout=25", function(st, r) {
            if (st === 200 && r) {
                if (!connected) { connected = true; changed(["colony", "gamedata", "status", "sync", "controls"]) }
                const first = seq === 0
                seq = r.seq
                if (!first && r.changed && r.changed.length > 0) changed(r.changed)
                Qt.callLater(poll)
            } else {
                connected = false
                retry.start()
            }
        })
    }
    Timer { id: retry; interval: 3000; onTriggered: root.poll() }

    Component.onCompleted: {
        get("kinds", function(st, r) {
            if (st !== 200 || !r) return
            const m = {}
            for (const k of (r.kinds || [])) m[k.kind] = k.label
            kindLabels = m
        })
        get("tabs", function(st, r) { if (st === 200 && r && r.tabs) applyTabs(r.tabs) })
        loadTheme()
        loadControls()
        showTop()
        poll()
    }

    // ---- layout ----
    Rectangle {
        id: bar
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 88 * root.s
        color: theme.header
        Skin { app: root; name: "header" }
        Tap {
            id: back
            app: root
            visible: root.canGoBack
            objectName: "backButton"
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 190 * root.s
            onTapped: root.pop()
            Text {
                anchors.centerIn: parent
                text: "‹  Back"
                color: theme.game ? theme.title : theme.accent
                font { family: theme.font; pixelSize: theme.body; weight: Font.DemiBold }
            }
        }
        HeaderText {
            app: root
            anchors { left: root.canGoBack ? back.right : parent.left; leftMargin: 28 * root.s; verticalCenter: parent.verticalCenter }
            width: 480 * root.s
            text: root.tabNames[root.tab]
            color: theme.title      // the game's title bars: textTitle (white) on the header color
            pixelSize: theme.body
            weight: Font.DemiBold
        }
        Tap {   // sync chip: progress while it runs, a reminder while it is needed (tap: the sync screen)
            id: syncChip
            visible: !root.syncOpen && (root.syncInfo.state === "running" || root.syncInfo.needed === true || root.syncInfo.queued === true)
            objectName: "syncChip"
            app: root
            anchors { right: conn.left; rightMargin: 24 * root.s; verticalCenter: parent.verticalCenter }
            width: chipText.implicitWidth + 36 * root.s
            height: 56 * root.s
            radius: height / 2
            base: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.25)
            border.color: theme.accent
            border.width: Math.max(1, 2 * root.s)
            onTapped: root.openSync("")
            Text {
                id: chipText
                anchors.centerIn: parent
                text: root.syncInfo.state === "running"
                      ? (root.syncInfo.total > 0 ? "Syncing " + Math.round(100 * root.syncInfo.done / root.syncInfo.total) + "%" : "Syncing...")
                      : root.syncInfo.queued ? "Sync waiting" : "Sync art & fonts"
                color: theme.game ? theme.title : theme.accent
                font { family: theme.font; pixelSize: theme.small; weight: Font.DemiBold }
            }
        }
        Row {
            id: conn
            anchors { right: parent.right; rightMargin: 28 * root.s; verticalCenter: parent.verticalCenter }
            spacing: 12 * root.s
            // What the game is doing (the core decides: GET /controls `game`); red only when the app's own service is gone.
            readonly property var game: root.connected && root.controls && root.controls.game ? root.controls.game : null
            Rectangle {
                width: 16 * root.s; height: width; radius: width / 2
                anchors.verticalCenter: parent.verticalCenter
                color: !conn.game ? theme.bad : conn.game.tone === "good" ? theme.good : conn.game.tone === "warn" ? theme.warn : theme.muted
            }
            Text {
                objectName: "gameState"
                text: !root.connected ? "Service not responding" : conn.game ? conn.game.label : "Connecting..."
                color: theme.game ? theme.title : theme.muted
                font { family: theme.font; pixelSize: theme.small }
            }
        }
    }

    SpeedBar {
        id: speedBar
        app: root
        anchors { left: parent.left; right: parent.right; top: bar.bottom }
    }

    Rectangle {   // behind every page: nothing shows through while one page replaces another
        anchors { left: parent.left; right: parent.right; top: speedBar.bottom; bottom: tabs.top }
        color: root.theme.bg
    }
    Loader {
        id: pageLoader
        anchors { left: parent.left; right: parent.right; top: speedBar.bottom; bottom: tabs.top }
        clip: true
    }

    Rectangle {
        id: tabs
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 104 * root.s
        color: theme.tabBg
        Row {
            anchors.fill: parent
            Repeater {
                model: root.tabNames
                delegate: Tap {
                    id: tb
                    required property string modelData
                    required property int index
                    app: root
                    objectName: "tab" + index
                    width: tabs.width / root.tabNames.length
                    height: tabs.height
                    onTapped: root.goTab(index)
                    base: root.tab === tb.index ? theme.tabActiveBg : theme.tabBg
                    Skin { app: root; name: root.tab === tb.index ? "tabActive" : "tab" }
                    Rectangle {
                        visible: root.tab === tb.index
                        width: parent.width * 0.5; height: 6 * root.s; radius: height / 2
                        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter }
                        color: theme.accent
                    }
                    Text {
                        anchors.centerIn: parent
                        text: tb.modelData
                        color: root.tab === tb.index ? theme.tabTextActive : theme.tabText
                        font { family: theme.font; pixelSize: Math.round(30 * root.s); weight: root.tab === tb.index ? Font.Bold : Font.Normal }
                    }
                }
            }
        }
    }

    Rectangle {   // short messages, e.g. an action the game could not run
        visible: root.toastText !== ""
        objectName: "toast"
        anchors { horizontalCenter: parent.horizontalCenter; bottom: tabs.top; bottomMargin: 24 * root.s }
        width: Math.min(parent.width - 64 * root.s, tt.implicitWidth + 56 * root.s)
        height: tt.implicitHeight + 32 * root.s
        radius: theme.radius
        color: root.toastBad ? "#3a1a1c" : theme.panel
        border.color: root.toastBad ? theme.bad : theme.accent
        Text {
            id: tt
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 28 * root.s }
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            text: root.toastText
            color: theme.text
            font { family: theme.font; pixelSize: theme.small + 2 }
        }
        TapHandler { onTapped: root.toastText = "" }
    }

    Rectangle {   // the Yes / No question (ask first)
        visible: root.askState !== null
        objectName: "askBox"
        anchors.fill: parent
        z: 2000
        color: Qt.rgba(0, 0, 0, 0.6)
        TapHandler { }   // swallows taps behind the question
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 96 * root.s, 900 * root.s)
            height: askCol.implicitHeight + 64 * root.s
            radius: theme.radius
            color: theme.panel
            border.color: theme.accent
            border.width: Math.max(1, 2 * root.s)
            Column {
                id: askCol
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 32 * root.s }
                spacing: 28 * root.s
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: root.askState ? root.askState.text : ""
                    color: theme.text
                    font { family: theme.font; pixelSize: theme.body }
                }
                Row {
                    spacing: 20 * root.s
                    Btn { objectName: "askYes"; app: root; label: "Yes"; primary: true; minW: 200 * root.s
                          onTapped: { const a = root.askState; root.askState = null; if (a && a.yes) a.yes() } }
                    Btn { objectName: "askNo"; app: root; label: "No"; minW: 200 * root.s; onTapped: root.askState = null }
                }
            }
        }
    }

    SyncPage {
        id: syncPage
        visible: root.syncOpen
        anchors { left: parent.left; right: parent.right; top: bar.bottom; bottom: tabs.top }
        app: root
    }

    ElementPicker {
        id: picker
        visible: false
        anchors.fill: parent
        app: root
        property var cb: null
        onPicked: (id, name) => { visible = false; if (cb) cb(id, name) }
        onCancelled: visible = false
    }

    // v1.2: a tap anywhere else hides a long-pressed row's revealed buttons (not the press that revealed them).
    // An observer on top: its grab is passive, so the tap still reaches whatever was tapped.
    Item {
        anchors.fill: parent
        z: 1000
        enabled: root.revealKey !== ""
        TapHandler {
            property real pressAt: 0
            onPressedChanged: if (pressed) pressAt = Date.now()
            onTapped: if (root.revealedAt < pressAt) root.hideReveal()
        }
    }
}
