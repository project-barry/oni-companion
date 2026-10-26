// A button with a label.
import QtQuick

Tap {
    id: b
    property string label: ""
    property bool primary: false
    property bool enabledLook: true
    property real minW: 0
    readonly property real s: app.s
    implicitWidth: Math.max(minW, lbl.implicitWidth + 56 * s)
    implicitHeight: 80 * s
    radius: app.theme.radius
    base: primary ? app.theme.accent : app.theme.buttonNormal
    hi: primary ? Qt.lighter(app.theme.accent, 1.25) : app.theme.buttonPressed
    border.width: primary ? 0 : Math.max(1, 2 * s)
    border.color: app.theme.line
    opacity: enabledLook ? 1 : 0.4
    Skin { app: b.app; opacity: b.primary ? 0 : 1; name: b.pressed ? "buttonPressed" : "button" }
    Text {
        id: lbl
        anchors.centerIn: parent
        text: b.label
        color: b.primary ? "#06121f" : b.app.theme.buttonText
        font { family: b.app.theme.font; pixelSize: b.app.theme.body; weight: Font.DemiBold }
    }
}
