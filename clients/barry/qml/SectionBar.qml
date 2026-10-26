// The game's section header bar (STATUS, CONDITION ...): the sectionHeader slice or color, white caps text.
// Used for block titles when a game theme is applied. Colors come from the theme tokens only.
import QtQuick

Rectangle {
    id: sb
    property var app
    property string text: ""
    width: parent ? parent.width : 0
    implicitHeight: Math.round(64 * app.s)
    height: implicitHeight
    color: app.theme.sectionHeader
    Skin { app: sb.app; name: "sectionHeader" }
    HeaderText {
        app: sb.app
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 22 * sb.app.s; rightMargin: 22 * sb.app.s }
        elide: Text.ElideRight
        text: sb.text
        color: sb.app.theme.sectionHeaderText
        pixelSize: sb.app.theme.small + 2
        caps: true
        letterSpacing: 1
    }
}
