import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: app.theme.game ? 0 : 6 * app.s
    readonly property var cols: block.columns || []
    readonly property real cw: width / Math.max(1, cols.length)
    function cellText(x) { return (x !== null && typeof x === "object") ? (x.text || "") : app.fmt(x) }
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
        height: tbl.implicitHeight
        radius: c.app.theme.radius
        color: c.app.theme.panel
        clip: true
        Column {
            id: tbl
            width: parent.width
            Row {
                Repeater {
                    model: c.cols
                    delegate: Text {
                        required property var modelData
                        width: c.cw
                        height: 64 * c.app.s
                        leftPadding: 18 * c.app.s
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        text: modelData
                        color: c.app.theme.muted
                        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.Bold }
                    }
                }
            }
            Repeater {
                model: c.block.rows || []
                delegate: Item {
                    id: tr
                    required property var modelData
                    width: tbl.width
                    height: Math.max(72 * c.app.s, rowItems.implicitHeight)
                    Rectangle { width: parent.width; height: Math.max(1, c.app.s); color: c.app.theme.line }
                    Row {
                        id: rowItems
                        Repeater {
                            model: tr.modelData
                            delegate: Tap {
                                id: cell
                                required property var modelData
                                app: c.app
                                width: c.cw
                                implicitHeight: Math.max(72 * c.app.s, ct.implicitHeight + 24 * c.app.s)
                                height: tr.height
                                onTapped: if (modelData !== null && typeof modelData === "object" && modelData.ref) c.app.openRef(modelData.ref)
                                Text {
                                    id: ct
                                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 18 * c.app.s; rightMargin: 8 * c.app.s }
                                    wrapMode: Text.Wrap
                                    text: c.cellText(cell.modelData)
                                    readonly property bool isObj: cell.modelData !== null && typeof cell.modelData === "object"
                                    color: isObj && cell.modelData.ref ? c.app.theme.accent
                                           : (isObj ? c.app.theme.valueTone(cell.modelData.tone) : c.app.theme.text)
                                    font { family: c.app.theme.font; pixelSize: c.app.theme.small + 2 }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
