import QtQuick

Column {
    id: c
    property var app
    property var block
    width: parent ? parent.width : 0
    spacing: app.theme.game ? 0 : 6 * app.s
    readonly property string ft: app.filterText
    readonly property var shown: ft === "" ? (block.items || []) : (block.items || []).filter(function(i) { return app.titleMatches(i.title) })
    visible: ft === "" || shown.length > 0
    // The colony alert list is drawn like the game's: a translucent panel, white bullets, the count in brackets.
    readonly property bool alertStyle: !!app.theme.game && block.variant === "alerts"
    SectionBar { app: c.app; text: c.block.title || ""; visible: !!c.block.title && c.app.theme.game }
    Text {
        visible: !!c.block.title && !c.app.theme.game
        width: parent.width
        text: c.block.title || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.small; weight: Font.DemiBold; capitalization: Font.AllUppercase }
    }
    Text {
        visible: c.shown.length === 0 && c.ft === ""
        width: parent.width
        text: c.block.empty || ""
        color: c.app.theme.muted
        font { family: c.app.theme.font; pixelSize: c.app.theme.body }
    }
    Rectangle {
        visible: c.shown.length > 0
        width: parent.width
        height: col.implicitHeight
        radius: c.app.theme.radius
        color: c.alertStyle ? c.app.theme.alertBg : c.app.theme.panel
        clip: true
        Skin { app: c.app; name: c.alertStyle ? "" : "panel" }
        Column {
            id: col
            width: parent.width
            Repeater {
                model: c.shown.length   // the count: a live refresh updates rows in place (no rebuild, no art flash)
                delegate: Tap {
                    id: row
                    required property int index
                    readonly property var modelData: c.shown[index] || ({})
                    readonly property var acts: (modelData.actions || []).filter(function(a) { return a.trigger !== "longPress" })
                    // v1.2: actions with trigger longPress (Dismiss) show only after a long press on the row.
                    readonly property var holdActs: (modelData.actions || []).filter(function(a) { return a.trigger === "longPress" })
                    readonly property bool alertRef: !!modelData.ref && modelData.ref.kind === "alert"
                    readonly property string revealId: modelData.ref ? "ref:" + modelData.ref.kind + ":" + modelData.ref.id : "row:" + (modelData.title || "")
                    readonly property bool revealed: c.app.revealKey === revealId
                    longPressEnabled: holdActs.length > 0 || alertRef
                    objectName: alertRef ? "alert-" + modelData.ref.id : ""
                    onLongPressed: c.app.reveal(revealId)
                    readonly property color alertColor: modelData.tone === "bad" ? c.app.theme.alertBadText : c.app.theme.alertText
                    app: c.app
                    width: col.width
                    implicitHeight: Math.max((c.alertStyle ? 60 : 88) * c.app.s, tx.implicitHeight + (c.alertStyle ? 18 : 28) * c.app.s, pic.height + 24 * c.app.s)
                    height: implicitHeight
                    onTapped: if (modelData.ref) c.app.openRef(modelData.ref)
                    Rectangle {
                        visible: row.index > 0 && !c.alertStyle
                        width: parent.width; height: Math.max(1, c.app.s)
                        color: c.app.theme.line
                    }
                    Rectangle {
                        visible: !!row.modelData.tone && row.modelData.tone !== "neutral" && !c.alertStyle
                        width: 8 * c.app.s; height: parent.height
                        color: c.app.theme.tone(row.modelData.tone)
                    }
                    Row {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 26 * c.app.s }
                        spacing: 16 * c.app.s
                        Text {
                            id: bullet
                            visible: c.alertStyle && pic.width === 0     // the game: a white dot, or the alert's own icon
                            width: visible ? implicitWidth : 0
                            anchors.top: parent.top
                            text: "•"
                            color: row.alertColor
                            font { family: c.app.theme.font; pixelSize: c.app.theme.body }
                        }
                        Art {
                            id: pic
                            app: c.app
                            art: row.modelData.art || (row.modelData.ref ? (row.modelData.ref.art || "") : "")
                            glyph: row.modelData.title || ""
                            size: c.alertStyle ? Math.round(c.app.theme.body * 1.1) : 64 * c.app.s   // the game draws alert icons at text height
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Column {
                            id: tx
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - extra.width - pic.width - bullet.width - parent.spacing * (pic.width > 0 ? 2 : 1) - (bullet.width > 0 ? parent.spacing : 0)
                            Text {
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: (row.modelData.title || "") + (c.alertStyle && row.modelData.badge && !/\(\d+\)\s*$/.test(row.modelData.title || "") ? " (" + String(row.modelData.badge).replace(/^x/, "") + ")" : "")
                                color: c.alertStyle ? row.alertColor : c.app.theme.text
                                font { family: c.app.theme.font; pixelSize: c.app.theme.body; weight: c.alertStyle ? Font.Normal : Font.DemiBold }
                            }
                            Text {
                                visible: !!row.modelData.subtitle
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: row.modelData.subtitle || ""
                                color: c.alertStyle ? row.alertColor : c.app.theme.muted
                                opacity: c.alertStyle ? 0.75 : 1
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small }
                            }
                            Row {   // revealed by a long press
                                visible: row.revealed && row.holdActs.length > 0
                                topPadding: 8 * c.app.s
                                bottomPadding: 6 * c.app.s
                                spacing: 12 * c.app.s
                                Repeater {
                                    model: row.holdActs
                                    delegate: ActionBtn { required property var modelData; app: c.app; action: modelData }
                                }
                            }
                            Text {
                                visible: row.revealed && row.holdActs.length === 0 && row.alertRef
                                objectName: "notDismissable"
                                width: parent.width
                                wrapMode: Text.Wrap
                                topPadding: 6 * c.app.s
                                text: "This alert can't be dismissed in the game"
                                color: row.alertColor
                                opacity: 0.85
                                font { family: c.app.theme.font; pixelSize: c.app.theme.small; italic: true }
                            }
                        }
                        Row {
                            id: extra
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 14 * c.app.s
                            Pill {
                                onPanel: true
                                visible: !!row.modelData.badge && !c.alertStyle
                                app: c.app
                                label: row.modelData.badge || ""
                                filled: true
                                tint: row.modelData.tone ? c.app.theme.tone(row.modelData.tone) : c.app.theme.muted
                            }
                            Repeater {
                                model: row.acts
                                delegate: ActionBtn {
                                    required property var modelData
                                    app: c.app
                                    action: modelData
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            Text {
                                visible: !!row.modelData.ref
                                anchors.verticalCenter: parent.verticalCenter
                                text: "›"
                                color: c.app.theme.muted
                                font { family: c.app.theme.font; pixelSize: Math.round(44 * c.app.s) }
                            }
                        }
                    }
                }
            }
        }
    }
}
