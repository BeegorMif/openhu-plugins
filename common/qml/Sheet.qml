import QtQuick
import OpenHU 1.0

// A small modal card over the page (settings, the menu of a long press, playlists): a tap beside it closes it.
// nearTop: near the top edge (room for the on-screen keyboard below a text field)
Item {
    id: sheet

    property string title
    property bool shown: false
    property bool nearTop: false
    // accessible name of the close button
    property string closeText
    property real cardWidth: Math.min(sheet.width - Theme.spacing * 2, Math.round(560 * Theme.scale))
    default property alias content: body.data

    signal closed()

    function open() { sheet.shown = true }
    function close() {
        if (sheet.shown) {
            sheet.shown = false
            sheet.closed()
        }
    }

    visible: opacity > 0
    opacity: sheet.shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 140 } }
    z: 20

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)

        MouseArea {
            anchors.fill: parent
            onClicked: sheet.close()
        }
    }

    Rectangle {
        id: card
        width: sheet.cardWidth
        height: Math.min(sheet.height - Theme.spacing * 2, header.height + body.implicitHeight + Theme.spacing * 1.5)
        anchors.horizontalCenter: parent.horizontalCenter
        y: sheet.nearTop ? Theme.spacing : Math.round((sheet.height - height) / 2)
        radius: Theme.radius
        color: Theme.surface
        border.color: Theme.outline
        border.width: 1

        // taps on the card stay on it
        MouseArea { anchors.fill: parent }

        Item {
            id: header
            width: parent.width
            height: sheet.title !== "" ? Math.round(Theme.fontNormal * 2.6) : Theme.spacing / 2

            Text {
                anchors.left: parent.left
                anchors.right: closeButton.left
                anchors.leftMargin: Theme.spacing
                anchors.verticalCenter: parent.verticalCenter
                text: sheet.title
                color: Theme.text
                font.pixelSize: Theme.fontNormal
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            IconButton {
                id: closeButton
                visible: sheet.title !== ""
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: Math.max(44, Math.round(64 * Theme.scale))
                flat: true
                iconName: "close"
                iconScale: 0.4
                Accessible.name: sheet.closeText
                onClicked: sheet.close()
            }
        }

        Flickable {
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: Theme.spacing * 0.75
            anchors.topMargin: 0
            contentHeight: body.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: body
                width: parent.width
                spacing: Math.round(Theme.spacing * 0.5)
            }
        }
    }
}
