import QtQuick

Rectangle {
    property var app
    property var block
    width: parent ? parent.width : 0
    implicitHeight: t.implicitHeight + 40 * app.s
    height: implicitHeight
    radius: app.theme.radius
    color: app.theme.panel
    Text {
        id: t
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 24 * parent.app.s }
        wrapMode: Text.Wrap
        text: "Update the app to see this."
        color: parent.app.theme.muted
        font { family: parent.app.theme.font; pixelSize: parent.app.theme.body }
    }
}
