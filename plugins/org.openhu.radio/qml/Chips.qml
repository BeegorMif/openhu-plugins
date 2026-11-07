import QtQuick
import OpenHU 1.0

// Hints in a row (simulated stick, a missing RDS or DAB decoder): chips [{text, color}], the longest elided
Row {
    id: row

    property var chips: []
    property real maximumWidth: 400

    spacing: Math.round(Theme.spacing / 3)
    layoutDirection: Qt.RightToLeft

    Repeater {
        model: row.chips

        Rectangle {
            id: chip
            required property var modelData
            width: Math.min(chipText.implicitWidth + Theme.spacing * 1.25, row.maximumWidth / Math.max(1, row.chips.length))
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
