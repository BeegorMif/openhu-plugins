import QtQuick
import OpenHU 1.0
import "Music.js" as Music

// A tile of the library grid: a square picture (cover or mosaic), a small round badge with what it is (top left),
// the marker of the track that plays (top right), an optional label (Own, M3U, ...) and two caption lines.
// The same size in every tab. Tap: open/play, long press: the menu.
Item {
    id: tile

    property var covers: []
    property string title
    property string subtitle
    property string kind
    property string placeholderIcon: "note"
    property string label
    property bool playing: false
    property bool dimmed: false
    // the "New playlist" tile: a plus instead of a picture
    property bool create: false

    signal clicked()
    signal held()

    readonly property real side: width

    Item {
        id: picture
        width: tile.side
        height: tile.side
        scale: area.pressed ? 0.96 : 1
        Behavior on scale { NumberAnimation { duration: 90 } }

        Mosaic {
            anchors.fill: parent
            visible: !tile.create
            covers: tile.covers
            name: tile.placeholderIcon === "folder" ? "" : tile.title
            icon: tile.placeholderIcon
            dimmed: tile.dimmed
        }

        Rectangle {
            anchors.fill: parent
            visible: tile.create
            radius: Math.max(3, Math.round(width / 28))
            color: Qt.rgba(Theme.surfaceHigh.r, Theme.surfaceHigh.g, Theme.surfaceHigh.b, 0.6)
            border.color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.35)
            border.width: Math.max(1, Math.round(2 * Theme.scale))

            Icon {
                anchors.centerIn: parent
                width: Math.round(parent.width * 0.3)
                height: width
                name: "plus"
                color: Theme.textDim
            }
        }

        // what the tile is
        Rectangle {
            visible: !tile.create && tile.kind !== ""
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: Math.round(tile.side * 0.05)
            width: Math.max(20, Math.round(tile.side * 0.17))
            height: width
            radius: width / 2
            color: Qt.rgba(0, 0, 0, 0.55)

            Icon {
                anchors.centerIn: parent
                width: Math.round(parent.width * 0.62)
                height: width
                name: Music.badgeIcon(tile.kind)
                color: "#ffffff"
            }
        }

        // the track that plays is in it
        Rectangle {
            visible: tile.playing
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Math.round(tile.side * 0.05)
            width: Math.max(20, Math.round(tile.side * 0.17))
            height: width
            radius: width / 2
            color: Theme.primary

            Icon {
                anchors.centerIn: parent
                width: Math.round(parent.width * 0.6)
                height: width
                name: "onAir"
                color: Theme.primaryText
            }
        }

        // Own, M3U, PLS, XSPF
        Rectangle {
            visible: tile.label !== ""
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Math.round(tile.side * 0.05)
            width: labelText.implicitWidth + Theme.spacing * 0.6
            height: labelText.implicitHeight + Theme.spacing * 0.2
            radius: height / 2
            color: Qt.rgba(0, 0, 0, 0.6)

            Text {
                id: labelText
                anchors.centerIn: parent
                text: tile.label
                color: "#ffffff"
                font.pixelSize: Math.max(11, Math.round(Theme.fontSmall * 0.8))
                font.weight: Font.Medium
            }
        }
    }

    Column {
        anchors.top: picture.bottom
        anchors.topMargin: Math.round(Theme.spacing * 0.4)
        width: tile.side

        Text {
            width: parent.width
            text: tile.title
            color: tile.playing ? Qt.lighter(Theme.primary, 1.25) : tile.dimmed ? Theme.textDim : Theme.text
            font.pixelSize: Theme.fontNormal * 0.85
            font.weight: Font.Medium
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: tile.subtitle
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall * 0.9
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        pressAndHoldInterval: 500
        onClicked: tile.clicked()
        onPressAndHold: tile.held()
    }
}
