// A text field with a clear button. Typing uses the Barry keyboard on the Thor.
import QtQuick

Rectangle {
    id: f
    property var app
    property alias text: input.text
    property string placeholder: ""
    property alias inputItem: input
    signal edited(string text)
    signal accepted()
    implicitHeight: 88 * app.s
    radius: app.theme.radius
    color: app.theme.panel
    border.width: Math.max(1, 2 * app.s)
    border.color: input.activeFocus ? app.theme.accent : app.theme.line
    TextInput {
        id: input
        anchors { left: parent.left; right: clear.left; verticalCenter: parent.verticalCenter; leftMargin: 28 * f.app.s }
        color: f.app.theme.text
        selectionColor: f.app.theme.accent
        clip: true
        font { family: f.app.theme.font; pixelSize: f.app.theme.body }
        inputMethodHints: Qt.ImhNoPredictiveText
        onTextEdited: f.edited(text)
        onAccepted: f.accepted()
        Text {
            visible: input.text.length === 0
            text: f.placeholder
            color: f.app.theme.muted
            font: input.font
        }
    }
    Tap {
        id: clear
        app: f.app
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        width: 88 * f.app.s
        color: "transparent"
        visible: input.text.length > 0
        onTapped: { input.text = ""; f.edited(""); input.forceActiveFocus() }
        Text {
            anchors.centerIn: parent
            text: "✕"
            color: f.app.theme.muted
            font { family: f.app.theme.font; pixelSize: f.app.theme.body }
        }
    }
    TapHandler { onTapped: input.forceActiveFocus() }
}
