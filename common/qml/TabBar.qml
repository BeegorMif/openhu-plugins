import QtQuick
import QtQuick.Controls
import OpenHU 1.0

// Tabs of equal width with an underline under the selected one; the page's own buttons (scan, gear) on the right
// (the default property). clicked(index) also comes when the selected tab is tapped again.
Item {
    id: bar

    property var labels: []
    property int currentIndex: 0
    property real touch: 48
    default property alias trailing: buttons.data

    signal clicked(int index)

    implicitHeight: bar.touch

    Row {
        id: tabs
        anchors.left: parent.left
        anchors.right: buttons.left
        height: parent.height

        Repeater {
            model: bar.labels

            AbstractButton {
                id: tabButton
                required property string modelData
                required property int index
                readonly property bool selected: bar.currentIndex === tabButton.index
                width: tabs.width / Math.max(1, bar.labels.length)
                height: tabs.height
                focusPolicy: Qt.NoFocus
                onClicked: bar.clicked(tabButton.index)

                contentItem: Text {
                    text: tabButton.modelData
                    color: tabButton.selected ? Theme.text : Theme.textDim
                    font.pixelSize: Math.round(Theme.fontLarge * 0.68)
                    font.weight: Font.Medium
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Item {
                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: 1
                        color: Theme.textDim
                        opacity: 0.25
                    }
                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: Math.max(3, Math.round(4 * Theme.scale))
                        color: Theme.primary
                        visible: tabButton.selected
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: Theme.text
                        opacity: tabButton.down ? 0.06 : 0
                    }
                }
            }
        }
    }

    Row {
        id: buttons
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
    }
}
