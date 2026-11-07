import QtQuick
import OpenHU 1.0
import "../lib/qml"
import "Music.js" as Music

// The library grid: the same square tiles and columns in every tab (columns: the plugin setting). items: tiles
// of the process ({kind, id, title, covers, ...}); page: the music page (texts, the track that plays). Asks for
// more (moreRequested) when it is scrolled near the end.
GridView {
    id: grid

    property var page
    property var items: []
    property int columns: 4
    property bool hasMore: false

    signal activated(var item)
    signal held(var item)
    signal moreRequested()

    readonly property real tileSide: Math.floor(grid.width / grid.columns) - grid.gap
    readonly property real gap: Math.round(Theme.spacing * 0.75)

    clip: true
    model: grid.items
    cellWidth: Math.floor(grid.width / grid.columns)
    cellHeight: grid.tileSide + Math.round(Theme.fontNormal * 2.9)
    boundsBehavior: Flickable.StopAtBounds
    cacheBuffer: Math.round(grid.cellHeight * 2)

    onContentYChanged: grid.checkMore()
    onCountChanged: grid.checkMore()
    onHeightChanged: grid.checkMore()

    function checkMore() {
        if (grid.hasMore && grid.contentHeight - grid.contentY - grid.height < grid.cellHeight * 2)
            grid.moreRequested()
    }

    delegate: Item {
        id: cell
        required property var modelData
        width: grid.cellWidth
        height: grid.cellHeight

        Tile {
            x: Math.round(grid.gap / 2)
            width: grid.tileSide
            height: parent.height
            badgeIcon: cell.modelData.create ? "" : Music.badgeIcon(cell.modelData.kind)
            create: cell.modelData.create === true
            covers: cell.modelData.covers || (cell.modelData.cover ? [cell.modelData.cover] : [])
            title: grid.page.tileTitle(cell.modelData)
            subtitle: grid.page.tileSubtitle(cell.modelData)
            label: grid.page.tileLabel(cell.modelData)
            placeholderIcon: cell.modelData.kind === "folder" ? "folder" : Music.badgeIcon(cell.modelData.kind)
            playing: grid.page.holds(cell.modelData)
            dimmed: cell.modelData.available === false
            onClicked: grid.activated(cell.modelData)
            onHeld: grid.held(cell.modelData)
        }
    }
}
