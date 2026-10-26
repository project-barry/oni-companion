// Inputs and outputs of a building, side by side when wide.
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 10 * app.s
    readonly property bool wide: width > 900 * app.s
    readonly property real colW: wide ? (width - 18 * app.s) / 2 : width
    SectionBar { app: c.app; text: c.block.title || ""; visible: !!c.block.title && c.app.theme.game }
    Text {
        visible: !!c.block.title && !c.app.theme.game
        width: parent.width
        text: c.block.title || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
    }
    Flow {
        width: parent.width
        spacing: 18 * c.app.s
        Repeater {
            model: [ { "head": "Inputs", "list": c.block.inputs || [] },
                     { "head": "Outputs", "list": c.block.outputs || [] } ]
            delegate: Rectangle {
                id: box
                required property var modelData
                width: c.colW
                height: col.implicitHeight + 28 * c.app.s
                radius: c.app.theme.radius
                color: c.app.theme.panel
                Column {
                    id: col
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 * c.app.s; topMargin: 16 * c.app.s }
                    spacing: 4 * c.app.s
                    Text {
                        text: box.modelData.head
                        color: c.app.theme.muted
                        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.Bold }
                    }
                    Text {
                        visible: box.modelData.list.length === 0
                        text: "None"
                        color: c.app.theme.muted
                        font { family: c.app.theme.font; pixelSize: c.app.theme.body }
                    }
                    Repeater {
                        model: box.modelData.list
                        delegate: Tap {
                            id: prow
                            required property var modelData
                            app: c.app
                            width: col.width
                            implicitHeight: Math.max(72 * c.app.s, info.implicitHeight + 16 * c.app.s)
                            height: implicitHeight
                            onTapped: if (modelData.element) c.app.openRef(modelData.element)
                            Row {
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                                spacing: 14 * c.app.s
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: !!prow.modelData.conduit && prow.modelData.conduit !== "none"
                                    width: 14 * c.app.s; height: 14 * c.app.s; radius: width / 2
                                    color: c.app.conduitColor(prow.modelData.conduit)
                                }
                                Column {
                                    id: info
                                    width: parent.width - rate.implicitWidth - parent.spacing * 2 - 14 * c.app.s
                                    Text {
                                        width: parent.width
                                        wrapMode: Text.Wrap
                                        text: prow.modelData.label || ""
                                        color: prow.modelData.element ? c.app.theme.accent : c.app.theme.text
                                        font { family: c.app.theme.font; pixelSize: c.app.theme.body }
                                    }
                                    Text {
                                        visible: !!prow.modelData.note || (!!prow.modelData.conduit && prow.modelData.conduit !== "none")
                                        width: parent.width
                                        wrapMode: Text.Wrap
                                        text: (prow.modelData.conduit && prow.modelData.conduit !== "none" ? prow.modelData.conduit : "")
                                              + (prow.modelData.note ? (prow.modelData.conduit && prow.modelData.conduit !== "none" ? " - " : "") + prow.modelData.note : "")
                                        color: c.app.theme.muted
                                        font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                                    }
                                }
                                Text {
                                    id: rate
                                    visible: prow.modelData.rate !== undefined
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: c.app.fmt(prow.modelData.rate) + (prow.modelData.unit ? " " + prow.modelData.unit : "")
                                    color: c.app.theme.text
                                    font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: Font.DemiBold }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
