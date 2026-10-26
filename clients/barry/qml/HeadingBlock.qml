import QtQuick

Item {
    id: h
    property var app
    property var block
    width: parent ? parent.width : 0
    implicitHeight: Math.max(t.implicitHeight, pic.height) + 8 * app.s
    height: implicitHeight
    readonly property int level: block.level || 2
    Art {
        id: pic
        app: h.app
        art: h.block.art || ""
        glyph: h.block.text || ""
        size: (h.level === 1 ? 96 : 64) * h.app.s
        anchors.verticalCenter: parent.verticalCenter
    }
    HeaderText {
        id: t
        app: h.app
        anchors { left: pic.right; leftMargin: pic.width > 0 ? 18 * h.app.s : 0; right: parent.right; verticalCenter: parent.verticalCenter }
        wrapMode: Text.Wrap
        text: h.block.text || ""
        color: h.level === 3 ? h.app.theme.muted : h.app.theme.title
        pixelSize: Math.round((h.level === 1 ? 50 : h.level === 2 ? 40 : 30) * h.app.s)
    }
}
