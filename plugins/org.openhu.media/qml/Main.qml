import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0
import "Music.js" as Music
import "Placeholder.js" as Placeholder

// Music player (openhu-plugins#38): the library in tabs (Albums, Artists, Songs, Playlists, Folders) with the same
// grid of square tiles everywhere, album/artist/playlist pages, the mini bar at the bottom and the player with
// "Up next". The process (bin/media.py) owns the state (music.state) and the library; the page asks it with
// music.query and sends music.command.
Item {
    id: page

    BusTopic { id: music; topic: "music.state" }

    readonly property var info: music.data || {}
    readonly property var track: page.info.track || null
    readonly property bool hasTrack: page.track !== null && page.track !== undefined
    readonly property bool playing: page.info.state === "playing"
    readonly property string mode: page.info.mode || "order"
    readonly property string repeatMode: page.info.repeat || "off"
    readonly property var context: page.info.context || ({})
    readonly property var scan: page.info.scan || ({})
    readonly property int version: (page.info.library || {}).version || 0
    readonly property int trackCount: (page.info.library || {}).tracks || 0
    readonly property int columns: page.info.columns || 4
    readonly property var sources: page.info.sources || []
    readonly property bool empty: page.info.library !== undefined && page.trackCount === 0 && !page.scan.active
    // touch targets of about 48 px at 800×480 (7"), larger on bigger screens
    readonly property int touch: Math.max(48, Math.round(72 * Theme.scale))

    // the position counts on between the (sparse) states while playing
    property real now: Date.now()
    readonly property real duration: page.info.duration || (page.hasTrack ? page.track.duration || 0 : 0)
    readonly property real position: Math.min(page.duration > 0 ? page.duration : 1e9,
        (page.info.position || 0) + (page.playing && page.info.positionTime ? Math.max(0, page.now - page.info.positionTime) / 1000 : 0))
    Timer {
        interval: 250
        repeat: true
        running: page.playing && page.visible
        onTriggered: page.now = Date.now()
    }

    property int tab: 0
    // album, artist and playlist pages opened from the tabs: [{kind, id, title}]
    property var stack: []
    property string songSort: "title"
    property bool playerOpen: false
    property var upNext: []

    readonly property var texts: ({
        unknownArtist: qsTrId("org.openhu.media.main.unknown_artist"),
        unknownAlbum: qsTrId("org.openhu.media.main.unknown_album"),
        headUnit: qsTrId("org.openhu.media.main.head_unit")
    })

    // --- talking to the process ---

    property int nextRequest: 1
    property var callbacks: ({})
    readonly property string requestPrefix: "music-page-" + Math.floor(Math.random() * 1e9) + "-"

    function query(cmd, params, callback) {
        var id = page.requestPrefix + page.nextRequest++
        page.callbacks[id] = callback
        api.emitEvent("music.query", Object.assign({ id: id, cmd: cmd }, params || {}))
    }

    function command(cmd, data) {
        api.emitEvent("music.command", Object.assign({ cmd: cmd }, data || {}))
    }

    Connections {
        target: eventBus
        function onEvent(topic, data) {
            if (topic === "music.result") {
                var callback = page.callbacks[data.id]
                if (callback) {
                    delete page.callbacks[data.id]
                    callback(data)
                }
            } else if (topic === "music.notice") {
                toast.show(data.text || "", data.error === true)
            }
        }
    }

    // --- texts of tiles and pages ---

    function plural(count, one, many) {
        return count === 1 ? one : many.arg(count)
    }

    function tileTitle(item) {
        if (!item)
            return ""
        if (item.kind === "artist")
            return item.title || page.texts.unknownArtist
        if (item.kind === "album")
            return item.title || page.texts.unknownAlbum
        if (item.kind === "folder" && item.sourceKind === "local" && item.path === "")
            return page.texts.headUnit
        return item.create ? qsTrId("org.openhu.media.main.new_playlist") : item.title || ""
    }

    function tileSubtitle(item) {
        if (!item || item.create)
            return ""
        switch (item.kind) {
        case "album":
            return item.subtitle || page.texts.unknownArtist
        case "artist":
            return page.plural(item.albums, qsTrId("org.openhu.media.main.one_album"), qsTrId("org.openhu.media.main.n_albums"))
        case "song":
            return item.artist || page.texts.unknownArtist
        case "playlist":
        case "folder":
            return page.plural(item.count, qsTrId("org.openhu.media.main.one_track"), qsTrId("org.openhu.media.main.n_tracks"))
        }
        return item.subtitle || ""
    }

    function typeText(type) {
        if (type === "own")
            return qsTrId("org.openhu.media.main.type_own")
        return type ? String(type).toUpperCase() : ""
    }

    function tileLabel(item) {
        return item && item.kind === "playlist" ? page.typeText(item.type) : ""
    }

    function length(seconds) {
        var minutes = Math.round((seconds || 0) / 60)
        return minutes >= 60 ? qsTrId("org.openhu.media.main.hours_minutes").arg(Math.floor(minutes / 60)).arg(minutes % 60)
            : qsTrId("org.openhu.media.main.minutes").arg(minutes)
    }

    function summary(info) {
        if (!info || info.count === undefined)
            return ""
        var parts = [page.plural(info.count, qsTrId("org.openhu.media.main.one_track"), qsTrId("org.openhu.media.main.n_tracks"))]
        if (info.duration > 0)
            parts.push(page.length(info.duration))
        if (info.year > 0)
            parts.push(String(info.year))
        return parts.join(" · ")
    }

    function sourceTitle(crumb) {
        return crumb.sourceKind === "local" ? page.texts.headUnit : crumb.title
    }

    function sourceText() {
        if (!page.hasTrack)
            return ""
        return page.track.sourceKind === "local" ? page.texts.headUnit : page.track.sourceName || ""
    }

    function modeText(mode) {
        return mode === "shuffle" ? qsTrId("org.openhu.media.main.mode_shuffle")
            : mode === "random" ? qsTrId("org.openhu.media.main.mode_random") : qsTrId("org.openhu.media.main.mode_order")
    }

    function repeatText(repeat) {
        return repeat === "all" ? qsTrId("org.openhu.media.main.repeat_all")
            : repeat === "one" ? qsTrId("org.openhu.media.main.repeat_one") : qsTrId("org.openhu.media.main.repeat_off")
    }

    // --- what plays ---

    function holds(item) {
        return page.hasTrack && page.info.state !== "stopped" && Music.holdsTrack(item, page.track, page.context)
    }

    function playingTrack(row) {
        return page.hasTrack && page.info.state !== "stopped" && !!row && row.id === page.track.id
    }

    function contextOf(item) {
        switch (item.kind) {
        case "album":
            return { kind: "album", id: item.id }
        case "artist":
            return { kind: "artist", id: item.id }
        case "playlist":
            return { kind: "playlist", id: item.id }
        case "folder":
            return { kind: "folder", source: item.source, path: item.path }
        }
        return { kind: "track", id: item.id }
    }

    function playContext(context, start, mode) {
        var data = { context: context }
        if (start !== null && start !== undefined)
            data.start = start
        if (mode)
            data.mode = mode
        page.command("playItems", data)
    }

    function cycleMode() {
        var next = page.mode === "order" ? "shuffle" : page.mode === "shuffle" ? "random" : "order"
        page.command("mode", { value: next })
        toast.show(page.modeText(next), false)
    }

    function cycleRepeat() {
        var next = page.repeatMode === "off" ? "all" : page.repeatMode === "all" ? "one" : "off"
        page.command("repeat", { value: next })
        toast.show(page.repeatText(next), false)
    }

    function push(entry) {
        page.stack = page.stack.concat([entry])
    }

    function pop() {
        page.stack = page.stack.slice(0, page.stack.length - 1)
    }

    function activate(item) {
        if (item.create) {
            listSheet.ask(null, "", "")
            return
        }
        switch (item.kind) {
        case "album":
        case "artist":
        case "playlist":
            page.push({ kind: item.kind, id: item.id, title: item.title })
            break
        case "song":
            page.playContext({ kind: "songs", sort: page.songSort }, item.id, null)
            break
        case "folder":
            page.tab = 4
            page.stack = []
            folderView.open(item.source, item.path)
            break
        }
    }

    function loadUpNext() {
        if (!page.playerOpen)
            return
        page.query("queue", { limit: 100 }, function(result) { page.upNext = result.items || [] })
    }

    onPlayerOpenChanged: page.loadUpNext()
    readonly property int queueVersion: (page.info.queue || {}).version || 0
    onQueueVersionChanged: page.loadUpNext()
    onHasTrackChanged: if (!page.hasTrack) page.playerOpen = false

    // --- the menu of a long press ---

    function openMenu(item) {
        if (!item || item.create)
            return
        var entries = [
            { action: "play", icon: "play", text: qsTrId("org.openhu.media.main.play") },
            { action: "next", icon: "playNext", text: qsTrId("org.openhu.media.main.play_next") },
            { action: "queue", icon: "addQueue", text: qsTrId("org.openhu.media.main.add_to_queue") },
            { action: "playlist", icon: "playlistAdd", text: qsTrId("org.openhu.media.main.add_to_playlist") }
        ]
        if (item.kind === "playlist" && item.own) {
            entries.push({ action: "rename", icon: "edit", text: qsTrId("org.openhu.media.main.rename") })
            entries.push({ action: "delete", icon: "trash", text: qsTrId("org.openhu.media.main.delete") })
        }
        if (item.queueEntry)
            entries.push({ action: "unqueue", icon: "remove", text: qsTrId("org.openhu.media.main.remove_from_queue") })
        if (item.playlist && item.playlistIndex >= 0)
            entries.push({ action: "unlist", icon: "remove", text: qsTrId("org.openhu.media.main.remove_from_playlist") })
        menu.item = item
        menu.entries = entries
        menu.title = page.tileTitle(item)
        menu.open()
    }

    function menuAction(action) {
        var item = menu.item
        menu.close()
        var context = page.contextOf(item)
        if (action === "play")
            page.playContext(context, null, item.kind === "song" ? null : "order")
        else if (action === "next" || action === "queue")
            page.command("enqueue", { context: context, next: action === "next" })
        else if (action === "playlist")
            page.chooseList(context, page.tileTitle(item))
        else if (action === "rename")
            listSheet.ask(null, item.id, item.title)
        else if (action === "delete")
            confirm.ask(item)
        else if (action === "unqueue")
            page.command("remove", { key: item.key })
        else if (action === "unlist")
            page.command("removeFromPlaylist", { playlist: item.playlist, index: item.playlistIndex })
    }

    function chooseList(context, title) {
        listSheet.context = context
        listSheet.mode = "choose"
        listSheet.title = qsTrId("org.openhu.media.main.add_to_playlist")
        listSheet.subject = title
        page.query("playlists", {}, function(result) {
            listSheet.lists = (result.items || []).filter(function(item) { return item.own })
        })
        listSheet.open()
    }

    // --- the page ---

    Backdrop {
        anchors.fill: parent
        source: page.hasTrack ? page.track.cover || "" : ""
        tint: page.hasTrack && page.track.title ? Placeholder.color(page.track.title) : Theme.background
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacing
        anchors.rightMargin: Theme.spacing
        anchors.bottomMargin: Math.round(Theme.spacing * 0.75)
        spacing: Math.round(Theme.spacing * 0.5)

        // tabs and the gear
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: page.touch

            Row {
                id: tabs
                anchors.left: parent.left
                anchors.right: gear.left
                height: parent.height
                readonly property var labels: [qsTrId("org.openhu.media.main.tab_albums"), qsTrId("org.openhu.media.main.tab_artists"),
                    qsTrId("org.openhu.media.main.tab_songs"), qsTrId("org.openhu.media.main.tab_playlists"),
                    qsTrId("org.openhu.media.main.tab_folders")]

                Repeater {
                    model: tabs.labels

                    AbstractButton {
                        id: tabButton
                        required property string modelData
                        required property int index
                        readonly property bool selected: page.tab === tabButton.index
                        width: tabs.width / tabs.labels.length
                        height: tabs.height
                        focusPolicy: Qt.NoFocus
                        onClicked: {
                            if (page.tab === tabButton.index && tabButton.index === 4 && page.stack.length === 0)
                                folderView.open("", "")
                            page.tab = tabButton.index
                            page.stack = []
                        }

                        contentItem: Text {
                            text: tabButton.modelData
                            color: tabButton.selected ? Theme.text : Theme.textDim
                            font.pixelSize: Math.round(Theme.fontLarge * 0.68)
                            font.weight: Font.Medium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        background: Item {
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: 1
                                color: Theme.textDim
                                opacity: 0.25
                            }
                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: parent.width
                                height: Math.max(3, Math.round(4 * Theme.scale))
                                color: Theme.primary
                                visible: tabButton.selected
                            }
                            Rectangle {
                                anchors.fill: parent
                                color: Theme.text
                                opacity: tabButton.down ? 0.06 : 0
                            }
                        }
                    }
                }
            }

            IconButton {
                id: gear
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: page.touch
                flat: true
                iconName: "gear"
                iconScale: 0.46
                Accessible.name: qsTrId("org.openhu.media.main.settings")
                onClicked: settings.open()
            }
        }

        // scan progress
        Column {
            Layout.fillWidth: true
            visible: page.scan.active === true
            spacing: Math.round(Theme.spacing * 0.25)

            Rectangle {
                id: scanTrack
                width: parent.width
                height: Math.max(3, Math.round(4 * Theme.scale))
                radius: height / 2
                color: Theme.outline
                clip: true

                Rectangle {
                    height: parent.height
                    radius: height / 2
                    color: Theme.primary
                    width: page.scan.total > 0 ? parent.width * Math.min(1, page.scan.done / page.scan.total) : parent.width * 0.3

                    SequentialAnimation on x {
                        running: page.scan.active === true && !(page.scan.total > 0)
                        loops: Animation.Infinite
                        NumberAnimation { from: 0; to: scanTrack.width * 0.7; duration: 900; easing.type: Easing.InOutQuad }
                        NumberAnimation { from: scanTrack.width * 0.7; to: 0; duration: 900; easing.type: Easing.InOutQuad }
                    }
                }
            }
            Text {
                width: parent.width
                readonly property string name: page.scan.sourceKind === "local" ? page.texts.headUnit : page.scan.source || ""
                text: page.scan.total > 0 ? qsTrId("org.openhu.media.main.scanning").arg(name).arg(page.scan.done).arg(page.scan.total)
                    : qsTrId("org.openhu.media.main.scanning_start").arg(name)
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
        }

        // the tabs' content
        Item {
            id: content
            Layout.fillWidth: true
            Layout.fillHeight: true
            readonly property bool library: page.stack.length === 0 && !page.empty

            LibraryGrid {
                anchors.fill: parent
                visible: content.library && page.tab === 0
                page: page
                columns: page.columns
                cmd: "albums"
                version: page.version
                onActivated: function(item) { page.activate(item) }
                onHeld: function(item) { page.openMenu(item) }
            }
            LibraryGrid {
                anchors.fill: parent
                visible: content.library && page.tab === 1
                page: page
                columns: page.columns
                cmd: "artists"
                version: page.version
                onActivated: function(item) { page.activate(item) }
                onHeld: function(item) { page.openMenu(item) }
            }
            LibraryGrid {
                id: songs
                anchors.fill: parent
                visible: content.library && page.tab === 2
                page: page
                columns: page.columns
                cmd: "songs"
                params: ({ sort: page.songSort })
                version: page.version
                onActivated: function(item) { page.activate(item) }
                onHeld: function(item) { page.openMenu(item) }

                header: Item {
                    width: songs.width
                    height: page.touch + Theme.spacing * 0.75

                    Row {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: Math.round(songs.gap / 2)
                        spacing: Math.round(Theme.spacing * 0.5)

                        Repeater {
                            model: [{ sort: "title", text: qsTrId("org.openhu.media.main.sort_title") },
                                    { sort: "artist", text: qsTrId("org.openhu.media.main.sort_artist") },
                                    { sort: "added", text: qsTrId("org.openhu.media.main.sort_added") }]

                            PillButton {
                                required property var modelData
                                touch: page.touch
                                text: modelData.text
                                checked: page.songSort === modelData.sort
                                onClicked: page.songSort = modelData.sort
                            }
                        }
                    }
                    PillButton {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.rightMargin: Math.round(songs.gap / 2)
                        touch: page.touch
                        primary: true
                        iconName: "shuffle"
                        text: qsTrId("org.openhu.media.main.shuffle_all")
                        onClicked: page.playContext({ kind: "songs", sort: page.songSort }, null, "shuffle")
                    }
                }
            }
            LibraryGrid {
                anchors.fill: parent
                visible: content.library && page.tab === 3
                page: page
                columns: page.columns
                cmd: "playlists"
                prefix: [{ create: true, kind: "playlist", id: "" }]
                version: page.version
                onActivated: function(item) { page.activate(item) }
                onHeld: function(item) { page.openMenu(item) }
            }
            FolderView {
                id: folderView
                anchors.fill: parent
                visible: content.library && page.tab === 4
                page: page
                columns: page.columns
                version: page.version
            }
            DetailView {
                anchors.fill: parent
                visible: page.stack.length > 0
                page: page
                columns: page.columns
                version: page.version
                entry: page.stack.length > 0 ? page.stack[page.stack.length - 1] : ({})
                onBackClicked: page.pop()
            }

            // nothing there yet
            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - Theme.spacing * 2, Math.round(620 * Theme.scale))
                visible: page.empty && page.stack.length === 0
                spacing: Math.round(Theme.spacing * 0.6)

                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.round(Theme.fontHuge * 0.8)
                    height: width
                    name: "usb"
                    color: Theme.textDim
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTrId("org.openhu.media.main.empty_title")
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge * 0.8
                    font.weight: Font.Medium
                    wrapMode: Text.Wrap
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTrId("org.openhu.media.main.empty_text")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontNormal * 0.85
                    wrapMode: Text.Wrap
                }
                Text {
                    width: parent.width
                    visible: text !== ""
                    horizontalAlignment: Text.AlignHCenter
                    text: page.info.error || ""
                    color: "#ff8a80"
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.Wrap
                }
            }
        }

        MiniBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(page.touch + Math.round(Theme.spacing * 0.6), Math.round(84 * Theme.scale))
            visible: page.hasTrack
            touch: page.touch
            track: page.track || ({})
            playing: page.playing
            position: page.position
            duration: page.duration
            mode: page.mode
            unknownArtist: page.texts.unknownArtist
            onOpened: page.playerOpen = true
            onPreviousClicked: page.command("previous")
            onToggleClicked: page.command("toggle")
            onNextClicked: page.command("next")
            onModeClicked: page.cycleMode()
        }
    }

    PlayerView {
        anchors.fill: parent
        visible: page.playerOpen && page.hasTrack
        z: 10
        touch: page.touch
        track: page.track || ({})
        playing: page.playing
        position: page.position
        duration: page.duration
        mode: page.mode
        repeat: page.repeatMode
        upNext: page.upNext
        sourceText: page.sourceText()
        unknownArtist: page.texts.unknownArtist
        onBackClicked: page.playerOpen = false
        onPreviousClicked: page.command("previous")
        onToggleClicked: page.command("toggle")
        onNextClicked: page.command("next")
        onModeClicked: page.cycleMode()
        onRepeatClicked: page.cycleRepeat()
        onSought: function(seconds) { page.command("seek", { value: seconds }) }
        onJumped: function(key) { page.command("jump", { key: key }) }
        onEntryMoved: function(key, to) { page.command("move", { key: key, to: to }) }
        onEntryHeld: function(entry) { page.openMenu(Object.assign({ kind: "song", queueEntry: true }, entry)) }
    }

    // --- sheets ---

    Sheet {
        id: settings
        anchors.fill: parent
        title: qsTrId("org.openhu.media.main.settings")

        Text {
            text: qsTrId("org.openhu.media.main.columns")
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
        Row {
            spacing: Math.round(Theme.spacing * 0.5)

            Repeater {
                model: [3, 4, 5, 6]

                PillButton {
                    required property int modelData
                    touch: page.touch
                    width: page.touch * 1.3
                    text: String(modelData)  // untranslated: a number
                    checked: page.columns === modelData
                    onClicked: page.command("set", { key: "columns", value: modelData })
                }
            }
        }
        Text {
            topPadding: Theme.spacing * 0.5
            visible: page.sources.length > 0
            text: qsTrId("org.openhu.media.main.sources")
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
        Repeater {
            model: page.sources

            MenuEntry {
                required property var modelData
                touch: page.touch
                enabled: false
                iconName: modelData.kind === "usb" ? "usb" : modelData.kind === "local" ? "headUnit" : "folder"
                text: (modelData.kind === "local" ? page.texts.headUnit : modelData.name) + " · "
                    + page.plural(modelData.tracks, qsTrId("org.openhu.media.main.one_track"), qsTrId("org.openhu.media.main.n_tracks"))
            }
        }
        MenuEntry {
            touch: page.touch
            iconName: "chevronRight"
            text: qsTrId("org.openhu.media.main.rescan")
            onClicked: {
                page.command("rescan")
                settings.close()
            }
        }
    }

    Sheet {
        id: menu
        anchors.fill: parent
        property var item: ({})
        property var entries: []

        Repeater {
            model: menu.entries

            MenuEntry {
                required property var modelData
                touch: page.touch
                iconName: modelData.icon
                text: modelData.text
                textColor: modelData.action === "delete" ? "#ff8a80" : Theme.text
                onClicked: page.menuAction(modelData.action)
            }
        }
    }

    // add to a playlist, a new playlist, renaming one
    Sheet {
        id: listSheet
        anchors.fill: parent
        nearTop: listSheet.mode === "name"
        property var context: null
        property var lists: []
        property string mode: "choose"
        property string subject
        property string renaming
        property string source

        function ask(context, renaming, name) {
            listSheet.context = context
            listSheet.renaming = renaming || ""
            listSheet.mode = "name"
            listSheet.title = renaming ? qsTrId("org.openhu.media.main.rename") : qsTrId("org.openhu.media.main.new_playlist")
            listSheet.source = ""
            nameField.text = name || ""
            listSheet.open()
            nameField.forceActiveFocus()
        }

        function submit() {
            var name = nameField.text.trim()
            if (name === "")
                return
            if (listSheet.renaming)
                page.command("renamePlaylist", { playlist: listSheet.renaming, name: name })
            else
                page.command("createPlaylist", { name: name, source: listSheet.source,
                                                 context: listSheet.context || undefined })
            nameField.focus = false
            listSheet.close()
        }

        onClosed: nameField.focus = false

        Text {
            width: parent.width
            visible: listSheet.mode === "choose" && listSheet.subject !== ""
            text: listSheet.subject
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            elide: Text.ElideRight
        }
        MenuEntry {
            visible: listSheet.mode === "choose"
            touch: page.touch
            iconName: "plus"
            text: qsTrId("org.openhu.media.main.new_playlist")
            onClicked: listSheet.ask(listSheet.context, "", "")
        }
        Repeater {
            model: listSheet.mode === "choose" ? listSheet.lists : []

            MenuEntry {
                required property var modelData
                touch: page.touch
                iconName: "playlist"
                text: modelData.title
                onClicked: {
                    page.command("addToPlaylist", { playlist: modelData.id, context: listSheet.context })
                    listSheet.close()
                }
            }
        }

        TextField {
            id: nameField
            width: parent.width
            visible: listSheet.mode === "name"
            placeholderText: qsTrId("org.openhu.media.main.playlist_name")
            font.pixelSize: Theme.fontNormal
            maximumLength: 120
            onAccepted: listSheet.submit()
        }
        // on which source a new playlist is saved (when there are several)
        Flow {
            width: parent.width
            visible: listSheet.mode === "name" && !listSheet.renaming && page.sources.length > 1
            spacing: Math.round(Theme.spacing * 0.5)

            Repeater {
                model: page.sources

                PillButton {
                    required property var modelData
                    required property int index
                    touch: page.touch
                    iconName: modelData.kind === "usb" ? "usb" : modelData.kind === "local" ? "headUnit" : "folder"
                    text: modelData.kind === "local" ? page.texts.headUnit : modelData.name
                    checked: listSheet.source === modelData.key || listSheet.source === "" && index === 0
                    onClicked: listSheet.source = modelData.key
                }
            }
        }
        Row {
            visible: listSheet.mode === "name"
            anchors.right: parent ? parent.right : undefined
            spacing: Math.round(Theme.spacing * 0.5)

            PillButton {
                touch: page.touch
                text: qsTrId("org.openhu.media.main.cancel")
                onClicked: listSheet.close()
            }
            PillButton {
                touch: page.touch
                primary: true
                enabled: nameField.text.trim() !== ""
                text: listSheet.renaming ? qsTrId("org.openhu.media.main.save") : qsTrId("org.openhu.media.main.create")
                onClicked: listSheet.submit()
            }
        }
    }

    Sheet {
        id: confirm
        anchors.fill: parent
        property var item: ({})

        function ask(item) {
            confirm.item = item
            confirm.title = qsTrId("org.openhu.media.main.delete_question").arg(item.title)
            confirm.open()
        }

        Text {
            width: parent.width
            text: qsTrId("org.openhu.media.main.delete_text")
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.Wrap
        }
        Row {
            anchors.right: parent ? parent.right : undefined
            spacing: Math.round(Theme.spacing * 0.5)

            PillButton {
                touch: page.touch
                text: qsTrId("org.openhu.media.main.cancel")
                onClicked: confirm.close()
            }
            PillButton {
                touch: page.touch
                primary: true
                iconName: "trash"
                text: qsTrId("org.openhu.media.main.delete")
                onClicked: {
                    page.command("deletePlaylist", { playlist: confirm.item.id })
                    confirm.close()
                    if (page.stack.length > 0 && page.stack[page.stack.length - 1].id === confirm.item.id)
                        page.pop()
                }
            }
        }
    }

    Toast {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: page.touch + Theme.spacing * 2
    }
}
