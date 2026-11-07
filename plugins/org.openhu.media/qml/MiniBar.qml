import QtQuick
import OpenHU 1.0
import "Music.js" as Music

// The bar at the bottom of the library: cover, title and artist on the left, previous / play-pause / next exactly
// in the centre, the mode and the time on the right, a thin progress line along the bottom edge. A tap beside the
// buttons opens the player.
Rectangle {
    id: bar

    property var track: ({})
    property bool playing: false
    property real position: 0
    property real duration: 0
    property string mode: "order"
    property string unknownArtist
    property real touch: 48

    signal opened()
    signal previousClicked()
    signal toggleClicked()
    signal nextClicked()
    signal modeClicked()

    radius: Theme.radius
    color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.85)
    clip: true

    MouseArea {
        anchors.fill: parent
        onClicked: bar.opened()
    }

    Artwork {
        id: cover
        anchors.left: parent.left
        anchors.leftMargin: Math.round(Theme.spacing * 0.5)
        anchors.verticalCenter: parent.verticalCenter
        height: Math.round(bar.height * 0.74)
        width: height
        source: bar.track.cover || ""
        name: bar.track.title || ""
    }

    Column {
        anchors.left: cover.right
        anchors.right: controls.left
        anchors.leftMargin: Theme.spacing * 0.6
        anchors.rightMargin: Theme.spacing * 0.6
        anchors.verticalCenter: parent.verticalCenter

        Text {
            width: parent.width
            text: bar.track.title || ""
            color: Theme.text
            font.pixelSize: Theme.fontNormal * 0.9
            font.weight: Font.Medium
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: bar.track.artist || bar.unknownArtist
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall * 0.9
            elide: Text.ElideRight
        }
    }

    Row {
        id: controls
        anchors.centerIn: parent
        spacing: Math.round(Theme.spacing * 0.25)

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            flat: true
            iconName: "previous"
            iconScale: 0.46
            Accessible.name: qsTrId("org.openhu.media.main.previous")
            onClicked: bar.previousClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            color: Theme.primary
            iconColor: Theme.primaryText
            iconName: bar.playing ? "pause" : "play"
            iconScale: 0.46
            Accessible.name: bar.playing ? qsTrId("org.openhu.media.main.pause") : qsTrId("org.openhu.media.main.play")
            onClicked: bar.toggleClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            flat: true
            iconName: "next"
            iconScale: 0.46
            Accessible.name: qsTrId("org.openhu.media.main.next")
            onClicked: bar.nextClicked()
        }
    }

    Row {
        id: right
        anchors.right: parent.right
        anchors.rightMargin: Math.round(Theme.spacing * 0.5)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Math.round(Theme.spacing * 0.3)

        Text {
            anchors.verticalCenter: parent.verticalCenter
            // the width of the longest time, so the bar does not jump
            width: Math.ceil(timeMetrics.width)
            horizontalAlignment: Text.AlignRight
            text: Music.time(bar.position) + " / " + Music.time(bar.duration)  // untranslated: times
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall * 0.9
            font.features: { "tnum": 1 }

            TextMetrics {
                id: timeMetrics
                font.pixelSize: Theme.fontSmall * 0.9
                text: bar.duration >= 3600 ? "00:00:00 / 00:00:00" : "00:00 / 00:00"  // untranslated: width of a time
            }
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            flat: true
            iconName: Music.modeIcon(bar.mode)
            iconColor: bar.mode === "order" ? Theme.text : Qt.lighter(Theme.primary, 1.25)
            iconScale: 0.46
            Accessible.name: qsTrId("org.openhu.media.main.mode")
            onClicked: bar.modeClicked()
        }
    }

    // progress
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.max(2, Math.round(3 * Theme.scale))
        color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.25)

        Rectangle {
            height: parent.height
            width: bar.duration > 0 ? parent.width * Math.min(1, bar.position / bar.duration) : 0
            color: Theme.primary
        }
    }
}
