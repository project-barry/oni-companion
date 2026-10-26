// Spans: plain / bold / ref link / external link. Taps on links navigate.
// v1.2: a span may carry `color` (a theme color token), `icon` (an inline picture, art kind ui) and
// `action` (a tapped link in the game's tooltip: alert_activate with that link). Rendering only:
// the core already turned the game's markup into spans.
import QtQuick

Text {
    id: t
    property var app
    property var block
    width: parent ? parent.width : 0
    wrapMode: Text.Wrap
    textFormat: Text.StyledText
    linkColor: app.theme.accent
    color: app.theme.pageText
    lineHeight: 1.2
    font { family: app.theme.font; pixelSize: app.theme.body }
    function hex(c) {
        function h(v) { const x = Math.round(v * 255).toString(16); return x.length < 2 ? "0" + x : x }
        return "#" + h(c.r) + h(c.g) + h(c.b)
    }
    // Text for StyledText: escaped, line breaks as <br>, edge spaces kept.
    function body(s) {
        return app.esc(s).replace(/\n/g, "<br>").replace(/^ /, "&nbsp;").replace(/ $/, "&nbsp;")
    }
    function spanHtml(x, i) {
        let out = body(x.text || "")
        if (x.type === "bold") out = "<b>" + out + "</b>"
        const tk = x.color ? app.theme.token(x.color) : ""
        if (tk !== "") out = "<font color=\"" + hex(tk) + "\">" + out + "</font>"
        if (x.type === "ref" && x.ref)
            out = "<a href=\"ref:" + encodeURIComponent(x.ref.kind) + ":" + encodeURIComponent(x.ref.id) + "\">" + out + "</a>"
        else if (x.type === "link" && x.url)
            out = "<a href=\"" + app.esc(x.url).replace(/"/g, "%22") + "\">" + out + "</a>"
        else if (x.action && x.action.id)
            out = "<a href=\"span:" + i + "\">" + out + "</a>"
        if (x.icon && app.artUrl(x.icon) !== "")
            out = "<img src=\"" + app.artUrl(x.icon) + "\" width=\"" + app.theme.body + "\" height=\"" + app.theme.body + "\">" + out
        return out
    }
    text: {
        let out = ""
        const sp = (block && block.spans) || []
        for (let i = 0; i < sp.length; i++) out += spanHtml(sp[i], i)
        return out
    }
    onLinkActivated: link => {
        if (link.indexOf("span:") === 0) {
            const x = ((block && block.spans) || [])[Number(link.substring(5))]
            if (x && x.action) app.runAction(x.action, function(state, msg) { if (state === "failed") app.toast(msg) })
        } else app.activateLink(link)
    }
}
