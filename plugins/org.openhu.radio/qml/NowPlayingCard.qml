import QtQuick
import QtQuick.Layouts
import OpenHU 1.0

// The station that plays: picture, frequency or channel line, name, radio text (or an error) and badges; hints
// about the stick or missing programs as chips in the corner
Rectangle {
    id: card

    property string logo
    property string name
    property string overline
    property string title
    property string text
    property string error
    property bool dimmed: false
    property var badges: []
    // [{text, color}]
    property var chips: []

    radius: Theme.radius
    color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.55)

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.25
        spacing: Theme.spacing * 1.5

        Artwork {
            Layout.preferredHeight: Math.min(card.height - Theme.spacing * 2.5, Math.round(220 * Theme.scale))
            Layout.preferredWidth: Layout.preferredHeight
            Layout.alignment: Qt.AlignVCenter
            source: card.logo
            name: card.name
            opacity: card.dimmed ? 0.6 : 1
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.spacing / 3

            Text {
                Layout.fillWidth: true
                visible: text !== ""
                text: card.overline
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: card.title
                color: card.dimmed ? Theme.textDim : Theme.text
                font.pixelSize: Math.round(Theme.fontLarge * 1.7)
                font.weight: Font.Medium
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: text !== ""
                text: card.error || card.text
                color: card.error ? "#ff8a80" : Qt.lighter(Theme.primary, 1.25)
                font.pixelSize: Theme.fontNormal
                elide: card.error ? Text.ElideNone : Text.ElideRight
                wrapMode: card.error ? Text.Wrap : Text.NoWrap
                maximumLineCount: 2
            }
            Row {
                Layout.topMargin: Theme.spacing / 3
                visible: card.badges.length > 0
                spacing: Theme.spacing / 2

                Repeater {
                    model: card.badges

                    Rectangle {
                        id: badge
                        required property string modelData
                        width: badgeText.implicitWidth + Theme.spacing
                        height: badgeText.implicitHeight + Theme.spacing / 4
                        radius: Math.round(4 * Theme.scale)
                        color: "transparent"
                        border.color: Qt.rgba(Theme.textDim.r, Theme.textDim.g, Theme.textDim.b, 0.4)
                        border.width: 1

                        Text {
                            id: badgeText
                            anchors.centerIn: parent
                            text: badge.modelData
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                }
            }
        }
    }

    Column {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.spacing * 0.75
        spacing: Theme.spacing / 3

        Repeater {
            model: card.chips

            Rectangle {
                id: chip
                required property var modelData
                anchors.right: parent.right
                width: Math.min(chipText.implicitWidth + Theme.spacing * 1.25, card.width * 0.6)
                height: chipText.implicitHeight + Theme.spacing / 3
                radius: height / 2
                color: Qt.rgba(chip.modelData.color.r, chip.modelData.color.g, chip.modelData.color.b, 0.16)

                Text {
                    id: chipText
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, parent.width - Theme.spacing * 1.25)
                    text: chip.modelData.text
                    color: chip.modelData.color
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                }
            }
        }
    }
}
