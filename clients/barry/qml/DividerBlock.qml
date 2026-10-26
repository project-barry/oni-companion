import QtQuick

Item {
    property var app
    property var block
    width: parent ? parent.width : 0
    implicitHeight: 12 * app.s
    height: implicitHeight
    Rectangle { anchors.centerIn: parent; width: parent.width; height: Math.max(1, 2 * parent.app.s); color: parent.app.theme.line }
}
