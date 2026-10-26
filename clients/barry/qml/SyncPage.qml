// Art & font sync (v1.2): "Sync art & fonts from your game". Shown over the pages (not a tab): the first time the core
// reports that a sync is needed, and from Settings ("Re-sync art & fonts"). Every word and number comes from GET /sync via
// app.syncInfo; this file only lays them out. The user may leave (Hide): the sync keeps running in the game, and a chip in
// the header brings this screen back.
import QtQuick

Item {
    id: sp
    property var app
    readonly property real s: app.s
    readonly property var info: app.syncInfo || ({})
    readonly property string state: info.state || "idle"
    readonly property bool running: state === "running"
    readonly property bool canStart: info.canStart === true
    readonly property bool queued: info.queued === true && !running     // asked for; the core sends it once a colony runs
    objectName: "syncPage"

    function num(n) { return Number(n || 0).toLocaleString(Qt.locale(), "f", 0) }
    function seconds(ms) { return Math.max(1, Math.round((ms || 0) / 1000)) }
    readonly property string headline: {
        if (running) return "Syncing art & fonts"
        if (queued) return "Sync is waiting for the game"
        if (state === "done" && !info.needed) return "Sync finished"
        if (state === "failed") return "The sync did not finish"
        return "Sync art & fonts from your game"
    }
    readonly property string explain: {
        if (running)
            return info.total > 0 ? "Drawing the pictures from your own copy of the game. The game is paused until this is done, then it goes on at the speed it had."
                                  : "Waiting for the game to start..."
        if (queued)
            return info.message ? info.message + " The sync starts by itself when it can. You can leave this screen." : info.reason === "menu" ? "The game is at its menu. The sync starts by itself when you load a colony. You can leave this screen."
                                          : "The sync starts by itself when you load a colony in Oxygen Not Included with the ONI Companion Link mod on. You can leave this screen."
        if (state === "done" && !info.needed)
            return num(info.total) + " items checked" + (info.elapsedMs > 0 ? " in " + seconds(info.elapsedMs) + " s" : "") + "." +
                   (info.errors > 0 ? " " + info.errors + " could not be drawn." : "")
        if (state === "failed") return info.lastError || "Something went wrong. You can try again."
        if (info.neededReason === "new_build") return "The game was updated. Its pictures and fonts are copied again."
        if (info.neededReason === "new_dlc") return "A DLC was added. Only what is new is copied."
        return "This app shows the pictures and fonts of your own game. They are copied from it once, and nothing from the game is stored in the app itself."
    }

    Rectangle { anchors.fill: parent; color: sp.app.theme.bg }
    TapHandler { }                                   // nothing behind the screen can be tapped

    Flickable {
        anchors { fill: parent; margins: 32 * sp.s }
        contentHeight: col.implicitHeight
        clip: true
        Column {
            id: col
            width: parent.width
            spacing: 28 * sp.s
            Text {
                width: parent.width
                wrapMode: Text.Wrap
                text: sp.headline
                color: sp.app.theme.pageText
                font { family: sp.app.theme.font; pixelSize: Math.round(sp.app.theme.body * 1.2); weight: Font.Bold }
            }
            Text {
                width: parent.width
                wrapMode: Text.Wrap
                text: sp.explain
                color: sp.app.theme.muted
                font { family: sp.app.theme.font; pixelSize: sp.app.theme.body }
            }
            Rectangle {   // the game is not running with the mod and a colony
                visible: !sp.running && !sp.canStart && !sp.queued
                objectName: "syncStartGame"
                width: parent.width
                implicitHeight: sg.implicitHeight + 40 * sp.s
                height: implicitHeight
                radius: sp.app.theme.radius
                color: Qt.rgba(sp.app.theme.warn.r, sp.app.theme.warn.g, sp.app.theme.warn.b, 0.14)
                border.color: sp.app.theme.warn
                border.width: Math.max(1, 2 * sp.s)
                Column {
                    id: sg
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 24 * sp.s }
                    spacing: 6 * sp.s
                    Text {
                        width: parent.width
                        wrapMode: Text.Wrap
                        text: "No colony is running yet"
                        color: sp.app.theme.warn
                        font { family: sp.app.theme.font; pixelSize: sp.app.theme.body; weight: Font.Bold }
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.Wrap
                        text: sp.info.message ? sp.info.message + " Tap Start sync now: it begins when a colony is running." : sp.info.reason === "menu" ? "The game is at its menu. Tap Start sync now: it begins when you load a colony."
                                                        : "Tap Start sync now: it begins when you start the game with the ONI Companion Link mod on and load a colony."
                        color: sp.app.theme.pageText
                        font { family: sp.app.theme.font; pixelSize: sp.app.theme.small + 2 }
                    }
                }
            }
            Column {   // progress: the item being drawn, the count, a bar
                visible: sp.running && sp.info.total > 0
                objectName: "syncProgress"
                width: parent.width
                spacing: 8 * sp.s
                Row {
                    width: parent.width
                    Text {
                        width: parent.width - cnt.implicitWidth
                        elide: Text.ElideRight
                        text: sp.info.current || ""
                        color: sp.app.theme.muted
                        font { family: sp.app.theme.font; pixelSize: sp.app.theme.small }
                    }
                    Text {
                        id: cnt
                        objectName: "syncCount"
                        text: sp.num(sp.info.done) + " / " + sp.num(sp.info.total)
                        color: sp.app.theme.pageText
                        font { family: sp.app.theme.font; pixelSize: sp.app.theme.body; weight: Font.DemiBold }
                    }
                }
                Rectangle {
                    width: parent.width
                    height: 16 * sp.s
                    radius: height / 2
                    color: sp.app.theme.progressTrack
                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(1, (sp.info.done || 0) / Math.max(1, sp.info.total || 1)))
                        height: parent.height
                        radius: parent.radius
                        color: sp.app.theme.progressFill
                    }
                }
            }
            Text {
                visible: sp.running && sp.info.errors > 0
                width: parent.width
                wrapMode: Text.Wrap
                text: sp.info.errors + " could not be drawn" + (sp.info.lastError ? ": " + sp.info.lastError : "")
                color: sp.app.theme.warn
                font { family: sp.app.theme.font; pixelSize: sp.app.theme.small + 2 }
            }
            Row {
                spacing: 20 * sp.s
                Btn {
                    visible: !sp.running && !sp.queued
                    objectName: "syncStart"
                    app: sp.app
                    primary: true
                    label: sp.state === "failed" ? "Try again" : sp.state === "done" && !sp.info.needed ? "Sync again" : "Start sync"
                    onTapped: sp.app.startSync(sp.app.syncScope)
                }
                Btn {
                    objectName: "syncHide"
                    app: sp.app
                    label: sp.running || sp.queued ? "Hide" : sp.state === "done" && !sp.info.needed ? "Close" : "Not now"
                    onTapped: sp.app.syncOpen = false
                }
                Btn {
                    visible: sp.queued
                    objectName: "syncCancel"
                    app: sp.app
                    label: "Cancel sync"
                    onTapped: sp.app.cancelSync()
                }
            }
        }
    }
}
