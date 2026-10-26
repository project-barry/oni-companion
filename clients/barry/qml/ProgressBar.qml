// Label, "value / max unit", and a bar.
import QtQuick

Item {
    id: pb
    property var app
    property string label: ""
    property real value: 0
    property real max: 1
    property string unit: ""
    property string tone: "neutral"
    property bool onPanel: true         // false: drawn straight on the page background
    readonly property real frac: max > 0 ? Math.max(0, Math.min(1, value / max)) : 0
    readonly property color col: app.theme.meterColor(label, tone)
    implicitHeight: row.implicitHeight + bar.height + 10 * app.s
    height: implicitHeight
    Row {
        id: row
        width: parent.width
        Text {
            width: parent.width - amt.implicitWidth
            elide: Text.ElideRight
            text: pb.label
            color: pb.app.theme.game && pb.onPanel ? pb.app.theme.text : pb.app.theme.muted
            font { family: pb.app.theme.font; pixelSize: pb.app.theme.small }
        }
        Text {
            id: amt
            text: pb.app.fmt(pb.value) + " / " + pb.app.fmt(pb.max) + (pb.unit ? " " + pb.unit : "")
            color: pb.onPanel ? pb.app.theme.text : pb.app.theme.pageText
            font { family: pb.app.theme.font; pixelSize: pb.app.theme.small }
        }
    }
    Rectangle {
        id: bar
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 14 * pb.app.s
        radius: height / 2
        color: pb.app.theme.progressTrack
        Rectangle {
            width: parent.width * pb.frac
            height: parent.height
            radius: parent.radius
            color: pb.col
        }
    }
}
