import QtQuick
import OpenHU 1.0
import "../lib/qml"
import "../lib/qml/Placeholder.js" as Placeholder

// The player: a back chevron and the hints; on the left the picture (logo or DAB slideshow), frequency or channel,
// name, radio text (or an error) and badges; on the right the stations of the band (favorites first); at the
// bottom the tuning scale across the whole width (FM/AM) and, centred, heart, −, previous, play/stop, next, + and
// scan. page: Main.qml (state and functions of the radio).
Item {
    id: player

    property var page
    readonly property bool scaleDragging: tuningScale.dragging
    readonly property bool dab: player.page.dab
    readonly property bool am: player.page.am

    signal backClicked()

    // taps do not go through to the overview below
    MouseArea { anchors.fill: parent }

    Backdrop {
        anchors.fill: parent
        source: player.page.logoOf(player.page.frequency)
        tint: player.page.currentName ? Placeholder.color(player.page.currentName) : Theme.background
    }

    IconButton {
        id: back
        x: Math.round(Theme.spacing * 0.5)
        y: Math.round(Theme.spacing * 0.25)
        implicitWidth: player.page.touch
        flat: true
        iconName: "back"
        iconScale: 0.5
        Accessible.name: qsTrId("org.openhu.radio.main.back")
        onClicked: player.backClicked()
    }

    Chips {
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacing * 1.25
        anchors.verticalCenter: back.verticalCenter
        maximumWidth: player.width * 0.6
        chips: player.page.chipsFor(player.page.band)
    }

    Item {
        id: area
        anchors.top: back.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: tuningScale.visible ? tuningScale.top : controls.top
        anchors.leftMargin: Theme.spacing * 1.25
        anchors.rightMargin: Theme.spacing * 1.25
        anchors.bottomMargin: Math.round(Theme.spacing * 0.5)

        Artwork {
            id: picture
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            height: Math.min(parent.height, Math.round(parent.width * 0.3))
            width: height
            source: player.page.logoOf(player.page.shown)
            name: player.page.currentName
            icon: "radio"
            fit: true
            opacity: !player.page.playing && !player.page.previewing ? 0.6 : 1
        }

        Column {
            anchors.left: picture.right
            anchors.right: stations.left
            anchors.leftMargin: Theme.spacing
            anchors.rightMargin: Theme.spacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Math.round(Theme.spacing * 0.3)

            readonly property var shown: player.page.shown

            Text {
                width: parent.width
                visible: text !== ""
                text: player.dab ? player.page.detailOf(parent.shown)
                    : player.page.currentName ? player.page.formatFrequency(parent.shown)
                    : player.page.bandLabels[player.page.band]
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                // DAB before the first station: a hint instead of an empty title
                text: parent.shown === null ? qsTrId("org.openhu.radio.main.choose_station")
                    : player.page.currentName || (player.dab ? String(parent.shown) : player.page.formatFrequency(parent.shown))
                color: !player.page.playing && !player.page.previewing ? Theme.textDim : Theme.text
                font.pixelSize: Math.round(Theme.fontLarge * 1.15)
                font.weight: Font.Medium
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                readonly property string error: player.page.previewing ? "" : player.page.error
                width: parent.width
                visible: text !== ""
                text: error || player.page.radioText
                color: error ? "#ff8a80" : Qt.lighter(Theme.primary, 1.25)
                font.pixelSize: Theme.fontNormal
                wrapMode: Text.Wrap
                maximumLineCount: 3
                elide: Text.ElideRight
            }
            Row {
                topPadding: Math.round(Theme.spacing * 0.2)
                spacing: Theme.spacing / 2
                readonly property var badges: {
                    if (player.page.previewing || !player.page.playing)
                        return []
                    if (player.dab)
                        return player.page.logoOf(player.page.frequency) && player.page.hasSlide ? ["DAB+", "Slideshow"] : ["DAB+"]  // untranslated: technical names
                    return player.page.rds.pi || player.page.rds.ps ? ["RDS"] : []  // untranslated: technical name
                }
                visible: badges.length > 0

                Repeater {
                    model: parent.badges

                    Rectangle {
                        id: badge
                        required property string modelData
                        width: badgeText.implicitWidth + Theme.spacing
                        height: badgeText.implicitHeight + Theme.spacing / 4
                        radius: Math.round(4 * Theme.scale)
                        color: "transparent"
                        border.color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.4)
                        border.width: 1

                        Text {
                            id: badgeText
                            anchors.centerIn: parent
                            text: badge.modelData
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                }
            }
        }

        StationList {
            id: stations
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.round(parent.width * 0.4)
            touch: player.page.touch
            title: qsTrId("org.openhu.radio.main.band_stations").arg(player.page.bandLabels[player.page.band])
            entries: player.page.rows
            playing: player.page.playing
            scanning: player.page.scanning
            scanProgress: player.page.scanProgress
            scanText: player.page.scanText
            emptyText: player.page.scanning ? "" : player.am ? qsTrId("org.openhu.radio.main.no_stations_am")
                : qsTrId("org.openhu.radio.main.no_stations")
            onTuneRequested: function(key) { player.page.tuneStation(player.page.band, key) }
            onFavoriteToggled: function(key) { player.page.toggleFavorite(key) }
        }
    }

    TuningScale {
        id: tuningScale
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: controls.top
        anchors.leftMargin: Theme.spacing * 1.25
        anchors.rightMargin: Theme.spacing * 1.25
        anchors.bottomMargin: Math.round(Theme.spacing * 0.5)
        visible: !player.dab
        minimum: player.page.minimum
        maximum: player.page.maximum
        step: player.page.step
        majorStep: player.am ? 200 : 2
        minorStep: player.am ? 100 : 0.5
        value: player.page.shown === null ? player.page.minimum : Number(player.page.shown)
        onMoved: function(value) { player.page.pending = value }
        onChosen: function(value) { player.page.tune(value) }
    }

    Row {
        id: controls
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Math.round(Theme.spacing)
        spacing: Math.round(Theme.spacing * 0.9)

        IconButton {
            readonly property bool favorite: player.page.isFavorite(player.page.frequency)
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: player.page.touch
            flat: true
            iconName: favorite ? "heartFilled" : "heart"
            iconColor: favorite ? "#ff6b81" : Theme.text
            iconScale: 0.48
            enabled: player.page.frequency !== null
            Accessible.name: qsTrId("org.openhu.radio.main.favorite")
            onClicked: player.page.toggleFavorite(player.page.frequency)
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            visible: !player.dab
            implicitWidth: player.page.touch
            iconName: "minus"
            iconScale: 0.48
            Accessible.name: qsTrId("org.openhu.radio.main.step_down")
            onPressed: player.page.startHold(-1)
            onReleased: player.page.endHold()
            onCanceled: player.page.endHold()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.page.touch * 1.15)
            iconName: "previous"
            Accessible.name: qsTrId("org.openhu.radio.main.previous_station")
            onClicked: player.page.seek(-1)
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.page.touch * 1.45)
            color: Theme.primary
            iconColor: Theme.primaryText
            iconName: player.page.playing ? "stop" : "play"
            enabled: !player.page.scanning
            Accessible.name: player.page.playing ? qsTrId("org.openhu.radio.main.stop") : qsTrId("org.openhu.radio.main.play")
            onClicked: player.page.command("toggle")
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.page.touch * 1.15)
            iconName: "next"
            Accessible.name: qsTrId("org.openhu.radio.main.next_station")
            onClicked: player.page.seek(1)
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            visible: !player.dab
            implicitWidth: player.page.touch
            iconName: "plus"
            iconScale: 0.48
            Accessible.name: qsTrId("org.openhu.radio.main.step_up")
            onPressed: player.page.startHold(1)
            onReleased: player.page.endHold()
            onCanceled: player.page.endHold()
        }
        // AM has no scan: the space keeps play/stop in the centre
        Item {
            width: player.page.touch
            height: player.page.touch
            visible: player.am
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            visible: !player.am
            implicitWidth: player.page.touch
            flat: true
            iconName: player.page.scanning ? "close" : "scan"
            iconScale: 0.48
            enabled: !player.page.scanning || player.dab
            Accessible.name: player.page.scanning ? qsTrId("org.openhu.radio.main.cancel") : qsTrId("org.openhu.radio.main.scan")
            onClicked: player.page.scanBand(player.page.band)
        }
    }
}
