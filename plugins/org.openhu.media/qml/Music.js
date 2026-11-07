.pragma library

// Helpers of the music page without QML: times, the icon of a tile, whether a tile holds the track that plays.

function time(seconds) {
    var total = Math.max(0, Math.floor(seconds || 0))
    var hours = Math.floor(total / 3600)
    var minutes = Math.floor((total % 3600) / 60)
    var rest = total % 60
    var pad = function(value) { return value < 10 ? "0" + value : String(value) }
    return hours > 0 ? hours + ":" + pad(minutes) + ":" + pad(rest) : minutes + ":" + pad(rest)
}

// the small round badge of a tile
function badgeIcon(kind) {
    return { album: "disc", artist: "microphone", song: "note", playlist: "playlist", folder: "folder",
             source: "usb", local: "headUnit" }[kind] || "note"
}

function modeIcon(mode) {
    return mode === "shuffle" ? "shuffle" : mode === "random" ? "random" : "order"
}

function repeatIcon(repeat) {
    return repeat === "one" ? "repeatOne" : "repeat"
}

// true if the tile (album, artist, song, playlist, folder) holds the track that plays
function holdsTrack(item, track, context) {
    if (!item || !track || !track.id)
        return false
    switch (item.kind) {
    case "album":
        return item.id === track.albumId
    case "artist":
        return item.id === (track.albumArtist !== undefined ? track.albumArtist : track.artist)
    case "song":
        return item.id === track.id
    case "playlist":
        return !!context && context.kind === "playlist" && context.id === item.id
    case "folder":
        if (item.source !== track.source)
            return false
        return !item.path || track.folder === item.path || String(track.folder).indexOf(item.path + "/") === 0
    }
    return false
}
