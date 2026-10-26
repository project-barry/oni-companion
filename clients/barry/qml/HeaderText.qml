// A header in the game's header font. In order: the Graystroke atlas (GameText) when the core has exported it and
// the text fits on one line, else Economica Bold from the game, else the body font. Same API as the Text it replaces.
import QtQuick

Item {
    id: h
    property var app
    property string text: ""
    property color color: app.theme.title
    property real pixelSize: app.theme.body
    property int weight: Font.Bold
    property bool caps: false
    property real letterSpacing: 0
    property int wrapMode: Text.NoWrap
    property int elide: Text.ElideNone
    readonly property string shown: caps ? text.toUpperCase() : text
    readonly property bool useAtlas: gt.ready && width > 0 && gt.naturalWidth <= width
    readonly property alias contentWidth: fb.contentWidth
    implicitHeight: fb.implicitHeight
    implicitWidth: useAtlas ? gt.naturalWidth : fb.implicitWidth

    GameText {
        id: gt
        app: h.app
        visible: h.useAtlas
        text: h.shown
        color: h.color
        pixelSize: h.pixelSize
        letterSpacing: h.letterSpacing
        anchors.verticalCenter: parent.verticalCenter
    }
    Text {
        id: fb
        visible: !h.useAtlas
        width: parent.width
        wrapMode: h.wrapMode
        elide: h.elide
        text: h.shown
        color: h.color
        font {
            family: h.app.theme.headerFont
            weight: h.weight
            pixelSize: Math.round(h.pixelSize)
            letterSpacing: h.letterSpacing
        }
    }
}
