import QtQuick
import OpenHU 1.0
import "Music.js" as Music

// The progress across the whole width with both times; drag (or tap) to seek, sought when the finger is lifted
Item {
    id: seek

    property real position: 0
    property real duration: 0
    property real touch: 48
    readonly property bool dragging: area.pressed
    property real dragValue: 0
    readonly property real shown: seek.dragging ? seek.dragValue : seek.position

    signal sought(real seconds)

    implicitHeight: seek.touch + Theme.fontSmall

    function valueAt(x) {
        return seek.duration * Math.max(0, Math.min(1, (x - track.x) / track.width))
    }

    Rectangle {
        id: track
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Math.round(Theme.spacing * 0.5)
        anchors.rightMargin: Math.round(Theme.spacing * 0.5)
        y: Math.round(seek.touch / 2 - height / 2)
        height: Math.max(3, Math.round(5 * Theme.scale))
        radius: height / 2
        color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.3)

        Rectangle {
            height: parent.height
            radius: height / 2
            width: seek.duration > 0 ? parent.width * Math.min(1, seek.shown / seek.duration) : 0
            color: Theme.primary
        }

        Rectangle {
            x: (seek.duration > 0 ? parent.width * Math.min(1, seek.shown / seek.duration) : 0) - width / 2
            anchors.verticalCenter: parent.verticalCenter
            width: Math.round((seek.dragging ? 26 : 18) * Math.max(Theme.scale, 0.75))
            height: width
            radius: width / 2
            color: Theme.text
            visible: seek.duration > 0
        }
    }

    MouseArea {
        id: area
        anchors.left: parent.left
        anchors.right: parent.right
        height: seek.touch
        enabled: seek.duration > 0
        preventStealing: true
        onPressed: function(mouse) { seek.dragValue = seek.valueAt(mouse.x) }
        onPositionChanged: function(mouse) { seek.dragValue = seek.valueAt(mouse.x) }
        onReleased: seek.sought(seek.dragValue)
    }

    Text {
        anchors.left: track.left
        anchors.top: track.bottom
        anchors.topMargin: Math.round(Theme.spacing * 0.5)
        text: Music.time(seek.shown)
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
    }
    Text {
        anchors.right: track.right
        anchors.top: track.bottom
        anchors.topMargin: Math.round(Theme.spacing * 0.5)
        text: Music.time(seek.duration)
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
    }
}
