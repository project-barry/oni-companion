// The game's 9-slice image for `name` (panel, header, button, buttonHover, buttonPressed,
// tab, tabActive), drawn over the parent's area. Invisible until the image has loaded, and
// when the theme has none: the plain rectangle underneath is the fallback.
import QtQuick

Item {
    id: sk
    property var app
    property string name: ""
    readonly property var sl: app.theme.slice(name)
    readonly property real k: Math.max(1, app.s * 2)   // source pixels -> screen pixels
    anchors.fill: parent
    visible: !!sl && img.status === Image.Ready
    Item {
        width: sk.width / sk.k
        height: sk.height / sk.k
        scale: sk.k
        transformOrigin: Item.TopLeft
        BorderImage {
            id: img
            anchors.fill: parent
            asynchronous: true
            smooth: true
            source: sk.sl ? sk.app.artUrl(sk.sl.art) : ""
            border.left: sk.sl ? sk.sl.insets.left : 0
            border.top: sk.sl ? sk.sl.insets.top : 0
            border.right: sk.sl ? sk.sl.insets.right : 0
            border.bottom: sk.sl ? sk.sl.insets.bottom : 0
        }
    }
}
