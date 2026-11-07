import QtQuick
import QtQuick.Layouts
import OpenHU 1.0
import "../lib/qml"

// FM/AM/DAB+ radio (openhu-plugins#40, the structure of the music player): tabs Favorites, FM, AM, DAB+ with the
// stations as square tiles, the mini bar with the station that plays, and the player with the picture (logo or DAB
// slideshow), RDS/DLS, the tuning scale (FM/AM), the controls and the other stations of the band on the right.
// A tab only shows stations; a tap on a tile tunes it (and switches the band). The scale and holding − / + move the
// frequency on the page only; it is tuned when the finger is lifted.
Item {
    id: page

    BusTopic { id: radio; topic: "radio.state" }
    // station logos from logos/ in the plugin data dir: {fm: {"96.2": data URL}, am: {...}, dab: {...}}
    BusTopic { id: logos; topic: "radio.logos" }
    // DAB slideshow picture of the station that plays: {band, station, image}
    BusTopic { id: slide; topic: "radio.slide" }
    // language of the shell: decimal point of the frequencies
    BusTopic { id: language; topic: "ui.language" }

    readonly property var bandIds: ["fm", "am", "dab"]
    readonly property var bandLabels: ({ fm: "FM", am: "AM", dab: "DAB+" })  // untranslated: band names

    readonly property string band: radio.data.band || "fm"
    readonly property bool dab: page.band === "dab"
    readonly property bool am: page.band === "am"
    readonly property var bandInfo: page.infoOf(page.band)
    readonly property var presets: radio.data.presets || []
    readonly property var stations: radio.data.stations || []
    readonly property var rds: radio.data.rds || {}
    readonly property bool playing: radio.data.playing === true
    readonly property bool scanning: radio.data.scanning === true
    readonly property real minimum: radio.data.min || page.bandInfo.min || (page.am ? 531 : 87.5)
    readonly property real maximum: radio.data.max || page.bandInfo.max || (page.am ? 1602 : 108)
    readonly property real step: page.bandInfo.step || (page.am ? 9 : 0.1)
    readonly property string unit: radio.data.unit || (page.am ? "kHz" : "MHz")
    readonly property var frequency: radio.data.frequency === undefined ? null : radio.data.frequency
    readonly property int columns: radio.data.columns || 4
    // touch targets of about 48 px at 800×480 (7"), larger on bigger screens
    readonly property int touch: Math.max(48, Math.round(72 * Theme.scale))

    // 0: Favorites, 1–3: the bands; at the start the band that plays
    property int tab: -1
    readonly property int shownTab: page.tab >= 0 ? page.tab : page.bandIds.indexOf(page.band) + 1
    readonly property string tabBand: page.shownTab > 0 ? page.bandIds[page.shownTab - 1] : ""
    // the player is the main page; the station list lies above it while it is open
    property bool playerOpen: true

    // frequency (FM/AM) or service (DAB) chosen on the page and not tuned yet, or not confirmed by radio.state yet
    property var pending: null
    readonly property var shown: page.pending !== null ? page.pending : page.frequency
    readonly property bool previewing: page.pending !== null && !page.sameKey(page.pending, page.frequency)

    // − / + held: direction and repeats so far
    property int holdDirection: 0
    property int holdRepeats: 0

    function command(cmd, value, band) {
        var data = { cmd: cmd, value: value }
        if (band !== undefined)
            data.band = band
        api.emitEvent("radio.command", data)
    }

    // --- stations of a band ---

    function infoOf(band) {
        return (radio.data.bands || {})[band] || {}
    }

    // key of a frequency in names/logos ("96.2" / "1008" / DAB service id, radiolib.frequency_key)
    function keyIn(band, frequency) {
        if (frequency === undefined || frequency === null)
            return ""
        return band === "dab" ? String(frequency) : band === "am" ? String(Math.round(frequency)) : Number(frequency).toFixed(1)
    }

    function key(frequency) {
        return page.keyIn(page.band, frequency)
    }

    function sameKey(a, b) {
        return a !== null && b !== null && page.key(a) === page.key(b)
    }

    function isCurrent(band, frequency) {
        return band === page.band && page.frequency !== null && page.keyIn(band, frequency) === page.key(page.frequency)
    }

    function formatIn(band, frequency) {
        if (frequency === undefined || frequency === null || band === "dab")
            return ""
        var number = band === "am" ? String(Math.round(frequency))
            : Number(frequency).toFixed(1).replace(".", Qt.locale((language.data || {}).language || "en").decimalPoint)
        return number + " " + (page.infoOf(band).unit || (band === "am" ? "kHz" : "MHz"))
    }

    function formatFrequency(frequency) {
        return page.formatIn(page.band, frequency)
    }

    // remembered RDS name / DAB label; for the station that plays the name it sends now
    function nameIn(band, frequency) {
        var info = page.infoOf(band)
        var key = page.keyIn(band, frequency)
        var name = (info.names || {})[key] || ""
        if (band === "dab")
            name = name || ((info.services || {})[key] || {}).label || ""
        if (page.isCurrent(band, frequency))
            name = (page.rds.ps || "").trim() || name
        return name
    }

    function nameOf(frequency) {
        return page.nameIn(page.band, frequency)
    }

    function logoIn(band, frequency) {
        var slideData = slide.data || {}
        if (band === "dab" && slideData.image && slideData.station === page.keyIn(band, frequency)
                && page.isCurrent(band, frequency))
            return slideData.image
        return ((logos.data || {})[band] || {})[page.keyIn(band, frequency)] || ""
    }

    function logoOf(frequency) {
        return page.logoIn(page.band, frequency)
    }

    // the frequency (FM/AM, when a name is the title) or channel and ensemble (DAB)
    function detailIn(band, frequency) {
        if (band === "dab") {
            var service = (page.infoOf(band).services || {})[page.keyIn(band, frequency)] || {}
            return [service.channel, service.ensembleLabel].filter(function(part) { return part }).join(" · ")
        }
        return page.nameIn(band, frequency) ? page.formatIn(band, frequency) : ""
    }

    function detailOf(frequency) {
        return page.detailIn(page.band, frequency)
    }

    function titleIn(band, frequency) {
        return page.nameIn(band, frequency) || (band === "dab" ? String(frequency) : page.formatIn(band, frequency))
    }

    function presetsIn(band) {
        return band === page.band ? page.presets : page.infoOf(band).presets || []
    }

    function isFavoriteIn(band, frequency) {
        var key = page.keyIn(band, frequency)
        return page.presetsIn(band).some(function(preset) { return page.keyIn(band, preset) === key })
    }

    function isFavorite(frequency) {
        return page.isFavoriteIn(page.band, frequency)
    }

    // the scanned stations and the favorites: FM/AM by frequency, DAB in the order of the station list
    function stationsIn(band) {
        var result = (band === page.band ? page.stations : page.infoOf(band).stations || []).slice()
        page.presetsIn(band).forEach(function(preset) {
            if (!result.some(function(station) { return page.keyIn(band, station) === page.keyIn(band, preset) }))
                result.push(preset)
        })
        if (band !== "dab")
            result.sort(function(a, b) { return a - b })
        return result
    }

    function toggleFavoriteIn(band, frequency) {
        if (frequency === null || frequency === undefined)
            return
        var key = page.keyIn(band, frequency)
        var preset = page.presetsIn(band).find(function(item) { return page.keyIn(band, item) === key })
        if (preset !== undefined)
            page.command("removePreset", preset, band)
        else
            page.command("savePreset", frequency, band)
    }

    function toggleFavorite(frequency) {
        page.toggleFavoriteIn(page.band, frequency)
    }

    function tune(frequency) {
        if (frequency === null)
            return
        page.pending = frequency
        pendingTimeout.restart()
        page.command("tune", frequency)
    }

    // a tile or a row: tunes the station (in its band) and plays it
    function tuneStation(band, frequency) {
        if (band === page.band) {
            page.tune(frequency)
        } else {
            page.pending = null
            page.command("tune", frequency, band)
        }
        if (!page.playing)
            page.command("play")
        page.playerOpen = true
    }

    // the scan of a band: switches to it first
    function scanBand(band) {
        if (page.scanning) {
            page.command("stop")
            return
        }
        page.pending = null
        if (band !== page.band)
            page.command("band", band)
        page.command("scan")
    }

    function seek(direction) {
        page.pending = null
        page.command("seek", direction)
    }

    // the station after value in direction (FM/AM: steps of the raster, wrapping around at the band edges like
    // radiolib.step_frequency; DAB: the station list, then the favorites that are not in it, like neighbour_station)
    function stepFrom(value, direction, steps) {
        if (page.dab) {
            var order = page.stations.slice()
            page.presets.forEach(function(preset) { if (order.indexOf(preset) < 0) order.push(preset) })
            if (order.length === 0)
                return value
            var index = order.indexOf(value)
            if (index < 0)
                index = direction > 0 ? -1 : 0
            return order[(index + direction + order.length) % order.length]
        }
        var frequency = Number(value === null ? page.minimum : value) + direction * page.step * steps
        if (frequency > page.maximum + 1e-6)
            frequency = page.minimum
        else if (frequency < page.minimum - 1e-6)
            frequency = page.maximum
        frequency = page.minimum + Math.round((frequency - page.minimum) / page.step) * page.step
        return page.am ? Math.round(frequency) : Math.round(frequency * 10) / 10
    }

    function startHold(direction) {
        page.holdDirection = direction
        page.holdRepeats = 0
        page.pending = page.stepFrom(page.shown, direction, 1)
        holdTimer.interval = 400
        holdTimer.restart()
    }

    function endHold() {
        if (page.holdDirection === 0)
            return
        holdTimer.stop()
        page.holdDirection = 0
        page.tune(page.pending)
    }

    // repeats while − / + is held: faster after a few, bigger steps after about 1.5 s (DAB: one station each time)
    Timer {
        id: holdTimer
        repeat: true
        onTriggered: {
            page.holdRepeats += 1
            interval = page.dab ? 250 : page.holdRepeats < 4 ? 150 : 80
            page.pending = page.stepFrom(page.shown, page.holdDirection, !page.dab && page.holdRepeats > 12 ? 5 : 1)
        }
    }

    // radio.state confirms the tuned frequency; without it (tune failed, same frequency) the page shows it again
    Timer {
        id: pendingTimeout
        interval: 4000
        onTriggered: {
            if (page.holdDirection === 0 && !player.scaleDragging)
                page.pending = null
        }
    }
    Connections {
        target: radio
        function onDataChanged() {
            if (page.holdDirection === 0 && !player.scaleDragging && page.pending !== null
                    && page.sameKey(page.pending, page.frequency))
                page.pending = null
        }
    }

    // --- what the page shows ---

    readonly property string currentName: page.nameOf(page.shown)
    readonly property string error: radio.data.error || ""
    readonly property bool hasSlide: !!(slide.data || {}).image
    readonly property string radioText: !page.previewing && page.playing ? (page.rds.rt || "").trim() : ""

    // a station as a tile or a row
    function entry(band, frequency, badge) {
        var current = page.isCurrent(band, frequency)
        var text = current && page.playing ? (page.rds.rt || "").trim() : ""
        var favorite = page.isFavoriteIn(band, frequency)
        return {
            band: band,
            key: frequency,
            name: page.nameIn(band, frequency),
            title: page.titleIn(band, frequency),
            detail: page.detailIn(band, frequency),
            text: text,
            logo: page.logoIn(band, frequency),
            favorite: favorite,
            current: current,
            badgeText: badge ? page.bandLabels[band] : "",
            badgeIcon: !badge && favorite ? "heartFilled" : ""
        }
    }

    // the tiles of the tab
    readonly property var tiles: {
        var result = []
        if (page.shownTab === 0) {
            ["fm", "dab", "am"].forEach(function(band) {
                page.presetsIn(band).forEach(function(preset) { result.push(page.entry(band, preset, true)) })
            })
        } else {
            page.stationsIn(page.tabBand).forEach(function(station) { result.push(page.entry(page.tabBand, station, false)) })
        }
        return result
    }

    // the rows of the player: favorites, then the other stations of the band
    readonly property var rows: {
        var result = []
        if (page.presets.length > 0) {
            result.push({ header: qsTrId("org.openhu.radio.main.favorites") })
            page.presets.forEach(function(preset) { result.push(page.entry(page.band, preset, false)) })
        }
        var others = page.stationsIn(page.band).filter(function(station) { return !page.isFavorite(station) })
        if (others.length > 0) {
            result.push({ header: qsTrId("org.openhu.radio.main.all_stations") })
            others.forEach(function(station) { result.push(page.entry(page.band, station, false)) })
        }
        return result
    }

    // hints about the stick or missing programs: [{text, color}]
    function chipsFor(band) {
        var result = []
        // test mode (tools/fake-sdr): internet streams instead of real reception
        if (radio.data.simulated === true)
            result.push({ text: qsTrId("org.openhu.radio.main.simulated_stick"), color: Theme.warning })
        // what RDS / DAB needs and is missing: redsea or openhu-dab (both come with the plugin archive),
        // one of their libraries ("librtlsdr.so.0 (librtlsdr0)"), sox, pacat
        if (band === "fm" && radio.data.rdsMissing)
            result.push({ text: qsTrId("org.openhu.radio.main.rds_missing").arg(radio.data.rdsMissing), color: Theme.textDim })
        if (band === "dab" && radio.data.dabMissing)
            result.push({ text: qsTrId("org.openhu.radio.main.dab_missing").arg(radio.data.dabMissing),
                          color: Qt.color("#ff8a80") })
        return result
    }

    readonly property string scanText: radio.data.scan
        ? qsTrId("org.openhu.radio.main.scanning_channel").arg(radio.data.scan.channel)
            .arg(radio.data.scan.done + 1).arg(radio.data.scan.total).arg(radio.data.scan.found)
        : qsTrId("org.openhu.radio.main.scanning")
    // -1: without known progress
    readonly property real scanProgress: radio.data.scan && radio.data.scan.total ? radio.data.scan.done / radio.data.scan.total : -1

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacing
        anchors.rightMargin: Theme.spacing
        anchors.bottomMargin: Math.round(Theme.spacing * 0.75)
        spacing: Math.round(Theme.spacing * 0.5)

        TabBar {
            Layout.fillWidth: true
            Layout.preferredHeight: page.touch
            touch: page.touch
            labels: [qsTrId("org.openhu.radio.main.tab_favorites"), page.bandLabels.fm, page.bandLabels.am, page.bandLabels.dab]
            currentIndex: page.shownTab
            onClicked: function(index) { page.tab = index }

            IconButton {
                // the scan of the band of the tab (AM has none); the DAB scan takes minutes and can be cancelled
                anchors.verticalCenter: parent.verticalCenter
                visible: page.tabBand === "fm" || page.tabBand === "dab"
                implicitWidth: page.touch
                flat: true
                iconName: page.scanning ? "close" : "scan"
                iconScale: 0.46
                enabled: !page.scanning || page.dab
                Accessible.name: page.scanning ? qsTrId("org.openhu.radio.main.cancel") : qsTrId("org.openhu.radio.main.scan")
                onClicked: page.scanBand(page.tabBand)
            }
            IconButton {
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: page.touch
                flat: true
                iconName: "gear"
                iconScale: 0.46
                Accessible.name: qsTrId("org.openhu.radio.main.settings")
                onClicked: settings.open()
            }
        }

        // the scan and the hints
        Item {
            id: notes
            readonly property var chips: page.chipsFor(page.tabBand || page.band)
            Layout.fillWidth: true
            Layout.preferredHeight: Math.round(Theme.fontSmall * 1.8)
            visible: page.scanning || notes.chips.length > 0

            Text {
                anchors.left: parent.left
                anchors.right: hints.left
                anchors.rightMargin: Theme.spacing
                anchors.verticalCenter: parent.verticalCenter
                visible: page.scanning
                text: page.scanText
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
            Chips {
                id: hints
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                maximumWidth: notes.width * 0.7
                chips: notes.chips
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            StationGrid {
                anchors.fill: parent
                entries: page.tiles
                columns: page.columns
                playing: page.playing
                onActivated: function(entry) { page.tuneStation(entry.band, entry.key) }
                onHeld: function(entry) { page.toggleFavoriteIn(entry.band, entry.key) }
            }

            Text {
                anchors.centerIn: parent
                width: Math.min(parent.width - Theme.spacing * 2, Math.round(620 * Theme.scale))
                visible: page.tiles.length === 0 && !page.scanning
                text: page.shownTab === 0 ? qsTrId("org.openhu.radio.main.no_favorites")
                    : page.tabBand === "am" ? qsTrId("org.openhu.radio.main.no_stations_am")
                    : qsTrId("org.openhu.radio.main.no_stations")
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }
        }

        MiniBar {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(page.touch + Math.round(Theme.spacing * 0.6), Math.round(84 * Theme.scale))
            touch: page.touch
            pictureSource: page.logoOf(page.frequency)
            pictureName: page.nameOf(page.frequency)
            pictureIcon: "radio"
            pictureFit: true
            // DAB before the first station: a hint instead of an empty title
            title: page.frequency === null ? qsTrId("org.openhu.radio.main.choose_station") : page.titleIn(page.band, page.frequency)
            subtitle: page.radioText || (page.playing ? page.bandLabels[page.band]
                : page.bandLabels[page.band] + " · " + qsTrId("org.openhu.radio.main.stopped"))
            subtitleLive: page.radioText !== ""
            playing: page.playing
            playingIcon: "stop"
            progress: page.scanning ? Math.max(0, page.scanProgress) : -1
            previousText: qsTrId("org.openhu.radio.main.previous_station")
            playText: qsTrId("org.openhu.radio.main.play")
            playingText: qsTrId("org.openhu.radio.main.stop")
            nextText: qsTrId("org.openhu.radio.main.next_station")
            onOpened: page.playerOpen = true
            onPreviousClicked: page.seek(-1)
            onToggleClicked: page.command("toggle")
            onNextClicked: page.seek(1)

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: page.dab ? (((page.bandInfo.services || {})[page.key(page.frequency)] || {}).channel || "")
                    : page.formatFrequency(page.frequency)
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall * 0.9
            }
            IconButton {
                readonly property bool favorite: page.isFavorite(page.frequency)
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: page.touch
                flat: true
                iconName: favorite ? "heartFilled" : "heart"
                iconColor: favorite ? "#ff6b81" : Theme.text
                iconScale: 0.46
                enabled: page.frequency !== null
                Accessible.name: qsTrId("org.openhu.radio.main.favorite")
                onClicked: page.toggleFavorite(page.frequency)
            }
        }
    }

    RadioPlayer {
        id: player
        anchors.fill: parent
        visible: page.playerOpen
        z: 10
        page: page
        onListClicked: page.playerOpen = false
    }

    Sheet {
        id: settings
        anchors.fill: parent
        title: qsTrId("org.openhu.radio.main.settings")
        closeText: qsTrId("org.openhu.radio.main.close")

        Text {
            text: qsTrId("org.openhu.radio.main.columns")
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
                    onClicked: page.command("columns", modelData)
                }
            }
        }
    }
}
