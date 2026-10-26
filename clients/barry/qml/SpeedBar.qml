// The game's speed control on every page: Pause and the speeds 1, 2, 3. Pause toggles and is highlighted while paused;
// a speed button selects that speed (paused or not) and the selected one is highlighted. Rendering only: the core owns the
// state (GET /controls, POST /controls, the `controls` event). The pressed button shows at once
// (pending) and then follows the real state. Dimmed and not pressable while the game is not available.
import QtQuick

Rectangle {
    id: sb
    property var app
    readonly property var c: app.controls
    readonly property bool usable: app.connected && !!c && c.available === true
    readonly property bool paused: app.speedPaused()
    readonly property int selected: app.speedSelected()
    readonly property real s: app.s
    objectName: "speedBar"
    visible: !app.controlsHidden
    height: visible ? 96 * s : 0
    color: app.theme.panel
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Math.max(1, s)
        color: app.theme.line
    }
    Skin { app: sb.app; name: "header"; opacity: 0.0 }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 14 * sb.s
        opacity: sb.usable ? 1 : 0.38
        Behavior on opacity { NumberAnimation { duration: 150 } }
        Repeater {
            model: ["pause", "speed1", "speed2", "speed3"]
            delegate: Rectangle {
                id: btn
                required property string modelData
                readonly property bool on: modelData === "pause" ? sb.paused : sb.selected === Number(modelData.substring(5))
                readonly property var sprite: sb.app.theme.icon(modelData === "pause" ? "speedPause" : modelData)
                objectName: "speed-" + modelData
                width: 120 * sb.s
                height: 72 * sb.s
                radius: sb.app.theme.radius
                color: on ? Qt.rgba(sb.app.theme.accent.r, sb.app.theme.accent.g, sb.app.theme.accent.b, 0.30)
                       : th.pressed ? sb.app.theme.buttonPressed : sb.app.theme.buttonNormal
                border.width: Math.max(1, 2 * sb.s)
                border.color: on ? sb.app.theme.accent : sb.app.theme.line
                Skin { app: sb.app; name: th.pressed ? "buttonPressed" : "button"; opacity: btn.on ? 0 : 1 }
                Image {
                    id: pic
                    anchors.centerIn: parent
                    visible: !!btn.sprite && status === Image.Ready
                    width: 44 * sb.s; height: width
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    asynchronous: true
                    source: btn.sprite ? sb.app.artUrl(btn.sprite.art) : ""
                }
                SpeedGlyph {
                    anchors.centerIn: parent
                    visible: !pic.visible
                    kind: btn.modelData
                    size: 44 * sb.s
                    tint: btn.on ? sb.app.theme.pageText : sb.app.theme.buttonText
                }
                TapHandler {
                    id: th
                    enabled: sb.usable
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: sb.app.setSpeed(btn.modelData)
                }
            }
        }
    }
}
