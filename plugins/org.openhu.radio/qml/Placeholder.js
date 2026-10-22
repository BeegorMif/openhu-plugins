.pragma library

// Placeholder of a station without a picture: its initials on a muted colour of its name (white text stays
// readable); the page tints its background with the same colour

var colors = ["#2b4a6f", "#4a3b6b", "#2f5a4c", "#6b4430", "#5a2f45", "#3f4f2a", "#2b5a63", "#5c4a26", "#3d3f70",
              "#5e2f2f"]

function color(name) {
    var hash = 0
    for (var i = 0; i < name.length; ++i)
        hash = (hash * 31 + name.charCodeAt(i)) % 9973
    return colors[hash % colors.length]
}

function initials(name) {
    return name.split(/\s+/).filter(function(word) { return /[0-9A-Za-zÀ-ž]/.test(word) })
        .map(function(word) { return word.charAt(0) }).join("").slice(0, 2).toUpperCase()
}
