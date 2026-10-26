// v1.3 Actions tab: a grid of equal buttons (variant "pad": overlays, tools) or the game's priority bar
// (variant "priority": 1..9 then Emergency, one row). Each card is one button: its `art` the game's icon (a plain
// label when there is none), its first action the tap. `active` highlights it (the game's current state, which the
// core re-sends on the `pad` event); `enabled:false` greys it and a tap or long press shows the `reason`.
// Rendering only: nothing here decides what is active or allowed.
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 10 * app.s
    readonly property bool bar: block.variant === "priority"
    readonly property var cards: block.cards || []
    readonly property real gap: (bar ? 8 : 14) * app.s
    readonly property int cols: bar ? Math.max(1, cards.length) : Math.max(2, Math.floor((width + gap) / (200 * app.s + gap)))
    readonly property real cellW: Math.floor((width - gap * (cols - 1)) / cols)
    property string busy: ""      // the tapped button until the game answers

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
        spacing: c.gap
        Repeater {
            model: c.cards.length   // the count: a live refresh updates the buttons in place
            delegate: Rectangle {
                id: btn
                required property int index
                readonly property var card: c.cards[index] || ({})
                readonly property var act: (card.actions && card.actions.length > 0) ? card.actions[0] : null
                readonly property bool usable: !!act && act.enabled !== false
                readonly property bool on: !!act && act.active === true
                readonly property bool working: c.busy === (act ? act.id + "|" + JSON.stringify(act.args || {}) : "")
                objectName: "pad-" + (card.title || "")
                width: c.cellW
                height: (c.bar ? 96 : (pic.visible ? 178 : 120)) * c.app.s
                radius: c.app.theme.radius
                color: on ? Qt.rgba(c.app.theme.accent.r, c.app.theme.accent.g, c.app.theme.accent.b, 0.30)
                          : th.pressed ? c.app.theme.buttonPressed : c.app.theme.buttonNormal
                border.width: Math.max(on ? 3 : 1, (on ? 3 : 2) * c.app.s)
                border.color: on ? c.app.theme.accent : working ? c.app.theme.warn : c.app.theme.line
                opacity: usable ? 1 : 0.4
                Skin { app: c.app; opacity: btn.on ? 0 : 1; name: th.pressed ? "buttonPressed" : "button" }
                Text {   // the hotkey, small in the corner (like the game's tooltips)
                    visible: !c.bar && !!btn.card.subtitle
                    anchors { right: parent.right; top: parent.top; rightMargin: 12 * c.app.s; topMargin: 8 * c.app.s }
                    text: btn.card.subtitle || ""
                    color: c.app.theme.muted
                    font { family: c.app.theme.font; pixelSize: Math.round(c.app.theme.small * 0.85) }
                }
                Column {
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 10 * c.app.s }
                    spacing: 6 * c.app.s
                    Art {
                        id: pic
                        visible: !c.bar && !!btn.card.art
                        anchors.horizontalCenter: parent.horizontalCenter
                        app: c.app
                        art: c.bar ? "" : (btn.card.art || "")
                        glyph: btn.card.title || ""
                        size: 84 * c.app.s
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: btn.card.title || ""
                        color: btn.on ? c.app.theme.title : (c.bar && btn.card.title === "!" ? c.app.theme.bad : c.app.theme.buttonText)
                        font { family: c.app.theme.font; pixelSize: c.bar ? Math.round(40 * c.app.s) : c.app.theme.small; weight: Font.DemiBold }
                    }
                }
                function press() {
                    if (!act) return
                    if (!usable) { c.app.notify(act.reason || "Not available right now."); return }
                    if (working) return
                    const key = act.id + "|" + JSON.stringify(act.args || {})
                    c.busy = key
                    const app = c.app
                    app.runAction(act, function(state, msg) {
                        if (state === "sent") return
                        // The reply can come after this grid is gone (page changed): then there is no busy flag to clear.
                        try { if (c.busy === key) c.busy = "" } catch (e) { }
                        if (state === "failed") app.toast(msg || "That did not work.")
                    })
                }
                TapHandler {
                    id: th
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: btn.press()
                    onLongPressed: if (!btn.usable && btn.act) c.app.notify(btn.act.reason || "Not available right now.")
                }
            }
        }
    }
}
