// A picture from the core's art folder (rendered from the user's own game). Takes no
// space when `art` is empty. While it loads or if the core has none (404), a plain tile
// with `glyph` shows instead: the v1 look.
// On-demand art (v1.2): the core asks the game for an image when this one asks for it, so
//  - an image is only asked for once its row is (nearly) on screen inside the page's Flickable
//    (and stays asked for once it has been), and
//  - when the core says the art manifest changed (`art` event) an image that came back 404 asks again.
import QtQuick

Item {
    id: a
    property var app
    property string art: ""
    property string glyph: ""
    property real size: 64 * app.s
    property bool fit: true
    width: art ? size : 0
    height: art ? size : 0
    visible: !!art
    property int retry: 0
    property bool shown: false
    property Item flick: null
    function findFlick() {
        var p = a.parent
        while (p) {
            if (p.contentY !== undefined && p.flickableDirection !== undefined) return p
            p = p.parent
        }
        return null
    }
    function recheck() {
        if (shown) return
        if (!flick) { shown = true; return }
        var y = a.mapToItem(flick, 0, 0).y
        if (y + a.height > -a.height && y < flick.height + a.height) shown = true
    }
    Component.onCompleted: { flick = findFlick(); recheck(); Qt.callLater(recheck) }
    Connections {
        target: a.flick
        ignoreUnknownSignals: true
        function onContentYChanged() { a.recheck() }
        function onHeightChanged() { a.recheck() }
        function onContentHeightChanged() { a.recheck() }
    }
    Connections {
        target: a.app
        ignoreUnknownSignals: true
        function onChanged(names) { if (names.indexOf("art") >= 0 && img.status === Image.Error) a.retry++ }
    }
    // The last picture that finished loading stays up while a different one loads (and through a failed reload),
    // so the placeholder only shows before any picture has been ready.
    Image {
        id: last
        anchors.fill: parent
        visible: img.status !== Image.Ready
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        cache: true
        sourceSize: img.sourceSize
    }
    Rectangle {
        anchors.fill: parent
        visible: img.status !== Image.Ready && last.status !== Image.Ready
        radius: a.app.theme.radius / 2
        color: a.app.theme.panelHi
        Text {
            anchors.centerIn: parent
            text: a.glyph ? a.glyph.charAt(0).toUpperCase() : ""
            color: a.app.theme.muted
            font { family: a.app.theme.font; pixelSize: Math.round(a.size * 0.45); weight: Font.Bold }
        }
    }
    Image {
        id: img
        anchors.fill: parent
        source: (a.art && a.shown) ? a.app.artUrl(a.art) + (a.retry > 0 ? "&r=" + a.retry : "") : ""
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true
        onStatusChanged: if (status === Image.Ready) last.source = source
        smooth: true
        mipmap: true
        sourceSize.width: Math.round(a.size * 2)
        sourceSize.height: Math.round(a.size * 2)
    }
}
