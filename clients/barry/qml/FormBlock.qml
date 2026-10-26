// A tool form. Fields: number (unit choice), element picker, choice, toggle.
// Submit sends {values:{...}} through app.submitTool; the page shows the reply.
import QtQuick

Column {
    id: f
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 22 * app.s

    // name -> value as it will be sent; texts for number fields; unit ids; element names
    property var values: ({})
    property var units: ({})
    property var badFields: ({})
    property var names: ({})
    property bool busy: false

    function setValue(name, v) { const x = values; x[name] = v; values = x }
    function setUnit(name, u) { const x = units; x[name] = u; units = x }
    function setName(name, n) { const x = names; x[name] = n; names = x }
    function submit() {
        const out = {}
        const bad = {}
        const fs = block.fields || []
        for (let i = 0; i < fs.length; i++) {
            const fd = fs[i]
            let v = values[fd.name]
            if (fd.kind === "number") {
                const n = Number(v)
                if (v === undefined || v === "" || isNaN(n)) { bad[fd.name] = true; continue }
                out[fd.name] = fd.units ? { "value": n, "unit": units[fd.name] } : n
            } else if (v !== undefined) {
                out[fd.name] = v
            }
        }
        badFields = bad
        if (Object.keys(bad).length > 0) return
        busy = true
        app.submitTool(block.tool, out, function() { f.busy = false }, block.endpoint)
    }

    Text {
        visible: !!f.block.title
        width: parent.width
        text: f.block.title || ""
        color: f.app.theme.pageText
        font { family: f.app.theme.font; pixelSize: Math.round(34 * f.app.s); weight: Font.Bold }
    }

    Repeater {
        model: f.block.fields || []
        delegate: Column {
            id: fld
            required property var modelData
            readonly property string kind: modelData.kind
            readonly property string nm: modelData.name
            width: f.width
            spacing: 8 * f.app.s
            Component.onCompleted: {
                if (kind === "number") {
                    f.setValue(nm, modelData.default !== undefined ? String(modelData.default) : "")
                    if (modelData.units) f.setUnit(nm, modelData.defaultUnit || modelData.units[0].id)
                } else if (kind === "toggle") {
                    f.setValue(nm, !!modelData.default)
                } else if (kind === "choice") {
                    f.setValue(nm, modelData.default !== undefined ? modelData.default : modelData.options[0].value)
                } else if (kind === "element" && modelData.default) {
                    f.setValue(nm, modelData.default)
                    f.app.nameOf("element", modelData.default, function(n) { f.setName(nm, n) })
                }
            }
            Text {
                text: fld.modelData.label || ""
                color: f.badFields[fld.nm] ? f.app.theme.bad : f.app.theme.muted
                font { family: f.app.theme.font; pixelSize: f.app.theme.small; weight: Font.DemiBold }
            }

            // number
            Row {
                visible: fld.kind === "number"
                width: parent.width
                spacing: 14 * f.app.s
                Rectangle {
                    width: parent.width - (units.visible ? units.width + parent.spacing : unitText.visible ? unitText.width + parent.spacing : 0)
                    height: 88 * f.app.s
                    radius: f.app.theme.radius
                    color: f.app.theme.panel
                    border.width: Math.max(1, 2 * f.app.s)
                    border.color: f.badFields[fld.nm] ? f.app.theme.bad : num.activeFocus ? f.app.theme.accent : f.app.theme.line
                    TextInput {
                        id: num
                        anchors { fill: parent; leftMargin: 26 * f.app.s; rightMargin: 26 * f.app.s }
                        verticalAlignment: TextInput.AlignVCenter
                        color: f.app.theme.text
                        selectionColor: f.app.theme.accent
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        text: f.values[fld.nm] !== undefined ? f.values[fld.nm] : ""
                        onTextEdited: f.setValue(fld.nm, text)
                        font { family: f.app.theme.font; pixelSize: f.app.theme.body }
                        onAccepted: f.submit()
                    }
                    TapHandler { onTapped: num.forceActiveFocus() }
                }
                Text {
                    id: unitText
                    visible: fld.kind === "number" && !fld.modelData.units && !!fld.modelData.unit
                    anchors.verticalCenter: parent.verticalCenter
                    text: fld.modelData.unit || ""
                    color: f.app.theme.muted
                    font { family: f.app.theme.font; pixelSize: f.app.theme.body }
                }
                Row {
                    id: units
                    visible: fld.kind === "number" && !!fld.modelData.units
                    spacing: 8 * f.app.s
                    Repeater {
                        model: fld.modelData.units || []
                        delegate: Btn {
                            required property var modelData
                            app: f.app
                            label: modelData.label
                            primary: f.units[fld.nm] === modelData.id
                            minW: 96 * f.app.s
                            onTapped: f.setUnit(fld.nm, modelData.id)
                        }
                    }
                }
            }

            // element picker
            Tap {
                id: pick
                objectName: "elementField"
                visible: fld.kind === "element"
                app: f.app
                width: parent.width
                height: 88 * f.app.s
                radius: f.app.theme.radius
                base: f.app.theme.panel
                border.width: Math.max(1, 2 * f.app.s)
                border.color: f.app.theme.line
                onTapped: f.app.pickElement(fld.modelData.filter || "any", function(id, name) {
                    f.setValue(fld.nm, id); f.setName(fld.nm, name)
                })
                Text {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 26 * f.app.s; rightMargin: 60 * f.app.s }
                    elide: Text.ElideRight
                    text: f.names[fld.nm] || f.values[fld.nm] || "Choose..."
                    color: (f.names[fld.nm] || f.values[fld.nm]) ? f.app.theme.text : f.app.theme.muted
                    font { family: f.app.theme.font; pixelSize: f.app.theme.body }
                }
                Text {
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 26 * f.app.s }
                    text: "▾"
                    color: f.app.theme.muted
                    font { family: f.app.theme.font; pixelSize: f.app.theme.body }
                }
            }

            // choice
            Flow {
                visible: fld.kind === "choice"
                width: parent.width
                spacing: 10 * f.app.s
                Repeater {
                    model: fld.modelData.options || []
                    delegate: Btn {
                        required property var modelData
                        app: f.app
                        label: modelData.label
                        primary: f.values[fld.nm] === modelData.value
                        onTapped: f.setValue(fld.nm, modelData.value)
                    }
                }
            }

            // toggle
            Tap {
                visible: fld.kind === "toggle"
                objectName: "toggle-" + fld.nm
                app: f.app
                width: parent.width
                height: 20 * f.app.s + 56 * f.app.s
                onTapped: f.setValue(fld.nm, !f.values[fld.nm])
                Rectangle {
                    id: track
                    width: 110 * f.app.s; height: 56 * f.app.s; radius: height / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: f.values[fld.nm] ? f.app.theme.accent : f.app.theme.line
                    Rectangle {
                        width: 44 * f.app.s; height: width; radius: width / 2
                        y: 6 * f.app.s
                        x: f.values[fld.nm] ? parent.width - width - 6 * f.app.s : 6 * f.app.s
                        color: "white"
                        Behavior on x { NumberAnimation { duration: 120 } }
                    }
                }
                Text {
                    anchors { left: track.right; leftMargin: 20 * f.app.s; verticalCenter: parent.verticalCenter }
                    text: f.values[fld.nm] ? "On" : "Off"
                    color: f.app.theme.pageText
                    font { family: f.app.theme.font; pixelSize: f.app.theme.body }
                }
            }
        }
    }

    Btn {
        objectName: "submitButton"
        app: f.app
        primary: true
        label: f.busy ? "Working..." : (f.block.submitLabel || "Go")
        enabledLook: !f.busy
        width: parent.width
        onTapped: if (!f.busy) f.submit()
    }
}
