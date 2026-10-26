// Connect a phone (v1.4): the panel behind Settings' "Connect a phone" button. It is drawn only from the
// core's loopback pairing API (GET /connect and its POSTs and DELETE); QML holds no secret and no logic.
// Pairing happens here, on the gaming device: a phone scans the code shown on this page.
// Reads again when the core says "connect" changed (events), and after each of its own actions.
import QtQuick

Item {
    id: p
    property var app
    property var entry
    property var st: null            // the last ConnectState (GET /connect or a reply)
    property bool failed: false
    property string error: ""
    property bool busy: false        // a request is waiting for its answer
    readonly property real s: app.s
    Rectangle { anchors.fill: parent; color: app.theme.bg; z: -1 }   // opaque, so a page never shows the one before it

    function load() {
        app.get("connect", function(code, r) {
            if (code === 200 && r && r.identity) { failed = false; error = ""; st = r }
            else if (!st) { failed = true; error = app.errorText(code, r) }
        })
    }
    // A change request: on success the core sends a "connect" event, and the page reads again at once too.
    function change(path, body, done) {
        if (busy) return
        busy = true
        app.post("connect/" + path, body, function(code, r) {
            busy = false
            if (code === 200 && r) { if (done) done(r); load() }
            else app.toast(app.errorText(code, r))
        })
    }
    function removeDevice(d) {
        if (busy) return
        busy = true
        app.barry.request("DELETE", "api/v1/connect/devices/" + encodeURIComponent(d.deviceId), null, function(code, r) {
            busy = false
            if (code === 200 && r) load()
            else app.toast(app.errorText(code, r))
        })
    }
    function fmtTime(iso) {
        const d = new Date(iso)
        return isNaN(d.getTime()) ? "" : Qt.formatTime(d, "hh:mm")
    }
    function fmtSeen(iso) {
        if (!iso) return "not used yet"
        const d = new Date(iso)
        return isNaN(d.getTime()) ? "" : "last used " + Qt.formatDateTime(d, "d MMM hh:mm")
    }
    // The QR image: GET /connect/qr.png with the token (the image loader sends no headers). The code in the
    // query makes a new code load a new picture.
    function qrSource() {
        const u = app.artUrl("/api/v1/connect/qr.png")
        return (u && st && st.code) ? u + "&v=" + encodeURIComponent(st.code.display) : ""
    }
    function kindText(k) { return k === "tailscale" ? "Tailscale" : "Wi-Fi" }
    function platformText(x) {
        return ({ "android": "Android", "ios": "iPhone or iPad", "web": "Web browser" })[x] || "Other device"
    }

    Component.onCompleted: load()
    Connections {
        target: p.app
        function onChanged(names) { if (names.indexOf("connect") >= 0) p.load() }
    }

    Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: col.implicitHeight + 48 * p.s + 24 * p.s
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: col
            x: 24 * p.s
            y: 24 * p.s
            width: scroll.width - 48 * p.s
            spacing: 24 * p.s

            Text {   // the page's one-line failure (no state yet)
                visible: p.failed && p.st === null
                width: parent.width
                wrapMode: Text.Wrap
                text: p.error
                color: p.app.theme.bad
                font { family: p.app.theme.font; pixelSize: p.app.theme.body }
            }
            Text {
                visible: p.st === null && !p.failed
                text: "Loading..."
                color: p.app.theme.muted
                font { family: p.app.theme.font; pixelSize: p.app.theme.body }
            }

            ToggleRow {
                id: mainSwitch
                objectName: "connectSwitch"
                visible: p.st !== null
                app: p.app
                label: "Connect a phone"
                on: p.st ? p.st.enabled === true : false
                sub: p.st === null ? "" : (p.st.enabled
                     ? "On. Phones on this network or Tailscale can find this device and pair with it."
                     : "Off. Nothing is shared. Turn it on to pair a phone.")
                onTapped: p.change("switch", { "enabled": !p.st.enabled })
            }

            // ---- on: the name, the code, the addresses, the paired devices ----
            Column {
                visible: p.st !== null && p.st.enabled === true
                width: parent.width
                spacing: 24 * p.s

                Text {
                    objectName: "connectName"
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: p.st && p.st.identity ? p.st.identity.name : ""
                    color: p.app.theme.pageText
                    font { family: p.app.theme.headerFont; pixelSize: p.app.theme.body * 2; weight: Font.Bold }
                }
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: "Find this name in your phone's list. Tag " + (p.st && p.st.identity ? p.st.identity.fingerprintTag : "") + " tells two devices with the same name apart."
                    color: p.app.theme.muted
                    font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                }

                // The QR code: the core draws it from the pairing text (GET /connect/qr.png).
                Rectangle {
                    visible: p.st !== null && p.st.code !== null
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 360 * p.s + 32 * p.s; height: width
                    color: "white"
                    radius: 8 * p.s
                    Image {
                        objectName: "connectQr"
                        anchors.centerIn: parent
                        width: 360 * p.s; height: width
                        sourceSize.width: 360 * p.s; sourceSize.height: 360 * p.s
                        fillMode: Image.PreserveAspectFit
                        smooth: false
                        cache: false
                        source: p.qrSource()
                    }
                }

                Text {
                    objectName: "connectCode"
                    visible: p.st !== null && p.st.code !== null
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: p.st && p.st.code ? p.st.code.display : ""
                    color: p.app.theme.pageText
                    font { family: p.app.theme.headerFont; pixelSize: p.app.theme.body * 2.4; weight: Font.Bold; letterSpacing: 4 * p.s }
                }
                Text {
                    visible: p.st !== null && p.st.code !== null
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: p.st && p.st.code ? "Scan the code with the app, or type the address. Valid until " + p.fmtTime(p.st.code.expiresAt) + ". Tries left: " + p.st.code.failuresLeft + "." : ""
                    color: p.app.theme.muted
                    font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                }
                Btn {
                    objectName: "newCodeButton"
                    visible: p.st !== null && p.st.enabled === true
                    app: p.app
                    label: "New code"
                    width: parent.width
                    onTapped: p.change("code", {})
                }

                Text {
                    width: parent.width
                    text: "Addresses"
                    color: p.app.theme.title
                    font { family: p.app.theme.font; pixelSize: p.app.theme.body; weight: Font.DemiBold }
                }
                Repeater {
                    model: p.st ? p.st.addresses : []
                    Text {
                        width: parent.width
                        wrapMode: Text.WrapAnywhere
                        text: p.kindText(modelData.kind) + ": " + modelData.address
                        color: p.app.theme.pageText
                        font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                    }
                }

                Text {
                    width: parent.width
                    text: "Paired devices"
                    color: p.app.theme.title
                    font { family: p.app.theme.font; pixelSize: p.app.theme.body; weight: Font.DemiBold }
                }
                Text {
                    visible: p.st !== null && p.st.devices.length === 0
                    width: parent.width
                    text: "No phone is paired yet."
                    color: p.app.theme.muted
                    font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                }
                Repeater {
                    model: p.st ? p.st.devices : []
                    Rectangle {
                        width: parent.width
                        height: devCol.implicitHeight + 32 * p.s
                        radius: p.app.theme.radius
                        color: p.app.theme.panel
                        border.color: p.app.theme.line
                        border.width: Math.max(1, 2 * p.s)
                        Column {
                            id: devCol
                            anchors { left: parent.left; right: removeBtn.left; verticalCenter: parent.verticalCenter; leftMargin: 24 * p.s; rightMargin: 16 * p.s }
                            spacing: 4 * p.s
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: modelData.label
                                color: p.app.theme.pageText
                                font { family: p.app.theme.font; pixelSize: p.app.theme.body; weight: Font.DemiBold }
                            }
                            Text {
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: p.platformText(modelData.platform) + ", " + p.fmtSeen(modelData.lastSeen)
                                color: p.app.theme.muted
                                font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                            }
                            Text {
                                visible: modelData.transport === "http"
                                width: parent.width
                                wrapMode: Text.Wrap
                                text: "Plain HTTP: its token can be read on this Wi-Fi."
                                color: p.app.theme.warn
                                font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                            }
                        }
                        Btn {
                            id: removeBtn
                            objectName: "removeDevice-" + modelData.deviceId
                            app: p.app
                            label: "Remove"
                            anchors { right: parent.right; rightMargin: 16 * p.s; verticalCenter: parent.verticalCenter }
                            onTapped: p.removeDevice(modelData)
                        }
                    }
                }

                ToggleRow {
                    objectName: "plainHttpSwitch"
                    app: p.app
                    label: "Allow iPhone over plain HTTP"
                    sub: "Off by default. Safari cannot check this device's certificate on the local network: anyone on this Wi-Fi can read the phone's token. Tailscale is real HTTPS."
                    subColor: p.app.theme.warn
                    on: p.st ? p.st.plainHttp === true : false
                    onTapped: p.change("plain-http", { "enabled": !p.st.plainHttp })
                }
                Text {
                    visible: p.st !== null && !!p.st.plainHttpNote
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: p.st ? (p.st.plainHttpNote || "") : ""
                    color: p.app.theme.warn
                    font { family: p.app.theme.font; pixelSize: p.app.theme.small }
                }
            }

            Btn {
                objectName: "resetIdentityButton"
                visible: p.st !== null
                app: p.app
                label: "Reset identity"
                width: parent.width
                onTapped: p.app.ask("Reset identity? Every paired phone must pair again, and Connect a phone turns off.", function() {
                    p.change("reset-identity", {})
                })
            }
            Item { width: 1; height: 24 * p.s }
        }
    }
}
