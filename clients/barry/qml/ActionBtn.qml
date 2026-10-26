// A button for a Screen `action`. One tap sends one command: "Sent", then "Done" or the
// error. Tapping again sends again (that is how "Show in game" catches up with a walker).
import QtQuick

Rectangle {
    id: b
    property var app
    property var action
    property string phase: "idle"      // idle | sent | done | failed
    readonly property real s: app.s
    // v1.3: enabled false = greyed; a tap (or long press) shows `reason` instead of sending.
    readonly property bool usable: !(action && action.enabled === false)
    opacity: usable ? 1 : 0.45
    objectName: "action-" + (action ? action.id : "")
    implicitWidth: Math.max(180 * s, lbl.implicitWidth + 48 * s)
    implicitHeight: 72 * s
    radius: app.theme.radius
    // Done / Failed: a solid fill with black or white text, whichever reads (a 25% tint on a white card was unreadable)
    color: phase === "failed" ? app.theme.bad : phase === "done" ? app.theme.good
         : th.pressed ? app.theme.buttonPressed : app.theme.buttonNormal
    readonly property bool ended: phase === "done" || phase === "failed"
    readonly property color endText: (0.299 * color.r + 0.587 * color.g + 0.114 * color.b) > 0.55 ? "#000000" : "#ffffff"
    border.width: Math.max(1, 2 * s)
    readonly property bool danger: !!(action && action.danger)   // v1.2: Dismiss
    border.color: phase === "failed" ? app.theme.bad : phase === "done" ? app.theme.good : danger ? app.theme.bad : app.theme.accent

    function finish(state, msg) {
        watchdog.stop()
        phase = state === "done" ? "done" : "failed"
        if (phase === "failed") app.toast(msg || "That did not work.")
        resetTimer.restart()
    }
    function why() { app.notify((action && action.reason) || "Not available right now.") }
    function send() {
        if (phase === "sent") return
        if (!usable) { why(); return }
        // v1.3: an action with `confirm` asks first and posts only on Yes
        if (action && action.confirm) { app.ask(action.confirm, doSend); return }
        doSend()
    }
    function doSend() {
        if (phase === "sent") return
        phase = "sent"
        watchdog.restart()
        app.runAction(action, function(state, msg) {
            try { if (state !== "sent") b.finish(state, msg) } catch (e) { /* the page was rebuilt meanwhile */ }
        })
    }
    Skin { app: b.app; opacity: (b.phase === "done" || b.phase === "failed") ? 0 : 1; name: th.pressed ? "buttonPressed" : "button" }
    Text {
        id: lbl
        anchors.centerIn: parent
        text: b.phase === "sent" ? "Sent" : b.phase === "done" ? "Done" : b.phase === "failed" ? "Failed"
              : (b.action ? b.action.label : "")
        color: b.ended ? b.endText : b.danger && b.phase === "idle" ? b.app.theme.bad : b.app.theme.buttonText
        font { family: b.app.theme.font; pixelSize: b.app.theme.small + 2; weight: Font.DemiBold }
    }
    // Not polling: a single shot that ends "Sent" if no answer ever arrives.
    Timer { id: watchdog; interval: 15000; onTriggered: b.finish("failed", "The game did not answer.") }
    Timer { id: resetTimer; interval: 3500; onTriggered: if (b.phase !== "sent") b.phase = "idle" }
    TapHandler { id: th; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: b.send()
                 onLongPressed: if (!b.usable) b.why() }
}
