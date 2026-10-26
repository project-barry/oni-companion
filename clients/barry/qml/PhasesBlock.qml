// Element ladder, coldest at the top.
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 10 * app.s
    SectionBar { app: c.app; text: c.block.title || ""; visible: !!c.block.title && c.app.theme.game }
    Text {
        visible: !!c.block.title && !c.app.theme.game
        width: parent.width
        text: c.block.title || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
    }
    Column {
        width: parent.width
        spacing: 6 * c.app.s
        Repeater {
            model: c.block.states || []
            delegate: Tap {
                id: ph
                required property var modelData
                app: c.app
                width: parent.width
                implicitHeight: Math.max(88 * c.app.s, tx.implicitHeight + 28 * c.app.s)
                height: implicitHeight
                radius: c.app.theme.radius
                base: c.app.theme.panel
                clip: true
                onTapped: if (modelData.target) c.app.openRef(modelData.target)
                Rectangle {
                    width: 22 * c.app.s; height: parent.height
                    color: c.app.theme.stateColor(ph.modelData.state)
                }
                Row {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 52 * c.app.s; rightMargin: 24 * c.app.s }
                    spacing: 16 * c.app.s
                    Column {
                        id: tx
                        width: parent.width - tgt.width - parent.spacing
                        Text {
                            width: parent.width
                            wrapMode: Text.Wrap
                            text: ph.modelData.label || ""
                            color: c.app.theme.text
                            font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: Font.DemiBold }
                        }
                        Text {
                            visible: !!ph.modelData.range
                            width: parent.width
                            text: ph.modelData.range || ""
                            color: c.app.theme.muted
                            font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                        }
                    }
                    Text {
                        id: tgt
                        visible: !!ph.modelData.target
                        anchors.verticalCenter: parent.verticalCenter
                        text: ph.modelData.target ? "→ " + ph.modelData.target.id : ""
                        color: c.app.theme.accent
                        font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                    }
                }
            }
        }
    }
}
