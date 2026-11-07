import QtQuick
import OpenHU 1.0
import "../lib/qml"
import "Music.js" as Music
import "../lib/qml/Placeholder.js" as Placeholder

// The player: a back chevron; on the left the cover, title, artist and source; on the right "Up next" (tap: play
// it now, drag the handle: reorder, long press: the menu); at the bottom the seek bar across the whole width and,
// centred, mode, previous, play/pause, next and repeat.
Item {
    id: player

    property var track: ({})
    property bool playing: false
    property real position: 0
    property real duration: 0
    property string mode: "order"
    property string repeat: "off"
    property var upNext: []
    property string sourceText
    property string unknownArtist
    property real touch: 48

    signal backClicked()
    signal previousClicked()
    signal toggleClicked()
    signal nextClicked()
    signal modeClicked()
    signal repeatClicked()
    signal sought(real seconds)
    signal jumped(int key)
    signal entryMoved(int key, int to)
    signal entryHeld(var entry)

    // taps do not go through to the library below
    MouseArea { anchors.fill: parent }

    Backdrop {
        anchors.fill: parent
        source: player.track.cover || ""
        tint: player.track.title ? Placeholder.color(player.track.title) : Theme.background
    }

    IconButton {
        id: back
        x: Math.round(Theme.spacing * 0.5)
        y: Math.round(Theme.spacing * 0.25)
        implicitWidth: player.touch
        flat: true
        iconName: "back"
        iconScale: 0.5
        Accessible.name: qsTrId("org.openhu.media.main.back")
        onClicked: player.backClicked()
    }

    Item {
        id: area
        anchors.top: back.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: seekBar.top
        anchors.leftMargin: Theme.spacing * 1.25
        anchors.rightMargin: Theme.spacing * 1.25
        anchors.bottomMargin: Math.round(Theme.spacing * 0.25)

        Artwork {
            id: cover
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            height: Math.min(parent.height, Math.round(parent.width * 0.3))
            width: height
            source: player.track.cover || ""
            name: player.track.title || ""
        }

        Column {
            anchors.left: cover.right
            anchors.right: queueCard.left
            anchors.leftMargin: Theme.spacing
            anchors.rightMargin: Theme.spacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Math.round(Theme.spacing * 0.3)

            Text {
                width: parent.width
                text: player.track.title || ""
                color: Theme.text
                font.pixelSize: Math.round(Theme.fontLarge * 1.15)
                font.weight: Font.Medium
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: player.track.artist || player.unknownArtist
                color: Qt.lighter(Theme.primary, 1.25)
                font.pixelSize: Theme.fontNormal
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: player.track.album || ""
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
            Row {
                spacing: Math.round(Theme.spacing * 0.35)
                visible: player.sourceText !== ""

                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.round(Theme.fontSmall * 1.1)
                    height: width
                    name: player.track.sourceKind === "usb" ? "usb" : player.track.sourceKind === "local" ? "headUnit" : "folder"
                    color: Theme.textDim
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: player.sourceText
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        Rectangle {
            id: queueCard
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: Math.round(parent.width * 0.4)
            radius: Theme.radius
            color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.6)

            Text {
                id: queueTitle
                x: Theme.spacing
                y: Math.round(Theme.spacing * 0.5)
                text: qsTrId("org.openhu.media.main.up_next")
                color: Theme.text
                font.pixelSize: Theme.fontNormal * 0.9
                font.weight: Font.Medium
            }

            ListView {
                id: queueList
                anchors.top: queueTitle.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: Math.round(Theme.spacing * 0.35)
                clip: true
                model: player.upNext
                boundsBehavior: Flickable.StopAtBounds
                interactive: true

                // with repeat the entries after the end of the list (repeat: true) follow below "Then again"
                delegate: Column {
                    id: entry
                    required property var modelData
                    required property int index
                    readonly property bool repeat: entry.modelData.repeat === true
                    width: ListView.view.width
                    // a dragged row above its neighbours
                    z: track.dragOffset !== 0 ? 2 : 0

                    Row {
                        visible: entry.repeat && (entry.index === 0 || player.upNext[entry.index - 1].repeat !== true)
                        height: Math.round(Theme.fontSmall * 2.2)
                        leftPadding: Math.round(Theme.spacing * 0.65)
                        spacing: Math.round(Theme.spacing * 0.4)

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.round(Theme.fontSmall * 1.2)
                            height: width
                            name: "repeat"
                            color: Theme.textDim
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTrId("org.openhu.media.main.up_next_again")
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                    TrackRow {
                        id: track
                        width: parent.width
                        touch: player.touch
                        title: entry.modelData.title || ""
                        subtitle: entry.modelData.artist || ""
                        cover: entry.modelData.cover || ""
                        duration: entry.modelData.duration || 0
                        available: entry.modelData.available !== false
                        // moving only within this pass of the list
                        draggable: !entry.repeat
                        onClicked: player.jumped(entry.modelData.key)
                        onHeld: player.entryHeld(entry.modelData)
                        onMoved: function(steps) {
                            player.entryMoved(entry.modelData.key, Math.max(0, entry.index + steps))
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: parent.width - Theme.spacing * 2
                    visible: queueList.count === 0
                    text: qsTrId("org.openhu.media.main.nothing_next")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }

    SeekBar {
        id: seekBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: controls.top
        anchors.leftMargin: Theme.spacing
        anchors.rightMargin: Theme.spacing
        touch: player.touch
        position: player.position
        duration: player.duration
        onSought: function(seconds) { player.sought(seconds) }
    }

    Row {
        id: controls
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Math.round(Theme.spacing)
        spacing: Math.round(Theme.spacing * 0.9)

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: player.touch
            flat: player.mode === "order"
            color: Theme.selected
            iconName: Music.modeIcon(player.mode)
            iconColor: player.mode === "order" ? Theme.text : Qt.lighter(Theme.primary, 1.25)
            iconScale: 0.48
            Accessible.name: qsTrId("org.openhu.media.main.mode")
            onClicked: player.modeClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.touch * 1.15)
            iconName: "previous"
            Accessible.name: qsTrId("org.openhu.media.main.previous")
            onClicked: player.previousClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.touch * 1.45)
            color: Theme.primary
            iconColor: Theme.primaryText
            iconName: player.playing ? "pause" : "play"
            Accessible.name: player.playing ? qsTrId("org.openhu.media.main.pause") : qsTrId("org.openhu.media.main.play")
            onClicked: player.toggleClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: Math.round(player.touch * 1.15)
            iconName: "next"
            Accessible.name: qsTrId("org.openhu.media.main.next")
            onClicked: player.nextClicked()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: player.touch
            flat: player.repeat === "off"
            color: Theme.selected
            iconName: Music.repeatIcon(player.repeat)
            iconColor: player.repeat === "off" ? Theme.text : Qt.lighter(Theme.primary, 1.25)
            iconScale: 0.48
            Accessible.name: qsTrId("org.openhu.media.main.repeat")
            onClicked: player.repeatClicked()
        }
    }
}
