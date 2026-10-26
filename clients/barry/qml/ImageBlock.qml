// An `image` block: one picture with an optional caption. Size is a hint.
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 8 * app.s
    readonly property real px: (block.size === "small" ? 120 : block.size === "large" ? 300 : 200) * app.s
    Art {
        app: c.app
        art: c.block.art || ""
        glyph: c.block.caption || c.block.alt || ""
        size: c.px
        anchors.horizontalCenter: parent.horizontalCenter
    }
    Text {
        visible: !!c.block.caption
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: c.block.caption || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.body }
    }
}
