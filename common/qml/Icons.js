.pragma library

// Icons of the radio and music pages as SVG (24×24, own drawings), coloured per use: url("shuffle", "#4f9cf9") is a
// data URL for an Image. "C" in the markup is replaced by the colour.
var line = ' fill="none" stroke="C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
var bold = ' fill="none" stroke="C" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'

var shapes = {
    play: '<path d="M8 5.5v13l10.5-6.5z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>',
    pause: '<rect x="6.5" y="5.5" width="3.8" height="13" rx="1.2" fill="C"/>'
        + '<rect x="13.7" y="5.5" width="3.8" height="13" rx="1.2" fill="C"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="C"/>',
    previous: '<path d="M18.5 6.5v11L10 12z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>'
        + '<path d="M6.5 6v12" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    next: '<path d="M5.5 6.5v11L14 12z" fill="C" stroke="C" stroke-width="1.5" stroke-linejoin="round"/>'
        + '<path d="M17.5 6v12" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    minus: '<path d="M5 12h14" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    plus: '<path d="M5 12h14M12 5v14" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    onAir: '<path d="M5 10.5v3M9 7v10M13 9v6M17 5.5v13M21 10.5v3" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',

    // playback modes
    order: '<g' + line + '><path d="M4 7h9M4 12h9M4 17h6"/><path d="M18 6v12M15.5 15.5 18 18l2.5-2.5"/></g>',
    shuffle: '<g' + line + '><path d="M3.5 7H7c3 0 4.2 2 5.5 5s2.5 5 5.5 5h2.5"/><path d="M3.5 17H7c1.4 0 2.4-.5 3.2-1.4"/>'
        + '<path d="M13.8 8.4C14.6 7.5 15.6 7 17 7h3.5"/><path d="M18 4.5 20.5 7 18 9.5M18 14.5l2.5 2.5-2.5 2.5"/></g>',
    random: '<rect x="4" y="4" width="16" height="16" rx="3.5"' + line + '/>'
        + '<g fill="C"><circle cx="8.6" cy="8.6" r="1.5"/><circle cx="15.4" cy="8.6" r="1.5"/>'
        + '<circle cx="12" cy="12" r="1.5"/><circle cx="8.6" cy="15.4" r="1.5"/><circle cx="15.4" cy="15.4" r="1.5"/></g>',
    repeat: '<g' + line + '><path d="M4.5 11.5V10a3.5 3.5 0 0 1 3.5-3.5h11"/><path d="M16 3.5l3 3-3 3"/>'
        + '<path d="M19.5 12.5V14a3.5 3.5 0 0 1-3.5 3.5H5"/><path d="M8 20.5l-3-3 3-3"/></g>',
    repeatOne: '<g' + line + '><path d="M4.5 11.5V10a3.5 3.5 0 0 1 3.5-3.5h11"/><path d="M16 3.5l3 3-3 3"/>'
        + '<path d="M19.5 12.5V14a3.5 3.5 0 0 1-3.5 3.5H5"/><path d="M8 20.5l-3-3 3-3"/></g>'
        + '<path d="M10.8 10.6 12.4 9.6v5" fill="none" stroke="C" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',

    // what a tile is
    disc: '<circle cx="12" cy="12" r="8.5"' + line + '/><circle cx="12" cy="12" r="2.3" fill="C"/>'
        + '<path d="M7.6 9.2a5 5 0 0 1 2.6-2.6" fill="none" stroke="C" stroke-width="1.6" stroke-linecap="round"/>',
    microphone: '<g' + line + '><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0"/>'
        + '<path d="M12 17.5V21M9 21h6"/></g>',
    note: '<path d="M10 17V5.5l9-2v11.5" fill="none" stroke="C" stroke-width="2" stroke-linejoin="round"/>'
        + '<circle cx="7.4" cy="17.2" r="2.8" fill="C"/><circle cx="16.4" cy="15.2" r="2.8" fill="C"/>',
    playlist: '<g' + line + '><path d="M4 6h11M4 10.5h11M4 15h6.5"/><path d="M17.5 17.5V8l3 1"/></g>'
        + '<circle cx="15.3" cy="17.6" r="2.4" fill="C"/>',
    folder: '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h3.6l2 2.2h7.4a2 2 0 0 1 2 2v7.3a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"'
        + line + '/>',

    // radio
    heart: '<path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6a5 5 0 1 1 7.5 6.6z" fill="none" stroke="C"'
        + ' stroke-width="2" stroke-linejoin="round"/>',
    heartFilled: '<path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6a5 5 0 1 1 7.5 6.6z" fill="C" stroke="C"'
        + ' stroke-width="2" stroke-linejoin="round"/>',
    scan: '<g fill="none" stroke="C" stroke-width="2" stroke-linecap="round"><path d="M20 12a8 8 0 1 1-8-8"/>'
        + '<path d="M16 12a4 4 0 1 1-4-4"/><path d="M12 12l6.5-6.5"/></g>',
    radio: '<g fill="none" stroke="C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        + '<rect x="3" y="8.5" width="18" height="12" rx="2.5"/><path d="M7 8.5 17 4"/><circle cx="9" cy="14.5" r="2.6"/>'
        + '<path d="M14.5 13h3M14.5 16h3"/></g>',

    // actions and places
    gear: '<g' + line + '><circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2'
        + 'M6 6l1.6 1.6M16.4 16.4 18 18M6 18l1.6-1.6M16.4 7.6 18 6"/><circle cx="12" cy="12" r="6.3"/></g>',
    back: '<path d="M14.5 5.5 8 12l6.5 6.5"' + bold + '/>',
    library: '<g' + line + '><rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/>'
        + '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/></g>',
    chevronRight: '<path d="M9.5 6l6 6-6 6"' + line + '/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"' + bold + '/>',
    playNext: '<g' + line + '><path d="M4 6h11M4 11h11M4 16h6"/></g><path d="M15 13.5v7l5.5-3.5z" fill="C"'
        + ' stroke="C" stroke-width="1.2" stroke-linejoin="round"/>',
    addQueue: '<g' + line + '><path d="M4 6h11M4 11h11M4 16h6M17.5 13v7M14 16.5h7"/></g>',
    playlistAdd: '<g' + line + '><path d="M4 6h10M4 10.5h10M4 15h6M17.5 12v8M13.5 16h8"/></g>',
    edit: '<g' + line + '><path d="M4.5 19.5h4l10-10-4-4-10 10z"/><path d="M13 7l4 4"/></g>',
    trash: '<g' + line + '><path d="M4.5 7h15M10 7V4.8h4V7M6.5 7l1 12.5h9l1-12.5"/></g>',
    remove: '<path d="M6 12h12" stroke="C" stroke-width="2.2" stroke-linecap="round"/>',
    drag: '<g fill="C"><circle cx="9" cy="6.5" r="1.6"/><circle cx="15" cy="6.5" r="1.6"/><circle cx="9" cy="12" r="1.6"/>'
        + '<circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="17.5" r="1.6"/><circle cx="15" cy="17.5" r="1.6"/></g>',
    usb: '<g' + line + '><rect x="7" y="9.5" width="10" height="11.5" rx="2"/><path d="M9.3 9.5V3.5h5.4v6"/></g>'
        + '<g fill="C"><rect x="10.3" y="5.2" width="1.3" height="1.8"/><rect x="12.4" y="5.2" width="1.3" height="1.8"/></g>',
    headUnit: '<g' + line + '><rect x="3" y="5" width="18" height="11.5" rx="2"/><path d="M8.5 20h7M12 16.5V20"/></g>'
}

function url(name, color) {
    var shape = shapes[name]
    if (!shape)
        return ""
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' + shape.replace(/"C"/g, '"' + color + '"')
        + '</svg>'
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg)
}
