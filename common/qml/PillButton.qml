import QtQuick
import QtQuick.Controls
import OpenHU 1.0

// A rounded button with an icon and a text (Play, Shuffle, Play folder, the sort chips); primary: the accent colour,
// checked: a selected chip
AbstractButton {
    id: button

    property string iconName
    property bool primary: false
    property real touch: 48

    implicitHeight: button.touch
    implicitWidth: content.implicitWidth + Theme.spacing * 1.6
    focusPolicy: Qt.NoFocus
    opacity: enabled ? 1 : 0.4

    background: Rectangle {
        radius: height / 2
        color: button.primary ? Theme.primary
            : button.checked ? Theme.selected : Qt.rgba(Theme.surfaceHigh.r, Theme.surfaceHigh.g, Theme.surfaceHigh.b, 0.85)
        border.width: button.checked ? Math.max(1, Math.round(2 * Theme.scale)) : 0
        border.color: Theme.primary

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.text
            opacity: button.down ? 0.14 : 0
        }
    }

    contentItem: Item {
        Row {
            id: content
            anchors.centerIn: parent
            spacing: Math.round(Theme.spacing * 0.4)

            Icon {
                visible: button.iconName !== ""
                anchors.verticalCenter: parent.verticalCenter
                width: Math.round(Theme.fontNormal * 1.1)
                height: width
                name: button.iconName
                color: button.primary ? Theme.primaryText : Theme.text
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: button.text
                color: button.primary ? Theme.primaryText : Theme.text
                font.pixelSize: Theme.fontNormal * 0.85
                font.weight: Font.Medium
            }
        }
    }
}
