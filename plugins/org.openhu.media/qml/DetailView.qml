import QtQuick

// The page of an album or playlist (header and the track rows) or of an artist (header and the albums as tiles).
// entry: {kind, id, title}; loaded with music.query, again when the library changes (version).
Item {
    id: detail

    property var page
    property var entry: ({})
    property int version: 0
    property int columns: 4
    property var info: ({})
    property int generation: 0

    readonly property string kind: detail.entry.kind || ""
    readonly property var tracks: detail.info.tracks || []

    signal backClicked()

    // reads entry itself: in onEntryChanged the bindings on it (kind) may not be updated yet
    function reload() {
        var kind = detail.entry.kind || ""
        if (!detail.page || !kind)
            return
        var generation = ++detail.generation
        var id = detail.entry.id
        var params = {}
        params[kind] = id
        detail.page.query(kind, params, function(result) {
            if (generation === detail.generation)
                detail.info = result.ok === false ? {} : Object.assign({}, result, { id: id })
        })
    }

    onEntryChanged: {
        detail.info = {}
        detail.reload()
    }
    onVersionChanged: detail.reload()

    readonly property var context: detail.kind === "album" ? { kind: "album", id: detail.entry.id }
        : detail.kind === "artist" ? { kind: "artist", id: detail.entry.id }
        : { kind: "playlist", id: detail.entry.id }

    Component {
        id: headerComponent

        DetailHeader {
            width: detail.width
            touch: detail.page ? detail.page.touch : 48
            kind: detail.kind
            covers: detail.info.covers || (detail.info.cover ? [detail.info.cover] : [])
            title: detail.page ? detail.page.tileTitle(Object.assign({ kind: detail.kind }, detail.entry, detail.info)) : ""
            subtitle: detail.kind === "album" ? (detail.info.artist || (detail.page ? detail.page.texts.unknownArtist : ""))
                : detail.kind === "playlist" && detail.page ? detail.page.typeText(detail.info.type) : ""
            info: detail.page ? detail.page.summary(detail.info) : ""
            own: detail.info.own === true
            onBackClicked: detail.backClicked()
            onPlayClicked: detail.page.playContext(detail.context, null, "order")
            onShuffleClicked: detail.page.playContext(detail.context, null, "shuffle")
            onAddClicked: detail.page.chooseList(detail.context, detail.page.tileTitle(Object.assign({ kind: detail.kind }, detail.entry, detail.info)))
            onMoreClicked: detail.page.openMenu(Object.assign({ kind: "playlist" }, detail.entry, detail.info))
        }
    }

    ListView {
        id: rows
        anchors.fill: parent
        visible: detail.kind !== "artist"
        clip: true
        model: detail.tracks
        header: headerComponent
        boundsBehavior: Flickable.StopAtBounds

        delegate: TrackRow {
            id: row
            required property var modelData
            required property int index
            width: ListView.view.width
            touch: detail.page.touch
            showCover: detail.kind !== "album"
            number: detail.kind === "album" ? (row.modelData.track || row.index + 1) : row.index + 1
            title: row.modelData.title || ""
            subtitle: detail.kind === "album" ? (row.modelData.artist !== detail.info.artist ? row.modelData.artist || "" : "")
                : row.modelData.artist || ""
            cover: row.modelData.cover || ""
            duration: row.modelData.duration || 0
            available: row.modelData.available !== false
            playing: detail.page.playingTrack(row.modelData)
            onClicked: if (row.available) detail.page.playContext(detail.context, row.modelData.id, null)
            onHeld: detail.page.openMenu(Object.assign({ kind: "song", playlistIndex: detail.kind === "playlist" ? row.index : -1,
                                                         playlist: detail.info.own ? detail.entry.id : "" }, row.modelData))
        }
    }

    TileGrid {
        anchors.fill: parent
        visible: detail.kind === "artist"
        page: detail.page
        columns: detail.columns
        items: detail.kind === "artist" ? detail.info.items || [] : []
        header: headerComponent
        onActivated: function(item) { detail.page.activate(item) }
        onHeld: function(item) { detail.page.openMenu(item) }
    }
}
