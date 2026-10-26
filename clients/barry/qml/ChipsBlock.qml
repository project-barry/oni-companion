import QtQuick

Flow {
    id: f
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 12 * app.s
    Repeater {
        model: f.block.chips || []
        delegate: Item {
            id: it
            required property var modelData
            readonly property string st: modelData.style || "plain"
            implicitWidth: pill.implicitWidth
            implicitHeight: 64 * f.app.s
            width: implicitWidth
            height: implicitHeight
            Pill {
                id: pill
                app: f.app
                anchors.verticalCenter: parent.verticalCenter
                label: it.modelData.label || ""
                filled: it.st === "dlc" || it.st === "state"
                tint: it.st === "dlc" ? "#c08cf0" : it.st === "state" ? f.app.theme.accent
                      : it.st === "category" ? f.app.theme.warn : f.app.theme.muted
            }
            TapHandler { enabled: !!it.modelData.ref; onTapped: f.app.openRef(it.modelData.ref) }
        }
    }
}
