import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: app.theme.game ? 0 : 6 * app.s
    SectionBar { app: c.app; text: c.block.title || ""; visible: !!c.block.title && c.app.theme.game }
    Text {
        visible: !!c.block.title && !c.app.theme.game
        width: parent.width
        text: c.block.title || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
    }
    Rectangle {
        width: parent.width
        height: rows.implicitHeight
        radius: c.app.theme.radius
        color: c.app.theme.panel
        clip: true
        Column {
            id: rows
            width: parent.width
            Repeater {
                model: c.block.rows || []
                delegate: Tap {
                    id: row
                    required property var modelData
                    required property int index
                    app: c.app
                    width: rows.width
                    implicitHeight: Math.max(72 * c.app.s, inner.implicitHeight + 28 * c.app.s)
                    height: implicitHeight
                    onTapped: if (modelData.ref) c.app.openRef(modelData.ref)
                    Rectangle {
                        visible: row.index > 0
                        width: parent.width; height: Math.max(1, c.app.s)
                        color: c.app.theme.line
                    }
                    Row {
                        id: inner
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 26 * c.app.s }
                        spacing: 20 * c.app.s
                        Column {
                            width: parent.width - val.width - parent.spacing
                            Text {
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: row.modelData.label || ""
                                color: c.app.theme.text
                                font { family: c.app.theme.font; pixelSize: c.app.theme.body }
                            }
                            Text {
                                visible: !!row.modelData.hint
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: row.modelData.hint || ""
                                color: c.app.theme.muted
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                            }
                        }
                        Text {
                            id: val
                            anchors.top: parent.top
                            horizontalAlignment: Text.AlignRight
                            text: c.app.fmt(row.modelData.value) + (row.modelData.unit ? " " + row.modelData.unit : "")
                            color: row.modelData.ref ? c.app.theme.accent : c.app.theme.valueTone(row.modelData.tone)
                            font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: Font.DemiBold }
                        }
                    }
                }
            }
        }
    }
}
