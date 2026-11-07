import QtQuick
import OpenHU 1.0

// The bar at the bottom of an overview (music library, radio stations): picture, title and subtitle on the left,
// previous / play / next exactly in the centre, the page's own items on the right (the default property: time and
// mode, frequency and heart), a thin progress line along the bottom edge. A tap beside the buttons opens the player.
Rectangle {
    id: bar

    property string pictureSource
    property string pictureName
    property string pictureIcon: "note"
    property bool pictureFit: false
    property string title
    property string subtitle
    // the subtitle in the accent colour (radio text)
    property bool subtitleLive: false
    property bool playing: false
    // icon of the middle button while playing: "pause" (music) or "stop" (radio)
    property string playingIcon: "pause"
    // 0–1, below 0: no progress line
    property real progress: -1
    property real touch: 48
    // accessible names of the buttons
    property string previousText
    property string playText
    property string playingText
    property string nextText
    default property alias trailing: right.data

    signal opened()
    signal previousClicked()
    signal toggleClicked()
    signal nextClicked()

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
        source: bar.pictureSource
        name: bar.pictureName
        icon: bar.pictureIcon
        fit: bar.pictureFit
    }

    Column {
        anchors.left: cover.right
        anchors.right: controls.left
        anchors.leftMargin: Theme.spacing * 0.6
        anchors.rightMargin: Theme.spacing * 0.6
        anchors.verticalCenter: parent.verticalCenter

        Text {
            width: parent.width
            text: bar.title
            color: Theme.text
            font.pixelSize: Theme.fontNormal * 0.9
            font.weight: Font.Medium
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: bar.subtitle
            color: bar.subtitleLive ? Qt.lighter(Theme.primary, 1.25) : Theme.textDim
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
            Accessible.name: bar.previousText
            onClicked: bar.previousClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            color: Theme.primary
            iconColor: Theme.primaryText
            iconName: bar.playing ? bar.playingIcon : "play"
            iconScale: 0.46
            Accessible.name: bar.playing ? bar.playingText : bar.playText
            onClicked: bar.toggleClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: bar.touch
            flat: true
            iconName: "next"
            iconScale: 0.46
            Accessible.name: bar.nextText
            onClicked: bar.nextClicked()
        }
    }

    Row {
        id: right
        anchors.right: parent.right
        anchors.rightMargin: Math.round(Theme.spacing * 0.5)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Math.round(Theme.spacing * 0.3)
    }

    // progress
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: bar.progress >= 0
        height: Math.max(2, Math.round(3 * Theme.scale))
        color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.25)

        Rectangle {
            height: parent.height
            width: parent.width * Math.max(0, Math.min(1, bar.progress))
            color: Theme.primary
        }
    }
}
