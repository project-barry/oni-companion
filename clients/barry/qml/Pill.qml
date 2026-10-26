// A small rounded label (chip or badge).
import QtQuick

Rectangle {
    id: p
    property var app
    property string label: ""
    property color tint: app.theme.muted
    property bool filled: false
    property bool onPanel: false          // drawn on a light panel: a light tint (the game's yellow) is darkened until it reads
    readonly property real lum: 0.2126 * tint.r + 0.7152 * tint.g + 0.0722 * tint.b
    readonly property color ink: (onPanel && app.theme.game && lum > 0.4) ? Qt.darker(tint, 2.4) : tint
    implicitWidth: t.implicitWidth + 28 * app.s
    implicitHeight: 44 * app.s
    radius: height / 2
    color: filled ? Qt.rgba(tint.r, tint.g, tint.b, 0.22) : "transparent"
    border.color: ink
    border.width: Math.max(1, 2 * app.s)
    Text {
        id: t
        anchors.centerIn: parent
        text: p.label
        color: p.ink
        font { family: p.app.theme.font; pixelSize: p.app.theme.small; weight: Font.DemiBold }
    }
}
