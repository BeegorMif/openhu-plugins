import QtQuick
import QtQuick.Controls
import OpenHU 1.0
import "../lib/qml"

// An entry of a sheet: icon and text over the whole width, at least one touch target high
AbstractButton {
    id: entry

    property string iconName
    property real touch: 48
    property color textColor: Theme.text
    property bool selected: false

    width: parent ? parent.width : implicitWidth
    implicitHeight: entry.touch
    focusPolicy: Qt.NoFocus
    opacity: enabled ? 1 : 0.4

    background: Rectangle {
        radius: Theme.radius / 2
        color: entry.selected ? Theme.selected : entry.down ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
    }

    contentItem: Item {
        Icon {
            id: icon
            anchors.left: parent.left
            anchors.leftMargin: Theme.spacing * 0.5
            anchors.verticalCenter: parent.verticalCenter
            visible: entry.iconName !== ""
            width: Math.round(Theme.fontNormal * 1.2)
            height: width
            name: entry.iconName
            color: entry.textColor
        }
        Text {
            anchors.left: icon.visible ? icon.right : parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.spacing * 0.75
            anchors.verticalCenter: parent.verticalCenter
            text: entry.text
            color: entry.textColor
            font.pixelSize: Theme.fontNormal * 0.9
            elide: Text.ElideRight
        }
    }
}
