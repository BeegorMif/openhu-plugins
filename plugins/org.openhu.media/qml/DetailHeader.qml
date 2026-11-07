import QtQuick
import QtQuick.Layouts
import OpenHU 1.0
import "../lib/qml"

// The head of an album, artist or playlist page: back, the cover (or mosaic), title, subtitle, number of tracks and
// length, then Play, Shuffle and Add to playlist (own playlists also Rename and Delete through "more")
Item {
    id: header

    property var covers: []
    property string kind
    property string title
    property string subtitle
    property string info
    property bool own: false
    property real touch: 48

    signal backClicked()
    signal playClicked()
    signal shuffleClicked()
    signal addClicked()
    signal moreClicked()

    implicitHeight: Math.max(cover.height, details.implicitHeight) + Theme.spacing * 0.75

    IconButton {
        id: back
        anchors.left: parent.left
        anchors.top: parent.top
        implicitWidth: header.touch
        flat: true
        iconName: "back"
        iconScale: 0.5
        Accessible.name: qsTrId("org.openhu.media.main.back")
        onClicked: header.backClicked()
    }

    Mosaic {
        id: cover
        anchors.left: back.right
        anchors.top: parent.top
        anchors.leftMargin: Math.round(Theme.spacing * 0.25)
        width: Math.round(Math.max(header.touch * 2.4, Math.min(header.width * 0.2, 200 * Theme.scale)))
        height: width
        covers: header.covers
        name: header.title
        icon: header.kind === "artist" ? "microphone" : header.kind === "playlist" ? "playlist" : "disc"
    }

    ColumnLayout {
        id: details
        anchors.left: cover.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: Theme.spacing
        spacing: Math.round(Theme.spacing * 0.2)

        Text {
            Layout.fillWidth: true
            text: header.title
            color: Theme.text
            font.pixelSize: Math.round(Theme.fontLarge * 0.95)
            font.weight: Font.Medium
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: header.subtitle
            color: Qt.lighter(Theme.primary, 1.25)
            font.pixelSize: Theme.fontNormal * 0.9
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: header.info
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            elide: Text.ElideRight
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: Math.round(Theme.spacing * 0.4)
            spacing: Math.round(Theme.spacing * 0.5)

            PillButton {
                touch: header.touch
                primary: true
                iconName: "play"
                text: qsTrId("org.openhu.media.main.play")
                onClicked: header.playClicked()
            }
            PillButton {
                touch: header.touch
                iconName: "shuffle"
                text: qsTrId("org.openhu.media.main.shuffle")
                onClicked: header.shuffleClicked()
            }
            PillButton {
                touch: header.touch
                iconName: "playlistAdd"
                text: qsTrId("org.openhu.media.main.add_to_playlist")
                onClicked: header.addClicked()
            }
            IconButton {
                visible: header.own
                implicitWidth: header.touch
                iconName: "edit"
                iconScale: 0.42
                Accessible.name: qsTrId("org.openhu.media.main.rename")
                onClicked: header.moreClicked()
            }
        }
    }
}
