import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// FM/AM radio: frequency, RDS, seek/step, presets and scanned stations.
Item {
    id: page

    BusTopic { id: radio; topic: "radio.state" }

    readonly property bool fm: radio.data.band !== "am"

    function command(cmd, value) {
        api.emitEvent("radio.command", { cmd: cmd, value: value })
    }

    function format(frequency) {
        if (frequency === undefined)
            return "–"
        return page.fm ? Number(frequency).toFixed(1).replace(".", ",") : String(frequency)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Band
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            Repeater {
                model: [{ band: "fm", label: "FM" }, { band: "am", label: "AM" }]
                Button {
                    text: modelData.label
                    checkable: true
                    checked: (radio.data.band || "fm") === modelData.band
                    onClicked: page.command("band", modelData.band)
                }
            }
            Item { Layout.fillWidth: true }
            // Test mode (tools/fake-sdr): internet streams instead of real reception
            Text {
                visible: radio.data.simulated === true
                text: "Simulierter Stick"
                color: "#ffb74d"
                font.pixelSize: Theme.fontSmall
            }
            Text {
                visible: !radio.data.rdsAvailable && page.fm
                text: "RDS: redsea nicht installiert"
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }

        // Frequency and RDS
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.fontHuge * 2.3
            radius: Theme.radius
            color: Theme.surface

            Column {
                anchors.centerIn: parent
                spacing: Theme.spacing / 3

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: Theme.spacing / 2
                    Text {
                        text: page.format(radio.data.frequency)
                        color: radio.data.playing ? Theme.text : Theme.textDim
                        font.pixelSize: Theme.fontHuge
                        font.weight: Font.Light
                    }
                    Text {
                        anchors.baseline: parent.children[0].baseline
                        text: radio.data.unit || "MHz"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontLarge
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: radio.data.scanning ? "Sendersuche …"
                        : radio.data.error ? radio.data.error
                        : [radio.data.rds && radio.data.rds.ps, radio.data.rds && radio.data.rds.rt]
                            .filter(function(part) { return part }).join(" · ")
                    color: radio.data.error ? "#ff8a80" : Theme.primary
                    font.pixelSize: Theme.fontNormal
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, page.width - Theme.spacing * 6)
                }
            }
        }

        // Controls
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.spacing

            Button { text: "◀◀"; font.pixelSize: Theme.fontNormal; onClicked: page.command("seek", -1) }
            Button { text: "−"; font.pixelSize: Theme.fontLarge; onClicked: page.command("step", -1) }
            Button {
                text: radio.data.playing ? "Stopp" : "Abspielen"
                highlighted: true
                font.pixelSize: Theme.fontNormal
                Layout.preferredWidth: Theme.dockWidth * 1.8
                enabled: !radio.data.scanning
                onClicked: page.command("toggle")
            }
            Button { text: "+"; font.pixelSize: Theme.fontLarge; onClicked: page.command("step", 1) }
            Button { text: "▶▶"; font.pixelSize: Theme.fontNormal; onClicked: page.command("seek", 1) }
            Button { text: "★"; font.pixelSize: Theme.fontLarge; onClicked: page.command("savePreset") }
            Button {
                text: "Suchlauf"
                visible: page.fm
                enabled: !radio.data.scanning
                onClicked: page.command("scan")
            }
        }

        // Presets (hold to remove)
        Flow {
            Layout.fillWidth: true
            spacing: Theme.spacing / 2
            visible: (radio.data.presets || []).length > 0

            Repeater {
                model: radio.data.presets || []
                Button {
                    text: "★ " + page.format(modelData)
                    highlighted: modelData === radio.data.frequency
                    onClicked: page.command("tune", modelData)
                    onPressAndHold: page.command("removePreset", modelData)
                }
            }
        }

        // Scanned stations
        GridView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            cellWidth: Theme.dockWidth * 1.3
            cellHeight: Theme.fontNormal * 2.6
            model: radio.data.stations || []
            delegate: Button {
                width: GridView.view.cellWidth - Theme.spacing / 2
                text: page.format(modelData)
                flat: modelData !== radio.data.frequency
                onClicked: page.command("tune", modelData)
            }

            Text {
                anchors.centerIn: parent
                visible: parent.count === 0
                text: page.fm ? "Noch keine Sender – Suchlauf starten" : ""
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
            }
        }
    }
}
