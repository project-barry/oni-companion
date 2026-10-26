// A row card with title, subtitle, badge and a chevron.
import QtQuick

Tap {
    id: r
    property string title: ""
    property string subtitle: ""
    property string badge: ""
    implicitHeight: Math.max(88 * app.s, tx.implicitHeight + 28 * app.s)
    height: implicitHeight
    radius: app.theme.radius
    base: app.theme.panel
    Row {
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 26 * r.app.s }
        spacing: 16 * r.app.s
        Column {
            id: tx
            width: parent.width - ex.width - parent.spacing
            Text {
                width: parent.width
                wrapMode: Text.Wrap
                text: r.title
                color: r.app.theme.text
                font { family: r.app.theme.font; pixelSize: r.app.theme.body; weight: Font.DemiBold }
            }
            Text {
                visible: !!r.subtitle
                width: parent.width
                wrapMode: Text.Wrap
                text: r.subtitle
                color: r.app.theme.muted
                font { family: r.app.theme.font; pixelSize: r.app.theme.small }
            }
        }
        Row {
            id: ex
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14 * r.app.s
            Pill { onPanel: true; visible: !!r.badge; app: r.app; label: r.badge; filled: true }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: r.app.theme.muted
                font { family: r.app.theme.font; pixelSize: Math.round(44 * r.app.s) }
            }
        }
    }
}
