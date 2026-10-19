import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0
import "Placeholder.js" as Placeholder

// FM/AM/DAB+ radio (openhu-plugins#36): band tabs, the station that plays (logo or DAB slideshow, RDS/DLS) over a
// soft background from its picture, a tuning scale (FM/AM), transport buttons and the station list with favorites.
// The scale and holding − / + move the frequency on the page only; it is tuned when the finger is lifted.
Item {
    id: page

    BusTopic { id: radio; topic: "radio.state" }
    // station logos from logos/ in the plugin data dir: {fm: {"96.2": data URL}, am: {...}, dab: {...}}
    BusTopic { id: logos; topic: "radio.logos" }
    // DAB slideshow picture of the station that plays: {band, station, image}
    BusTopic { id: slide; topic: "radio.slide" }
    // language of the shell: decimal point of the frequencies
    BusTopic { id: language; topic: "ui.language" }

    readonly property string band: radio.data.band || "fm"
    readonly property bool dab: page.band === "dab"
    readonly property bool am: page.band === "am"
    readonly property var bandInfo: (radio.data.bands || {})[page.band] || {}
    readonly property var names: page.bandInfo.names || {}
    readonly property var services: page.bandInfo.services || {}
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

    // frequency (FM/AM) or service (DAB) chosen on the page and not tuned yet, or not confirmed by radio.state yet
    property var pending: null
    readonly property var shown: page.pending !== null ? page.pending : page.frequency
    readonly property bool previewing: page.pending !== null && !page.sameKey(page.pending, page.frequency)

    // − / + held: direction and repeats so far
    property int holdDirection: 0
    property int holdRepeats: 0

    function command(cmd, value) {
        api.emitEvent("radio.command", { cmd: cmd, value: value })
    }

    // key of a frequency in names/logos ("96.2" / "1008" / DAB service id, radiolib.frequency_key)
    function key(frequency) {
        if (frequency === undefined || frequency === null)
            return ""
        return page.dab ? String(frequency) : page.am ? String(Math.round(frequency)) : Number(frequency).toFixed(1)
    }

    function sameKey(a, b) {
        return a !== null && b !== null && page.key(a) === page.key(b)
    }

    function formatFrequency(frequency) {
        if (frequency === undefined || frequency === null || page.dab)
            return ""
        var number = page.am ? String(Math.round(frequency))
            : Number(frequency).toFixed(1).replace(".", Qt.locale((language.data || {}).language || "en").decimalPoint)
        return number + " " + page.unit
    }

    // remembered RDS name / DAB label; for the station that plays the name it sends now
    function nameOf(frequency) {
        var name = page.names[page.key(frequency)] || ""
        if (page.dab)
            name = name || (page.services[page.key(frequency)] || {}).label || ""
        if (page.sameKey(frequency, page.frequency))
            name = (page.rds.ps || "").trim() || name
        return name
    }

    function logoOf(frequency) {
        var slideData = slide.data || {}
        if (page.dab && slideData.image && slideData.station === page.key(frequency)
                && page.sameKey(frequency, page.frequency))
            return slideData.image
        return ((logos.data || {})[page.band] || {})[page.key(frequency)] || ""
    }

    // second line in the list: frequency (FM/AM, when a name is the title) or channel and ensemble (DAB)
    function detailOf(frequency) {
        if (page.dab) {
            var service = page.services[page.key(frequency)] || {}
            return [service.channel, service.ensembleLabel].filter(function(part) { return part }).join(" · ")
        }
        return page.nameOf(frequency) ? page.formatFrequency(frequency) : ""
    }

    function isFavorite(frequency) {
        return page.presets.some(function(preset) { return page.sameKey(preset, frequency) })
    }

    function toggleFavorite(frequency) {
        if (frequency === null)
            return
        var preset = page.presets.find(function(item) { return page.sameKey(item, frequency) })
        if (preset !== undefined)
            page.command("removePreset", preset)
        else
            page.command("savePreset", frequency)
    }

    function tune(frequency) {
        if (frequency === null)
            return
        page.pending = frequency
        pendingTimeout.restart()
        page.command("tune", frequency)
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
            if (page.holdDirection === 0 && !tuningScale.dragging)
                page.pending = null
        }
    }
    Connections {
        target: radio
        function onDataChanged() {
            if (page.holdDirection === 0 && !tuningScale.dragging && page.pending !== null
                    && page.sameKey(page.pending, page.frequency))
                page.pending = null
        }
    }

    readonly property string currentName: page.nameOf(page.shown)

    readonly property var entries: {
        var current = page.frequency
        function entry(frequency) {
            var name = page.nameOf(frequency)
            return {
                key: frequency,
                name: name,
                title: name || page.formatFrequency(frequency),
                detail: page.detailOf(frequency),
                text: page.sameKey(frequency, current) ? (page.rds.rt || "").trim() : "",
                logo: page.logoOf(frequency),
                favorite: page.isFavorite(frequency),
                current: page.sameKey(frequency, current)
            }
        }
        var result = []
        if (page.presets.length > 0) {
            result.push({ header: qsTrId("org.openhu.radio.main.favorites") })
            page.presets.forEach(function(preset) { result.push(entry(preset)) })
        }
        var others = page.stations.filter(function(station) { return !page.isFavorite(station) })
        if (others.length > 0) {
            result.push({ header: qsTrId("org.openhu.radio.main.all_stations") })
            others.forEach(function(station) { result.push(entry(station)) })
        }
        return result
    }

    Backdrop {
        anchors.fill: parent
        source: page.logoOf(page.frequency)
        tint: page.currentName ? Placeholder.color(page.currentName) : Theme.background
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacing * 1.25
        anchors.rightMargin: Theme.spacing * 1.25
        anchors.bottomMargin: Theme.spacing * 1.25
        spacing: Theme.spacing

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacing

            // Band
            Row {
                id: tabs
                Layout.fillWidth: true
                readonly property var items: [{ band: "fm", label: "FM" }, { band: "am", label: "AM" }, { band: "dab", label: "DAB+" }]  // untranslated: band names

                Repeater {
                    model: tabs.items

                    AbstractButton {
                        id: tab
                        required property var modelData
                        readonly property bool selected: page.band === tab.modelData.band
                        width: tabs.width / tabs.items.length
                        height: Math.round(Theme.fontNormal * 3)
                        focusPolicy: Qt.NoFocus
                        onClicked: {
                            page.pending = null
                            page.command("band", tab.modelData.band)
                        }

                        contentItem: Text {
                            text: tab.modelData.label
                            color: tab.selected ? Theme.text : Theme.textDim
                            font.pixelSize: Theme.fontLarge * 0.8
                            font.weight: Font.Medium
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
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
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: parent.width
                                height: Math.max(3, Math.round(4 * Theme.scale))
                                color: Theme.primary
                                visible: tab.selected
                            }
                            Rectangle {
                                anchors.fill: parent
                                color: Theme.text
                                opacity: tab.down ? 0.06 : 0
                            }
                        }
                    }
                }
            }

            NowPlayingCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                logo: page.logoOf(page.shown)
                name: page.currentName
                overline: page.dab ? page.detailOf(page.shown)
                    : page.currentName ? page.formatFrequency(page.shown)
                    : page.am ? "AM" : "FM"  // untranslated: band names
                // DAB before the first station: a hint instead of an empty title
                title: page.shown === null ? qsTrId("org.openhu.radio.main.choose_station")
                    : page.currentName || (page.dab ? String(page.shown) : page.formatFrequency(page.shown))
                text: !page.previewing && page.playing ? (page.rds.rt || "").trim() : ""
                error: page.previewing ? "" : radio.data.error || ""
                dimmed: !page.playing && !page.previewing
                badges: {
                    if (page.previewing || !page.playing)
                        return []
                    if (page.dab)
                        return page.logoOf(page.frequency) && (slide.data || {}).image ? ["DAB+", "Slideshow"] : ["DAB+"]  // untranslated: technical names
                    return page.rds.pi || page.rds.ps ? ["RDS"] : []  // untranslated: technical name
                }
                chips: {
                    var result = []
                    // test mode (tools/fake-sdr): internet streams instead of real reception
                    if (radio.data.simulated === true)
                        result.push({ text: qsTrId("org.openhu.radio.main.simulated_stick"), color: Theme.warning })
                    // what RDS / DAB needs and is missing: redsea or openhu-dab (both come with the plugin archive),
                    // one of their libraries ("librtlsdr.so.0 (librtlsdr0)"), sox, pacat
                    if (!page.dab && !page.am && radio.data.rdsMissing)
                        result.push({ text: qsTrId("org.openhu.radio.main.rds_missing").arg(radio.data.rdsMissing),
                                      color: Theme.textDim })
                    if (page.dab && radio.data.dabMissing)
                        result.push({ text: qsTrId("org.openhu.radio.main.dab_missing").arg(radio.data.dabMissing),
                                      color: Qt.color("#ff8a80") })
                    return result
                }
            }

            TuningScale {
                id: tuningScale
                Layout.fillWidth: true
                Layout.leftMargin: Theme.spacing
                Layout.rightMargin: Theme.spacing
                visible: !page.dab
                minimum: page.minimum
                maximum: page.maximum
                step: page.step
                majorStep: page.am ? 200 : 2
                minorStep: page.am ? 100 : 0.5
                value: page.shown === null ? page.minimum : Number(page.shown)
                onMoved: function(value) { page.pending = value }
                onChosen: function(value) { page.tune(value) }
            }

            // Controls
            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.spacing * 1.25

                IconButton {
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "previous"
                    Accessible.name: qsTrId("org.openhu.radio.main.previous_station")
                    onClicked: {
                        page.pending = null
                        page.command("seek", -1)
                    }
                }
                IconButton {
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "minus"
                    Accessible.name: qsTrId("org.openhu.radio.main.step_down")
                    onPressed: page.startHold(-1)
                    onReleased: page.endHold()
                    onCanceled: page.endHold()
                }
                IconButton {
                    // the DAB scan takes minutes and can be cancelled
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: Math.round(88 * Theme.scale)
                    color: Theme.primary
                    iconColor: Theme.primaryText
                    iconName: page.scanning || page.playing ? "stop" : "play"
                    enabled: !page.scanning || page.dab
                    Accessible.name: page.scanning ? qsTrId("org.openhu.radio.main.cancel")
                        : page.playing ? qsTrId("org.openhu.radio.main.stop") : qsTrId("org.openhu.radio.main.play")
                    onClicked: page.command(page.scanning ? "stop" : "toggle")
                }
                IconButton {
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "plus"
                    Accessible.name: qsTrId("org.openhu.radio.main.step_up")
                    onPressed: page.startHold(1)
                    onReleased: page.endHold()
                    onCanceled: page.endHold()
                }
                IconButton {
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "next"
                    Accessible.name: qsTrId("org.openhu.radio.main.next_station")
                    onClicked: {
                        page.pending = null
                        page.command("seek", 1)
                    }
                }
                IconButton {
                    readonly property bool favorite: page.isFavorite(page.frequency)
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: favorite ? "heartFilled" : "heart"
                    iconColor: favorite ? "#ff6b81" : Theme.text
                    enabled: page.frequency !== null
                    Accessible.name: qsTrId("org.openhu.radio.main.favorite")
                    onClicked: page.toggleFavorite(page.frequency)
                }
            }
        }

        StationList {
            Layout.preferredWidth: Math.round(page.width * 0.32)
            Layout.fillHeight: true
            Layout.topMargin: Theme.spacing
            entries: page.entries
            playing: page.playing
            scanAvailable: !page.am
            scanning: page.scanning
            canCancel: page.dab
            scanProgress: radio.data.scan && radio.data.scan.total ? radio.data.scan.done / radio.data.scan.total : -1
            scanText: radio.data.scan
                ? qsTrId("org.openhu.radio.main.scanning_channel").arg(radio.data.scan.channel)
                    .arg(radio.data.scan.done + 1).arg(radio.data.scan.total).arg(radio.data.scan.found)
                : qsTrId("org.openhu.radio.main.scanning")
            emptyText: page.scanning ? "" : page.am ? qsTrId("org.openhu.radio.main.no_stations_am") : qsTrId("org.openhu.radio.main.no_stations")
            onTuneRequested: function(key) { page.tune(key) }
            onFavoriteToggled: function(key) { page.toggleFavorite(key) }
            onScanRequested: page.command("scan")
            onCancelRequested: page.command("stop")
        }
    }
}
