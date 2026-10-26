// The game's fonts, read from the user's own game by the core (GET /fonts) and loaded here at run time.
// Nothing is bundled. Roles (theme.font.roles) name what each is for:
//   body   -> a FontLoader family, becomes theme.font once it is ready
//   header -> the game's Graystroke SDF atlas (drawn by GameText), else Economica Bold, else the body font bold
// Everything has a fallback: with no fonts, or a font that fails to load, the v1 look stays.
import QtQuick

QtObject {
    id: gf
    property var app
    property var entries: []                 // /fonts "fonts" list
    property var loaded: ({})                // /fonts name -> family a FontLoader registered
    property var atlas: null                 // prepared Graystroke table, or null
    property url atlasSource: ""
    readonly property bool atlasReady: !!atlas && atlasImage.status === Image.Ready
    property string headerFallbackFamily: ""   // Economica Bold when loaded
    property int generation: 0                // bumps when anything above changed
    readonly property var roles: app && app.theme ? app.theme.roles : ({})

    function refresh() {
        app.get("fonts", function(st, r) {
            if (st !== 200 || !r || !r.fonts) return
            gf.entries = r.fonts
        })
    }

    function entry(name) {
        for (const e of entries) if (e.name === name) return e
        return null
    }

    function recompute() {
        const m = {}
        for (let i = 0; i < loaders.count; i++) {
            const l = loaders.objectAt(i)
            if (l && l.status === FontLoader.Ready) m[l.fontName] = l.name
        }
        loaded = m
        // body font from the game
        const body = roles && roles.body && roles.body.font ? m[roles.body.font] : ""
        if (body) app.theme.font = body
        // header fallback: the first fallback family the game provides that is loaded (Economica), else the body font
        let hf = ""
        const wanted = (roles && roles.header && roles.header.fallback) || []
        for (const fam of wanted) {
            for (const e of entries) if (e.kind === "ttf" && e.family === fam && m[e.name] && /bold/i.test(e.style || "") && !/italic/i.test(e.style || "")) hf = m[e.name]
            if (hf) break
        }
        if (!hf && roles && roles.header && roles.header.font && m[roles.header.font]) hf = m[roles.header.font]
        headerFallbackFamily = hf
        app.theme.headerFont = hf ? hf : app.theme.font
        generation++
    }

    property string atlasKey: ""
    function loadAtlas() {
        const role = roles && roles.header
        const tbl = role && role.font ? entry(role.font) : null
        let img = null
        if (tbl && tbl.kind === "sdfAtlasTable")
            for (const e of entries) if (e.kind === "sdfAtlasImage" && e.family === tbl.family) img = e
        if (!img) { atlas = null; atlasSource = ""; atlasKey = ""; return }
        const key = tbl.url + ":" + tbl.size + ":" + img.size
        if (key === atlasKey) return          // same files: keep drawing with what is loaded
        atlasKey = key
        app.get(tbl.url.replace(/^\/api\/v1\//, ""), function(st, t) {
            if (st !== 200 || !t || !t.glyphs || !t.atlas || !t.face || atlasKey !== key) return
            const map = {}
            for (const g of t.glyphs) map[g.unicode] = g
            const kern = {}
            for (const k of (t.kerning || [])) kern[k.first * 1048576 + k.second] = k.x
            gf.atlas = { w: t.atlas.width, h: t.atlas.height, pad: t.atlas.padding, spread: t.atlas.spread,
                         pointSize: t.atlas.pointSize, chan: t.atlas.encoding === "sdf-red" ? 1 : 0,
                         lineHeight: t.face.lineHeight, ascent: t.face.ascent, descent: t.face.descent,
                         glyphs: map, kerning: kern }
            gf.atlasSource = app.artUrl(img.url)
        })
    }

    onEntriesChanged: {
        ttfModel = entries.filter(function(e) { return e.kind === "ttf" })
        loadAtlas()
        recompute()
    }
    onRolesChanged: { loadAtlas(); recompute() }

    property var ttfModel: []
    property var loaders: Instantiator {
        model: gf.ttfModel
        delegate: FontLoader {
            required property var modelData
            readonly property string fontName: modelData.name
            source: gf.app.artUrl(modelData.url)
            onStatusChanged: gf.recompute()
        }
        onCountChanged: gf.recompute()
    }
    property var atlasImage: Image {
        source: gf.atlasSource
        visible: false
        asynchronous: true
        smooth: true
        cache: true
        onStatusChanged: gf.generation++
    }
}
