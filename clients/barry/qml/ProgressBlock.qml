import QtQuick

ProgressBar {
    id: p
    property var block
    width: parent ? parent.width : 0
    onPanel: false
    label: block.label || ""
    value: block.value
    max: block.max
    unit: block.unit || ""
    tone: block.tone || "neutral"
}
