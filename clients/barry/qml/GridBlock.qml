// Cards in as many columns as fit (>= 360 px each).
import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: 10 * app.s
    readonly property int cols: Math.max(1, Math.floor((width + gap) / (380 * app.s + gap)))
    readonly property real gap: 18 * app.s
    readonly property string ft: app.filterText
    readonly property var shown: ft === "" ? (block.cards || []) : (block.cards || []).filter(function(i) { return app.titleMatches(i.title) })
    visible: ft === "" || shown.length > 0
    readonly property real cardW: (width - gap * (cols - 1)) / cols
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
            // The model is the count, so a live refresh updates the cards in place instead of rebuilding them
            // (a rebuild would recreate every portrait and flash its placeholder).
            model: c.shown.length
            delegate: Tap {
                id: card
                required property int index
                readonly property var modelData: c.shown[index] || ({})
                app: c.app
                width: c.cardW
                height: body.implicitHeight + 36 * c.app.s
                radius: c.app.theme.radius
                base: c.app.theme.panel
                objectName: "card-" + (modelData.title || "")
                // v1.2: longPress actions (Dismiss) appear after a long press on the card.
                readonly property var holdActs: (modelData.actions || []).filter(function(a) { return a.trigger === "longPress" })
                readonly property string revealId: modelData.ref ? "ref:" + modelData.ref.kind + ":" + modelData.ref.id : "card:" + (modelData.title || "")
                longPressEnabled: holdActs.length > 0
                onLongPressed: c.app.reveal(revealId)
                onTapped: if (modelData.ref) c.app.openRef(modelData.ref)
                Skin { app: c.app; name: "panel" }
                Rectangle {
                    width: 8 * c.app.s; height: parent.height - 2 * card.radius
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    color: c.app.theme.tone(card.modelData.tone)
                    visible: !!card.modelData.tone && card.modelData.tone !== "neutral"
                }
                Column {
                    id: body
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 * c.app.s; topMargin: 18 * c.app.s }
                    spacing: 10 * c.app.s
                    Row {
                        width: parent.width
                        spacing: 16 * c.app.s
                        Art {
                            id: pic
                            app: c.app
                            art: card.modelData.art || (card.modelData.ref ? (card.modelData.ref.art || "") : "")
                            glyph: card.modelData.title || ""
                            size: 112 * c.app.s
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - pic.width - (pic.width > 0 ? parent.spacing : 0) - (bdg.visible ? bdg.width + parent.spacing : 0)
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: card.modelData.title || ""
                                color: c.app.theme.text   // the card is a panel: text/panel is the pair the core checks
                                font { family: c.app.theme.font; pixelSize: Math.round(34 * c.app.s); weight: Font.Bold }
                            }
                            Text {
                                visible: !!card.modelData.subtitle
                                width: parent.width
                                elide: Text.ElideRight
                                text: card.modelData.subtitle || ""
                                color: c.app.theme.muted
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                            }
                        }
                        Pill {
                                onPanel: true
                            id: bdg
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !!card.modelData.badge
                            app: c.app
                            label: card.modelData.badge || ""
                            filled: true
                            tint: c.app.theme.tone(card.modelData.tone)
                        }
                    }
                    Flow {
                        visible: (card.modelData.badges || []).length > 0
                        width: parent.width
                        spacing: 8 * c.app.s
                        Repeater {
                            model: card.modelData.badges || []
                            delegate: Pill {
                                onPanel: true
                                required property var modelData
                                app: c.app
                                label: modelData.label
                                filled: true
                                tint: c.app.theme.level(modelData.level)
                            }
                        }
                    }
                    Repeater {
                        model: card.modelData.meters || []
                        delegate: ProgressBar {
                            required property var modelData
                            app: c.app
                            width: body.width
                            label: modelData.label || ""
                            value: modelData.value
                            max: modelData.max
                            unit: modelData.unit || ""
                            tone: modelData.tone || "neutral"
                        }
                    }
                    Repeater {
                        model: card.modelData.stats || []
                        delegate: Row {
                            required property var modelData
                            width: body.width
                            spacing: 14 * c.app.s
                            Text {
                                id: lab
                                width: Math.min(implicitWidth, parent.width * 0.4)
                                elide: Text.ElideRight
                                text: parent.modelData.label || ""
                                color: c.app.theme.muted
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                            }
                            Text {
                                // Long values (traits, skills) wrap onto more lines instead of being cut off.
                                width: parent.width - lab.width - parent.spacing
                                wrapMode: Text.Wrap
                                horizontalAlignment: Text.AlignRight
                                text: c.app.fmt(parent.modelData.value) + (parent.modelData.unit ? " " + parent.modelData.unit : "")
                                color: c.app.theme.valueTone(parent.modelData.tone)
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold }
                            }
                        }
                    }
                    Row {
                        visible: (card.modelData.actions || []).length > 0
                        spacing: 12 * c.app.s
                        Repeater {
                            model: (card.modelData.actions || []).filter(function(a) { return a.trigger !== "longPress" })
                            delegate: ActionBtn { required property var modelData; app: c.app; action: modelData }
                        }
                        Repeater {
                            model: c.app.revealKey === card.revealId ? card.holdActs : []
                            delegate: ActionBtn { required property var modelData; app: c.app; action: modelData }
                        }
                    }
                }
            }
        }
    }
}
