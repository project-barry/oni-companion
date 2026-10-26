// Colors and type sizes. Meaning (tone) comes from the core; colors are chosen here.
// v1.1: the core's GET /theme (game colors and 9-slice images, or the built-in dark theme)
// is applied with apply(); until it arrives, or if it fails, the v1 look below stays.
import QtQuick

QtObject {
    id: t
    property real s: 1
    property bool game: false            // true once a theme with source "game" is applied
    property color bg: "#0e1218"
    property color panel: "#18202a"
    property color panelHi: "#222c39"
    property color header: "#18202a"
    property color line: "#2c3846"
    property color text: "#eef0f4"
    property color title: "#eef0f4"
    property color muted: "#9aa4b5"
    property color accent: "#5aa9ff"
    property color good: "#4cc38a"
    property color warn: "#e8b44a"
    property color bad: "#ef5b5b"
    property color buttonNormal: "#18202a"
    property color buttonHover: "#222c39"
    property color buttonPressed: "#222c39"
    property color progressFill: "#5aa9ff"
    property color progressTrack: "#2c3846"
    property color meterStress: "#e8b44a"
    property color meterHealth: "#ef5b5b"
    property color meterCalories: "#5aa9ff"
    // v1.2: section bars, tabs, alert list (the v1 look until a game theme sets them)
    property color sectionHeader: "#222c39"
    property color sectionHeaderText: "#eef0f4"
    property color tabBg: "#18202a"
    property color tabActiveBg: "#18202a"
    property color tabText: "#9aa4b5"
    property color tabTextActive: "#eef0f4"
    property color alertBg: "#18202a"
    property color alertText: "#eef0f4"
    property color alertBadBg: "#18202a"
    property color alertBadText: "#ef5b5b"
    property var slices: ({})            // name -> { art, width, height, insets }
    property string font: "Noto Sans"            // body family; the game's own body font once GameFonts has loaded it
    property string headerFont: "Noto Sans"      // fallback header family (the game's Economica Bold when loaded)
    property var roles: ({})                     // v1.2: font roles from the core (theme.font.roles)
    property var icons: ({})             // v1.2: name -> { art, width, height } (speedPause, speedPlay, speed1..3)
    readonly property int body: Math.round(30 * s)
    readonly property int small: Math.round(24 * s)
    readonly property int tap: Math.round(80 * s)
    readonly property int gap: Math.round(20 * s)
    readonly property int radius: game ? Math.round(4 * s) : Math.round(20 * s)   // the game's panels are nearly square

    // #RRGGBB, or #RRGGBBAA as the contract writes it (Qt itself reads 8 digits as #AARRGGBB).
    function col(h) {
        if (typeof h === "string" && h.length === 9 && h.charAt(0) === "#")
            return Qt.rgba(parseInt(h.substr(1, 2), 16) / 255, parseInt(h.substr(3, 2), 16) / 255,
                           parseInt(h.substr(5, 2), 16) / 255, parseInt(h.substr(7, 2), 16) / 255)
        return h
    }

    // Takes the /theme reply. Unknown or missing tokens keep the current value.
    function apply(th) {
        if (!th || !th.colors) return
        const c = th.colors
        if (c.background) bg = col(c.background)
        if (c.panel) panel = col(c.panel)
        if (c.header) header = col(c.header)
        if (c.border) line = col(c.border)
        if (c.text) text = col(c.text)
        if (c.textTitle) title = col(c.textTitle)
        if (c.textDim) muted = col(c.textDim)
        if (c.info) accent = col(c.info)
        if (c.positive) good = col(c.positive)
        if (c.negative) bad = col(c.negative)
        if (c.warning) warn = col(c.warning)
        if (c.buttonNormal) buttonNormal = col(c.buttonNormal)
        if (c.buttonHover) { buttonHover = col(c.buttonHover); panelHi = col(c.buttonHover) }
        if (c.buttonPressed) buttonPressed = col(c.buttonPressed)
        if (c.progressFill) progressFill = col(c.progressFill)
        if (c.progressTrack) progressTrack = col(c.progressTrack)
        if (c.meterStress) meterStress = col(c.meterStress)
        if (c.meterHealth) meterHealth = col(c.meterHealth)
        if (c.meterCalories) meterCalories = col(c.meterCalories)
        if (c.sectionHeader) sectionHeader = col(c.sectionHeader)
        if (c.sectionHeaderText) sectionHeaderText = col(c.sectionHeaderText)
        if (c.tabBg) tabBg = col(c.tabBg)
        if (c.tabActiveBg) tabActiveBg = col(c.tabActiveBg)
        if (c.tabText) tabText = col(c.tabText)
        if (c.tabTextActive) tabTextActive = col(c.tabTextActive)
        if (c.alertBg) alertBg = col(c.alertBg)
        if (c.alertText) alertText = col(c.alertText)
        if (c.alertBadBg) alertBadBg = col(c.alertBadBg)
        if (c.alertBadText) alertBadText = col(c.alertBadText)
        roles = (th.font && th.font.roles) || ({})
        const m = {}
        for (const sl of (th.slices || [])) if (sl && sl.name && sl.art && sl.insets) m[sl.name] = sl
        slices = m
        const ic = {}
        for (const i of (th.icons || [])) if (i && i.name && i.art) ic[i.name] = i
        icons = ic
        game = th.source === "game"
    }
    // Text drawn straight on the page background (not on a panel): the title color in a game theme (white on the dark page).
    readonly property color pageText: game ? title : text
    // Text on the game's dark slate buttons (buttonNormal): the title color, white.
    readonly property color buttonText: game ? title : text
    function slice(name) { return slices[name] || null }
    function icon(name) { return icons[name] || null }
    // v1.2: a span's `color` is a theme color token (blocks.schema.json ColorToken); "" = the caller's own color.
    function token(name) {
        switch (name) {
        case "text": return text
        case "textDim": return muted
        case "textTitle": return title
        case "positive": return good
        case "negative": return bad
        case "warning": return warn
        case "info": return accent
        case "alertText": return alertText
        case "alertBadText": return alertBadText
        default: return ""
        }
    }

    function tone(name) {
        switch (name) {
        case "good": return good
        case "warn": return warn
        case "bad": return bad
        case "info": return accent
        default: return muted
        }
    }
    // Badge level (danger / warn / info) as a color.
    function level(name) {
        return name === "danger" ? bad : name === "warn" ? warn : accent
    }
    // Tone color for a value; neutral stays the normal text color.
    function valueTone(name) {
        return (name && name !== "neutral") ? tone(name) : text
    }
    // Meter fill: a warn or bad tone always shows as such; otherwise the game's own
    // meter color for stress, health and calories (when a game theme is applied).
    function meterColor(label, toneName) {
        if (toneName === "warn" || toneName === "bad") return tone(toneName)
        if (game) {
            const l = String(label).toLowerCase()
            if (l === "stress") return meterStress
            if (l === "health") return meterHealth
            if (l === "calories") return meterCalories
            return progressFill
        }
        return toneName === "good" ? good : accent
    }
    function stateColor(state) {
        switch (state) {
        case "solid": return "#8b7355"
        case "liquid": return "#3f7fd0"
        case "gas": return "#7fcfd8"
        default: return "#3a3f4a"
        }
    }
}
