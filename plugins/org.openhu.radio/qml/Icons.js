.pragma library

// Icons of the radio page as SVG (24×24, own drawings), coloured per use: url("heart", "#ff6b81") is a data URL for
// an Image. "C" in the markup is replaced by the colour.
var shapes = {
    play: '<path d="M8 5.5v13l10.5-6.5z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="C"/>',
    previous: '<path d="M18.5 6.5v11L10 12z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>'
        + '<path d="M6.5 6v12" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    next: '<path d="M5.5 6.5v11L14 12z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>'
        + '<path d="M17.5 6v12" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    minus: '<path d="M5 12h14" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    plus: '<path d="M5 12h14M12 5v14" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    heart: '<path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6a5 5 0 1 1 7.5 6.6z" fill="none" stroke="C"'
        + ' stroke-width="2" stroke-linejoin="round"/>',
    heartFilled: '<path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6a5 5 0 1 1 7.5 6.6z" fill="C" stroke="C"'
        + ' stroke-width="2" stroke-linejoin="round"/>',
    scan: '<g fill="none" stroke="C" stroke-width="2" stroke-linecap="round"><path d="M20 12a8 8 0 1 1-8-8"/>'
        + '<path d="M16 12a4 4 0 1 1-4-4"/><path d="M12 12l6.5-6.5"/></g>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    radio: '<g fill="none" stroke="C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        + '<rect x="3" y="8.5" width="18" height="12" rx="2.5"/><path d="M7 8.5 17 4"/><circle cx="9" cy="14.5" r="2.6"/>'
        + '<path d="M14.5 13h3M14.5 16h3"/></g>',
    onAir: '<path d="M5 10.5v3M9 7v10M13 9v6M17 5.5v13M21 10.5v3" stroke="C" stroke-width="2.2" stroke-linecap="round"/>'
}

function url(name, color) {
    var shape = shapes[name]
    if (!shape)
        return ""
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' + shape.replace(/"C"/g, '"' + color + '"')
        + '</svg>'
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg)
}
