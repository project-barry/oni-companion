// Plain fallback icons for the speed bar when the theme has no game sprite:
// pause (two bars), play (one triangle), 1 / 2 / 3 (that many triangles, like the game's chevrons).
import QtQuick

Canvas {
    id: g
    property string kind: "play"        // pause | play | speed1 | speed2 | speed3
    property color tint: "white"
    property real size: 40
    width: kind === "speed2" ? size * 1.25 : kind === "speed3" ? size * 1.6 : size
    height: size
    onKindChanged: requestPaint()
    onTintChanged: requestPaint()
    onWidthChanged: requestPaint()
    onPaint: {
        const c = getContext("2d")
        c.reset()
        c.fillStyle = tint
        const h = height
        if (kind === "pause") {
            const w = h * 0.28
            c.fillRect(h * 0.16, h * 0.14, w, h * 0.72)
            c.fillRect(h * 0.56, h * 0.14, w, h * 0.72)
            return
        }
        if (kind === "play") {      // a ring around the triangle, so Play differs from speed 1
            c.strokeStyle = tint
            c.lineWidth = Math.max(2, h * 0.07)
            c.beginPath()
            c.arc(width / 2, h / 2, h * 0.44, 0, Math.PI * 2)
            c.stroke()
            c.beginPath()
            c.moveTo(width / 2 - h * 0.12, h * 0.32)
            c.lineTo(width / 2 + h * 0.2, h * 0.5)
            c.lineTo(width / 2 - h * 0.12, h * 0.68)
            c.closePath()
            c.fill()
            return
        }
        const n = kind === "speed2" ? 2 : kind === "speed3" ? 3 : 1
        const tw = n === 1 ? h * 0.62 : h * 0.46
        const step = h * 0.34
        const total = tw + step * (n - 1)
        let x = (width - total) / 2
        for (let i = 0; i < n; i++) {
            c.beginPath()
            c.moveTo(x, h * 0.16)
            c.lineTo(x + tw, h * 0.5)
            c.lineTo(x, h * 0.84)
            c.closePath()
            c.fill()
            x += step
        }
    }
}
