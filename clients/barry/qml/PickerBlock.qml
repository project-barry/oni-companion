// v1.3 material choice of a building, like the game's build menu: per material slot the candidates (art, name,
// amount needed, amount the colony has), a greyed one is not selectable, then one Build button. The block holds no
// state: this item keeps the user's choice (starting from the core's `selected`) and sends the chosen ids as
// `materials`, one per slot in slot order, with the block's action.
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 10 * app.s
    property var userChoice: ({})        // slot index -> option id the user tapped
    readonly property var slots: block.slots || []

    function optionsOf(i) { return (slots[i] && slots[i].options) || [] }
    // The tapped option while it is still offered and enabled; otherwise the core's pre-selection.
    function chosenId(i) {
        const opts = optionsOf(i)
        const u = userChoice[i]
        if (u !== undefined) for (const o of opts) if (o.id === u && o.enabled) return u
        for (const o of opts) if (o.selected) return o.id
        return opts.length > 0 ? opts[0].id : ""
    }
    function chosenOption(i) {
        for (const o of optionsOf(i)) if (o.id === chosenId(i)) return o
        return null
    }
    function pick(i, o) {
        const x = Object.assign({}, userChoice); x[i] = o.id; userChoice = x
    }
    // One chosen id per slot, and a slot whose choice is greyed (or has none) blocks the button.
    readonly property var materials: { const m = []; for (let i = 0; i < slots.length; i++) m.push(chosenId(i)); return m }
    readonly property string blocker: {
        for (let i = 0; i < slots.length; i++) {
            const o = chosenOption(i)
            if (!o) return slots[i].empty || ("No " + slots[i].label + " to build with yet.")
            if (!o.enabled) return "Not enough " + o.name + "."
        }
        return ""
    }
    readonly property var buildAction: {
        const a = Object.assign({}, block.action || ({}))
        a.args = Object.assign({}, a.args || ({}), { "materials": materials })
        if (a.enabled !== false && blocker !== "") { a.enabled = false; a.reason = blocker }
        return a
    }
    function kg(v) {
        const n = Number(v)
        const r = n >= 100 ? Math.round(n) : Math.round(n * 10) / 10
        return r.toLocaleString(Qt.locale("en_US"), "f", r % 1 === 0 ? 0 : 1) + " kg"
    }

    SectionBar { app: c.app; text: c.block.title || ""; visible: !!c.block.title && c.app.theme.game }
    Text {
        visible: !!c.block.title && !c.app.theme.game
        width: parent.width
        text: c.block.title || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
    }
    Repeater {
        model: c.slots.length
        delegate: Column {
            id: slot
            required property int index
            readonly property var sl: c.slots[index] || ({})
            width: c.width
            spacing: 6 * c.app.s
            Text {
                width: parent.width
                text: (slot.sl.label || "") + "  -  " + c.kg(slot.sl.needKg)
                color: c.app.theme.pageText
                font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: Font.DemiBold }
            }
            Text {
                visible: (slot.sl.options || []).length === 0
                width: parent.width
                wrapMode: Text.Wrap
                text: slot.sl.empty || "Nothing to choose from yet."
                color: c.app.theme.muted
                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
            }
            Repeater {
                model: (slot.sl.options || []).length
                delegate: Tap {
                    id: row
                    required property int index
                    readonly property var o: (slot.sl.options || [])[index] || ({})
                    readonly property bool on: o.id === c.chosenId(slot.index)
                    app: c.app
                    objectName: "pick-" + slot.index + "-" + (o.id || "")
                    width: slot.width
                    height: 100 * c.app.s
                    radius: c.app.theme.radius
                    base: on ? Qt.rgba(c.app.theme.accent.r, c.app.theme.accent.g, c.app.theme.accent.b, 0.25) : c.app.theme.panel
                    border.width: Math.max(on ? 3 : 1, (on ? 3 : 2) * c.app.s)
                    border.color: on ? c.app.theme.accent : c.app.theme.line
                    onTapped: {
                        if (o.enabled) c.pick(slot.index, o)
                        else c.app.notify("Not enough " + o.name + ": you have " + c.kg(o.haveKg) + ", it needs " + c.kg(o.needKg) + ".")
                    }
                    Skin { app: c.app; opacity: row.on ? 0 : 1; name: "panel" }
                    Row {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 20 * c.app.s }
                        spacing: 16 * c.app.s
                        opacity: row.o.enabled ? 1 : 0.4
                        Rectangle {   // the choice mark
                            anchors.verticalCenter: parent.verticalCenter
                            width: 30 * c.app.s; height: width; radius: width / 2
                            color: row.on ? c.app.theme.accent : "transparent"
                            border.width: Math.max(2, 3 * c.app.s)
                            border.color: row.on ? c.app.theme.accent : c.app.theme.muted
                        }
                        Art {
                            id: pic
                            anchors.verticalCenter: parent.verticalCenter
                            app: c.app
                            art: row.o.art || (row.o.ref ? (row.o.ref.art || "") : "")
                            glyph: row.o.name || ""
                            size: 68 * c.app.s
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 30 * c.app.s - pic.width - amounts.width - parent.spacing * (pic.width > 0 ? 3 : 2)
                            elide: Text.ElideRight
                            text: row.o.name || ""
                            color: c.app.theme.text
                            font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: row.on ? Font.Bold : Font.DemiBold }
                        }
                        Column {
                            id: amounts
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                anchors.right: parent.right
                                text: "Needs " + c.kg(row.o.needKg)
                                color: c.app.theme.muted
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                            }
                            Text {
                                anchors.right: parent.right
                                text: "Have " + c.kg(row.o.haveKg)
                                color: row.o.enabled ? c.app.theme.text : c.app.theme.bad
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold }
                            }
                        }
                    }
                }
            }
        }
    }
    ActionBtn {
        objectName: "pickerBuild"
        app: c.app
        action: c.buildAction
        width: parent.width
    }
}
