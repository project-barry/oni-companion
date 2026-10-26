import QtQuick

Tap {
    id: l
    property var block
    width: parent ? parent.width : 0
    implicitHeight: 88 * app.s
    height: implicitHeight
    radius: app.theme.radius
    base: app.theme.panel
    border.color: app.theme.line
    border.width: Math.max(1, 2 * app.s)
    onTapped: app.openUrl(block.url)
    Row {
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 26 * l.app.s }
        spacing: 12 * l.app.s
        Text {
            width: parent.width - arrow.width - parent.spacing
            elide: Text.ElideRight
            text: l.block.label || l.block.url || ""
            color: l.app.theme.accent
            font { family: l.app.theme.font; pixelSize: l.app.theme.body; weight: Font.DemiBold }
        }
        Text {
            id: arrow
            text: "↗"
            color: l.app.theme.accent
            font { family: l.app.theme.font; pixelSize: l.app.theme.body }
        }
    }
}
