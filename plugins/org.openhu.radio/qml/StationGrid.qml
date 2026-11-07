import QtQuick
import OpenHU 1.0
import "../lib/qml"

// The stations of a tab as square tiles, the same size and columns in every tab (columns: the plugin setting).
// entries: Main.entry() ({band, key, name, title, detail, text, logo, favorite, current, badgeText, badgeIcon}).
// Tap: tune, long press: favorite.
GridView {
    id: grid

    property var entries: []
    property int columns: 4
    property bool playing: false

    signal activated(var entry)
    signal held(var entry)

    readonly property real gap: Math.round(Theme.spacing * 0.75)
    readonly property real tileSide: Math.floor(grid.width / grid.columns) - grid.gap

    clip: true
    model: grid.entries
    cellWidth: Math.floor(grid.width / grid.columns)
    cellHeight: grid.tileSide + Math.round(Theme.fontNormal * 2.9)
    boundsBehavior: Flickable.StopAtBounds

    delegate: Item {
        id: cell
        required property var modelData
        width: grid.cellWidth
        height: grid.cellHeight

        Tile {
            x: Math.round(grid.gap / 2)
            width: grid.tileSide
            height: parent.height
            covers: cell.modelData.logo ? [cell.modelData.logo] : []
            fit: true
            title: cell.modelData.title
            // without a name (FM before RDS) the radio icon, not the initials of the frequency
            pictureName: cell.modelData.name
            // the station that plays: its radio text
            subtitle: cell.modelData.text || cell.modelData.detail
            subtitleLive: cell.modelData.text !== ""
            placeholderIcon: "radio"
            badgeText: cell.modelData.badgeText
            badgeIcon: cell.modelData.badgeIcon
            badgeColor: "#ff6b81"
            playing: cell.modelData.current && grid.playing
            onClicked: grid.activated(cell.modelData)
            onHeld: grid.held(cell.modelData)
        }
    }
}
