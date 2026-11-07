import QtQuick
import OpenHU 1.0
import "Music.js" as Music

// A track as a row (album and playlist pages, files of a folder, "Up next"): number or small cover, title, artist,
// length, the marker while it plays; dimmed when it is not there (a stick that is not plugged in). Tap: play,
// long press: the menu. With draggable a handle on the right moves it up or down (moved(steps)).
Item {
    id: row

    property string title
    property string subtitle
    property string cover
    property int number: 0
    property bool showCover: true
    property real duration: 0
    property bool playing: false
    property bool available: true
    property bool draggable: false
    property real touch: 48

    signal clicked()
    signal held()
    signal moved(int steps)

    // while the handle is dragged: the offset of the row
    property real dragOffset: 0
    z: row.dragOffset !== 0 ? 2 : 0

    height: Math.max(row.touch, Math.round(Theme.fontNormal * 3))

    Rectangle {
        id: body
        width: parent.width
        height: parent.height
        y: row.dragOffset
        radius: Theme.radius / 2
        color: row.dragOffset !== 0 ? Theme.surfaceHigh
            : row.playing ? Theme.selected : area.pressed ? Qt.rgba(1, 1, 1, 0.06) : "transparent"

        MouseArea {
            id: area
            anchors.fill: parent
            pressAndHoldInterval: 500
            onClicked: row.clicked()
            onPressAndHold: row.held()
        }

        Item {
            id: lead
            anchors.left: parent.left
            anchors.leftMargin: Theme.spacing / 2
            anchors.verticalCenter: parent.verticalCenter
            height: Math.round(parent.height * 0.74)
            width: height

            Artwork {
                anchors.fill: parent
                visible: row.showCover
                source: row.cover
                name: row.title
                opacity: row.available ? 1 : 0.45
            }
            Text {
                anchors.centerIn: parent
                visible: !row.showCover && !row.playing
                text: row.number > 0 ? String(row.number) : ""
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal * 0.9
            }
            Icon {
                anchors.centerIn: parent
                visible: !row.showCover && row.playing
                width: Math.round(parent.width * 0.55)
                height: width
                name: "onAir"
                color: Qt.lighter(Theme.primary, 1.25)
            }
        }

        Column {
            anchors.left: lead.right
            anchors.right: time.left
            anchors.leftMargin: Theme.spacing * 0.75
            anchors.rightMargin: Theme.spacing / 2
            anchors.verticalCenter: parent.verticalCenter

            Text {
                width: parent.width
                text: row.title
                color: row.playing ? Qt.lighter(Theme.primary, 1.25) : row.available ? Theme.text : Theme.textDim
                font.pixelSize: Theme.fontNormal * 0.9
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: row.subtitle
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall * 0.9
                elide: Text.ElideRight
            }
        }

        Text {
            id: time
            anchors.right: handle.visible ? handle.left : parent.right
            anchors.rightMargin: handle.visible ? 0 : Theme.spacing * 0.75
            anchors.verticalCenter: parent.verticalCenter
            text: row.duration > 0 ? Music.time(row.duration) : ""
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }

        Item {
            id: handle
            visible: row.draggable
            anchors.right: parent.right
            width: row.touch
            height: parent.height

            Icon {
                anchors.centerIn: parent
                width: Math.round(Theme.fontNormal * 1.1)
                height: width
                name: "drag"
                color: Theme.textDim
            }

            MouseArea {
                id: dragArea
                anchors.fill: parent
                preventStealing: true
                property real startY: 0
                onPressed: function(mouse) { dragArea.startY = mapToItem(row, mouse.x, mouse.y).y - row.dragOffset }
                onPositionChanged: function(mouse) { row.dragOffset = mapToItem(row, mouse.x, mouse.y).y - dragArea.startY }
                onReleased: {
                    var steps = Math.round(row.dragOffset / row.height)
                    row.dragOffset = 0
                    if (steps !== 0)
                        row.moved(steps)
                }
                onCanceled: row.dragOffset = 0
            }
        }
    }
}
