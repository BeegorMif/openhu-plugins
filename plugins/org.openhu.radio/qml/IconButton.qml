import QtQuick
import QtQuick.Controls
import OpenHU 1.0

// Round touch button with an icon (Icons.js); flat: no background until pressed
AbstractButton {
    id: button

    property string iconName
    property color iconColor: Theme.text
    property color color: Qt.rgba(Theme.surfaceHigh.r, Theme.surfaceHigh.g, Theme.surfaceHigh.b, 0.85)
    property bool flat: false
    property real iconScale: 0.42

    implicitWidth: Math.round(64 * Theme.scale)
    implicitHeight: implicitWidth
    opacity: enabled ? 1 : 0.4
    focusPolicy: Qt.NoFocus

    background: Rectangle {
        radius: width / 2
        color: button.flat ? "transparent" : button.color

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Theme.text
            opacity: button.down ? 0.14 : 0
        }
    }

    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            width: Math.round(button.width * button.iconScale)
            height: width
            name: button.iconName
            color: button.iconColor
        }
    }
}
