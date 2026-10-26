// Renders a list of blocks, top to bottom. One file per block type; a type
// this app does not know becomes an "update the app" notice.
// Blocks load by file name (Loader), so Group can hold a BlockView.
import QtQuick

Column {
    id: v
    property var app
    property var blocks: []
    spacing: app.theme.gap * 1.2

    readonly property var files: ({
        "heading": "HeadingBlock.qml", "text": "TextBlock.qml", "stats": "StatsBlock.qml",
        "chips": "ChipsBlock.qml", "list": "ListBlock.qml", "grid": "GridBlock.qml",
        "ports": "PortsBlock.qml", "phases": "PhasesBlock.qml", "progress": "ProgressBlock.qml",
        "table": "TableBlock.qml", "notice": "NoticeBlock.qml", "form": "FormBlock.qml",
        "link": "LinkBlock.qml", "divider": "DividerBlock.qml", "group": "GroupBlock.qml",
        "image": "ImageBlock.qml", "picker": "PickerBlock.qml"
    })

    // The model is the count and a block's data is handed to its item in place: a live refresh with the
    // same block types keeps every item (and its images) instead of rebuilding the page.
    Repeater {
        model: v.blocks.length
        delegate: Loader {
            id: ld
            required property int index
            readonly property var blk: v.blocks[index] || ({})
            readonly property string kind: blk.type || ""
            width: v.width
            function load() {
                const pad = kind === "grid" && (blk.variant === "pad" || blk.variant === "priority")
                const f = pad ? "PadGrid.qml" : v.files[kind]
                setSource(f ? f : "UnknownBlock.qml", { "app": v.app, "block": blk })
            }
            onKindChanged: load()
            onBlkChanged: if (item && item.block !== undefined && status === Loader.Ready) item.block = blk
            Component.onCompleted: load()
        }
    }
}
