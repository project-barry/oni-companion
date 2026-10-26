// A label, a sub line and an on/off switch in one tappable row (the Connect a phone switches).
import QtQuick

Tap {
    id: row
    property var app
    property string label: ""
    property string sub: ""
    property bool on: false
    property color subColor: app.theme.muted
    width: parent ? parent.width : 0
    implicitHeight: Math.max(96 * app.s, textCol.implicitHeight + 24 * app.s)
    height: implicitHeight
    radius: app.theme.radius
    base: app.theme.panel
    hi: app.theme.panelHi
    Column {
        id: textCol
        anchors { left: parent.left; right: track.left; verticalCenter: parent.verticalCenter; leftMargin: 24 * row.app.s; rightMargin: 20 * row.app.s }
        spacing: 6 * row.app.s
        Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: row.label
            color: row.app.theme.pageText
            font { family: row.app.theme.font; pixelSize: row.app.theme.body; weight: Font.DemiBold }
        }
        Text {
            visible: row.sub !== ""
            width: parent.width
            wrapMode: Text.Wrap
            text: row.sub
            color: row.subColor
            font { family: row.app.theme.font; pixelSize: row.app.theme.small }
        }
    }
    Rectangle {
        id: track
        width: 110 * row.app.s; height: 56 * row.app.s; radius: height / 2
        anchors { right: parent.right; rightMargin: 24 * row.app.s; verticalCenter: parent.verticalCenter }
        color: row.on ? row.app.theme.accent : row.app.theme.line
        Rectangle {
            width: 44 * row.app.s; height: width; radius: width / 2
            y: 6 * row.app.s
            x: row.on ? parent.width - width - 6 * row.app.s : 6 * row.app.s
            color: "white"
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
}
