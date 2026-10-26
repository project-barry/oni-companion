// A tappable rectangle: >= 72 px high where it matters (set implicitHeight).
import QtQuick

Rectangle {
    id: r
    property var app
    property alias pressed: th.pressed
    property color base: "transparent"
    property color hi: app ? app.theme.panelHi : "#222c39"
    // v1.2: a long press (about 500 ms) emits longPressed instead of tapped. Off by default, so a slow tap
    // still taps everywhere else.
    property bool longPressEnabled: false
    signal tapped()
    signal longPressed()
    color: th.pressed ? hi : base
    TapHandler {
        id: th
        longPressThreshold: r.longPressEnabled ? 0.5 : Qt.styleHints.mousePressAndHoldInterval / 1000
        onTapped: r.tapped()
        onLongPressed: if (r.longPressEnabled) r.longPressed()
    }
}
