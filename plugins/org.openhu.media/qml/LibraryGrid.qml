import QtQuick

// A tab of the library as a grid: loads its tiles page by page with music.query (cmd, params), again when the
// library changes (version) while it is shown. prefix: tiles before the loaded ones ("New playlist").
TileGrid {
    id: library

    property string cmd
    property var params: ({})
    property int version: 0
    property var prefix: []
    property var loaded: []
    property int total: 0
    property bool loading: false
    property bool stale: true
    property int generation: 0
    readonly property bool empty: !library.loading && !library.stale && library.loaded.length === 0
    readonly property int pageSize: 120

    items: library.prefix.concat(library.loaded)
    hasMore: library.loaded.length < library.total

    function reload() {
        if (!library.visible || !library.page) {
            library.stale = true
            return
        }
        library.stale = false
        library.loading = true
        var generation = ++library.generation
        library.page.query(library.cmd, Object.assign({ offset: 0, limit: library.pageSize }, library.params),
                           function(result) {
            if (generation !== library.generation)
                return
            library.loading = false
            library.loaded = result.items || []
            library.total = result.total || library.loaded.length
        })
    }

    onVersionChanged: library.reload()
    onParamsChanged: library.reload()
    onCmdChanged: library.reload()
    onVisibleChanged: if (library.visible && library.stale) library.reload()
    Component.onCompleted: library.reload()

    onMoreRequested: {
        if (library.loading || !library.hasMore)
            return
        library.loading = true
        var generation = library.generation
        library.page.query(library.cmd, Object.assign({ offset: library.loaded.length, limit: library.pageSize },
                                                      library.params), function(result) {
            if (generation !== library.generation)
                return
            library.loading = false
            // a new array resets the view: keep the scroll position
            var y = library.contentY
            library.loaded = library.loaded.concat(result.items || [])
            library.contentY = y
        })
    }
}
