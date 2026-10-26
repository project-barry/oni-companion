// Header (title, subtitle, source) and the blocks of one Screen, in a Flickable.
import QtQuick

Flickable {
    id: fl
    property var app
    property var screen: null
    property string message: ""      // shown instead of blocks (loading / error)
    property bool canRetry: false
    property Item extraTop: null
    property bool bottomBar: false     // leave room for the page's own buttons
    signal retry()
    signal worldPicked(int id)

    contentWidth: width
    contentHeight: col.implicitHeight + 120 * app.s + (bottomBar ? 144 * app.s : 0)
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    // keep the reading position when a live update swaps the content
    function setScreen(sc) {
        const y = contentY
        screen = sc
        Qt.callLater(function() { contentY = Math.min(y, Math.max(0, contentHeight - height)) })
    }

    Column {
        id: col
        x: Math.max(32 * fl.app.s, (fl.width - 1160 * fl.app.s) / 2)
        y: 24 * fl.app.s
        width: Math.min(fl.width - 64 * fl.app.s, 1160 * fl.app.s)
        spacing: 24 * fl.app.s

        Column {
            visible: !!fl.screen
            width: parent.width
            spacing: 4 * fl.app.s
            Text {
                width: parent.width
                wrapMode: Text.Wrap
                text: fl.screen ? fl.screen.title : ""
                color: fl.app.theme.title
                font { family: fl.app.theme.font; pixelSize: Math.round(52 * fl.app.s); weight: Font.Bold }
            }
            Text {
                visible: !!(fl.screen && fl.screen.subtitle)
                width: parent.width
                wrapMode: Text.Wrap
                text: fl.screen ? (fl.screen.subtitle || "") : ""
                color: fl.app.theme.muted
                font { family: fl.app.theme.font; pixelSize: fl.app.theme.body }
            }
            Text {
                visible: !!(fl.screen && fl.screen.source)
                width: parent.width
                text: fl.screen ? fl.app.sourceLine(fl.screen.source, fl.screen.asOf) : ""
                color: fl.app.theme.accent
                font { family: fl.app.theme.font; pixelSize: fl.app.theme.small }
            }
        }

        Flow {   // world switcher (v1.1): choosing one re-fetches the same page with ?world=
            visible: !!(fl.screen && fl.screen.worldSwitcher)
            width: parent.width
            spacing: 12 * fl.app.s
            Repeater {
                model: fl.screen && fl.screen.worldSwitcher ? fl.screen.worldSwitcher.worlds : []
                delegate: Tap {
                    id: wp
                    required property var modelData
                    readonly property bool on: fl.screen.worldSwitcher.active === modelData.id
                    app: fl.app
                    objectName: "world" + modelData.id
                    implicitWidth: wt.implicitWidth + 48 * fl.app.s
                    width: implicitWidth
                    height: 72 * fl.app.s
                    radius: height / 2
                    base: on ? Qt.rgba(fl.app.theme.accent.r, fl.app.theme.accent.g, fl.app.theme.accent.b, 0.25) : fl.app.theme.buttonNormal
                    border.width: Math.max(1, 2 * fl.app.s)
                    border.color: on ? fl.app.theme.accent : fl.app.theme.line
                    onTapped: if (!on) fl.worldPicked(modelData.id)
                    Text {
                        id: wt
                        anchors.centerIn: parent
                        text: wp.modelData.name
                        color: wp.on ? fl.app.theme.title : fl.app.theme.muted
                        font { family: fl.app.theme.font; pixelSize: fl.app.theme.small + 2; weight: Font.DemiBold }
                    }
                }
            }
        }
        SearchField {   // filter (v1.1): hides rows and cards whose title does not contain the text
            visible: !!(fl.screen && fl.screen.filter)
            objectName: "filterField"
            app: fl.app
            width: parent.width
            placeholder: fl.screen && fl.screen.filter ? fl.screen.filter.placeholder : ""
            text: fl.app.filterText
            onEdited: (t) => fl.app.filterText = t.trim().toLowerCase()
        }

        Text {
            visible: !!fl.message
            width: parent.width
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            topPadding: 60 * fl.app.s
            text: fl.message
            color: fl.app.theme.muted
            font { family: fl.app.theme.font; pixelSize: fl.app.theme.body }
        }
        Btn {
            visible: fl.canRetry
            app: fl.app
            label: "Try again"
            primary: true
            anchors.horizontalCenter: parent.horizontalCenter
            onTapped: fl.retry()
        }

        BlockView {
            id: bv
            visible: !!fl.screen
            app: fl.app
            width: parent.width
            blocks: fl.screen ? (fl.screen.blocks || []) : []
        }
    }
}
