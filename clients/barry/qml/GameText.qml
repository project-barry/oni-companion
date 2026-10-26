// Header text drawn from the game's Graystroke SDF atlas (TextMeshPro), one small ShaderEffect per glyph.
// A character the atlas has no glyph for is drawn with the fallback font (Economica Bold, else the body font),
// run by run, so a missing glyph never breaks the line. Single line. Use HeaderText unless you need only this.
import QtQuick

Item {
    id: g
    property var app
    property string text: ""
    property color color: "white"
    property real pixelSize: 30
    property real letterSpacing: 0
    readonly property var at: app && app.fonts ? app.fonts.atlas : null
    readonly property bool ready: !!at && app.fonts.atlasReady
    readonly property real k: at ? pixelSize / at.pointSize : 1
    readonly property var runs: ready ? layoutRuns(text, at, k, letterSpacing) : []
    readonly property real naturalWidth: {
        let w = 0
        for (const r of runs) w += r.atlas ? r.width : fbMeasure(r.text)
        return w
    }
    implicitWidth: row.width
    implicitHeight: at ? Math.ceil((at.ascent - at.descent) * k) : Math.ceil(pixelSize * 1.2)

    // Measures fallback text with the same font the Text delegates use.
    TextMetrics { id: tm; font { family: g.app ? g.app.theme.headerFont : ""; pixelSize: Math.round(g.pixelSize); weight: Font.Bold } }
    function fbMeasure(t) { tm.text = t; return tm.advanceWidth }

    // Splits the text into runs: atlas runs carry positioned glyph quads, fallback runs the characters to draw as text.
    function layoutRuns(txt, a, kk, ls) {
        const out = []
        let cur = null
        let prev = -1
        const base = a.ascent * kk
        const cps = Array.from(txt)
        for (const ch of cps) {
            const cp = ch.codePointAt(0)
            const gl = a.glyphs[cp]
            if (!gl) {
                if (!cur || cur.atlas) { cur = { atlas: false, text: "" }; out.push(cur) }
                cur.text += ch
                prev = -1
                continue
            }
            if (!cur || !cur.atlas) { cur = { atlas: true, glyphs: [], width: 0 }; out.push(cur); prev = -1 }
            if (prev >= 0) {
                const kern = a.kerning[prev * 1048576 + cp]
                if (kern) cur.width += kern * kk
            }
            if (gl.w > 0 && gl.h > 0) {
                const pad = a.pad
                cur.glyphs.push({
                    x: cur.width + (gl.bearingX - pad) * kk, y: base - (gl.bearingY + pad) * kk,
                    w: (gl.w + 2 * pad) * kk, h: (gl.h + 2 * pad) * kk,
                    u: (gl.x - pad) / a.w, v: (gl.y - pad) / a.h, uw: (gl.w + 2 * pad) / a.w, uh: (gl.h + 2 * pad) / a.h
                })
            }
            cur.width += gl.advance * kk + ls
            prev = cp
        }
        return out
    }

    Row {
        id: row
        height: g.implicitHeight
        Repeater {
            model: g.runs
            delegate: Item {
                id: run
                required property var modelData
                height: g.implicitHeight
                width: modelData.atlas ? modelData.width : fb.implicitWidth
                Repeater {
                    model: run.modelData.atlas ? run.modelData.glyphs : []
                    delegate: ShaderEffect {
                        id: q
                        required property var modelData
                        x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
                        property variant src: g.app.fonts.atlasImage
                        property vector4d uvRect: Qt.vector4d(modelData.u, modelData.v, modelData.uw, modelData.uh)
                        property color color: g.color
                        property vector4d chan: g.at.chan === 1 ? Qt.vector4d(1, 0, 0, 0) : Qt.vector4d(0, 0, 0, 1)
                        property real spread: g.at.spread
                        property real sdfScale: g.k * Screen.devicePixelRatio
                        vertexShader: Qt.resolvedUrl("sdf.vert.qsb")
                        fragmentShader: Qt.resolvedUrl("sdf.frag.qsb")
                    }
                }
                Text {
                    id: fb
                    visible: !run.modelData.atlas
                    text: run.modelData.atlas ? "" : run.modelData.text
                    color: g.color
                    anchors.verticalCenter: parent.verticalCenter
                    font { family: g.app.theme.headerFont; pixelSize: Math.round(g.pixelSize); weight: Font.Bold; letterSpacing: g.letterSpacing }
                }
            }
        }
    }
}
