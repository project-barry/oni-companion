// A titled, collapsible group of blocks. The inner BlockView loads by file name.
import QtQuick

Rectangle {
    id: g
    property var app
    property var block
    // The open/closed choice survives a live refresh (the blocks are rebuilt); the key is the
    // title up to the first colon, because the core puts a changing total after it.
    readonly property string key: app.tab + "|" + String(block.title || "").replace(/[:(].*$/, "")
    property bool userOpen: app.groupOpen[key] !== undefined ? app.groupOpen[key] : !block.collapsed
    readonly property bool open: userOpen || app.filterText !== ""
    visible: app.filterText === "" || app.blockHasMatch(block)
    width: parent ? parent.width : 0
    implicitHeight: visible ? head.height + (open ? inner.height + 24 * app.s : 0) : 0
    height: implicitHeight
    radius: app.theme.radius
    color: "transparent"
    border.color: app.theme.line
    border.width: Math.max(1, 2 * app.s)
    clip: true
    Tap {
        id: head
        app: g.app
        width: parent.width
        height: 88 * g.app.s
        base: g.app.theme.game ? g.app.theme.sectionHeader : g.app.theme.header
        Skin { app: g.app; name: g.app.theme.game ? "sectionHeader" : "header" }
        onTapped: { g.userOpen = !g.userOpen; g.app.groupOpen[g.key] = g.userOpen }
        Text {
            anchors { left: parent.left; right: chev.left; verticalCenter: parent.verticalCenter; leftMargin: 26 * g.app.s }
            elide: Text.ElideRight
            text: g.block.title || ""
            color: g.app.theme.game ? g.app.theme.sectionHeaderText : g.app.theme.title
            font { family: g.app.theme.font; pixelSize: g.app.theme.body; weight: Font.Bold }
        }
        Text {
            id: chev
            anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 28 * g.app.s }
            text: g.open ? "▾" : "▸"
            color: g.app.theme.game ? g.app.theme.sectionHeaderText : g.app.theme.muted
            font { family: g.app.theme.font; pixelSize: g.app.theme.body }
        }
    }
    Loader {
        id: inner
        visible: g.open
        y: head.height + 12 * g.app.s
        x: 18 * g.app.s
        width: g.width - 36 * g.app.s
        height: item ? item.implicitHeight : 0
        Component.onCompleted: setSource("BlockView.qml", { "app": g.app, "blocks": g.block.blocks || [] })
        onLoaded: item.blocks = Qt.binding(function() { return g.block.blocks || [] })
    }
}
