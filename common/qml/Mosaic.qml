import QtQuick
import OpenHU 1.0

// The picture of a tile: a 2×2 mosaic of album covers (artists, playlists, folders) from two covers on (two or three
// are repeated crosswise), else the one cover; without one the placeholder (initials of the name, or the icon)
Item {
    id: mosaic

    property var covers: []
    property string name
    property string icon: "note"
    property bool dimmed: false
    property bool fit: false

    readonly property bool tiled: mosaic.covers.length >= 2
    readonly property var cells: mosaic.covers.length >= 4 ? mosaic.covers.slice(0, 4)
        : mosaic.covers.length === 3 ? [mosaic.covers[0], mosaic.covers[1], mosaic.covers[2], mosaic.covers[0]]
        : mosaic.covers.length === 2 ? [mosaic.covers[0], mosaic.covers[1], mosaic.covers[1], mosaic.covers[0]] : []

    opacity: mosaic.dimmed ? 0.45 : 1

    Artwork {
        anchors.fill: parent
        visible: !mosaic.tiled
        source: mosaic.covers.length > 0 ? mosaic.covers[0] : ""
        name: mosaic.name
        icon: mosaic.icon
        fit: mosaic.fit
    }

    Rectangle {
        anchors.fill: parent
        visible: mosaic.tiled
        radius: Math.max(3, Math.round(width / 28))
        color: Theme.surfaceHigh
        clip: true

        Grid {
            anchors.fill: parent
            columns: 2

            Repeater {
                model: mosaic.cells

                Image {
                    required property string modelData
                    width: mosaic.width / 2
                    height: mosaic.height / 2
                    source: modelData
                    sourceSize.width: width
                    sourceSize.height: height
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                }
            }
        }
    }
}
