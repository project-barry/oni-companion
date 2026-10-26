import QtQuick

Rectangle {
    id: n
    property var app
    property var block
    width: parent ? parent.width : 0
    readonly property string lvl: block.level || "info"
    readonly property color tint: lvl === "error" ? app.theme.bad : lvl === "warn" ? app.theme.warn : app.theme.accent
    implicitHeight: col.implicitHeight + 36 * app.s
    height: implicitHeight
    radius: app.theme.radius
    color: Qt.rgba(tint.r, tint.g, tint.b, 0.14)
    border.color: tint
    border.width: Math.max(1, 2 * app.s)
    Column {
        id: col
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 24 * n.app.s }
        spacing: 4 * n.app.s
        Text {
            visible: !!n.block.title
            width: parent.width
            wrapMode: Text.Wrap
            text: n.block.title || ""
            color: n.tint
            font { family: n.app.theme.font; pixelSize: n.app.theme.body; weight: Font.Bold }
        }
        Text {
            width: parent.width
            wrapMode: Text.Wrap
            text: n.block.text || ""
            color: n.app.theme.pageText
            font { family: n.app.theme.font; pixelSize: n.app.theme.body }
        }
    }
}
