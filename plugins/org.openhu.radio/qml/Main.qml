import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// FM/AM/DAB+ radio: frequency or DAB service, RDS/DLS, station logo or DAB slideshow, seek/step, presets and
// scanned stations.
Item {
    id: page

    BusTopic { id: radio; topic: "radio.state" }
    // station logos from logos/ in the plugin data dir: {fm: {"96.2": data URL}, am: {...}}
    BusTopic { id: logos; topic: "radio.logos" }

    // DAB slideshow picture of the station that plays: {band, station, image}
    BusTopic { id: slide; topic: "radio.slide" }
    // language of the shell: decimal point of the frequencies
    BusTopic { id: language; topic: "ui.language" }

    readonly property string band: radio.data.band || "fm"
    readonly property bool fm: page.band === "fm"
    readonly property bool dab: page.band === "dab"
    // key of the current frequency in radio.logos ("96.2" / "1008" / DAB service id, radiolib.frequency_key)
    readonly property string frequencyKey: radio.data.frequency === undefined || radio.data.frequency === null ? ""
        : page.dab ? String(radio.data.frequency)
        : page.fm ? Number(radio.data.frequency).toFixed(1) : String(Math.round(radio.data.frequency))
    readonly property string slideImage: page.dab && (slide.data || {}).station === page.frequencyKey
        ? ((slide.data || {}).image || "") : ""
    readonly property string logo: page.slideImage
        || ((logos.data || {})[page.band] || {})[page.frequencyKey] || ""
    readonly property var dabNames: ((radio.data.bands || {}).dab || {}).names || {}

    function command(cmd, value) {
        api.emitEvent("radio.command", { cmd: cmd, value: value })
    }

    function format(frequency) {
        if (frequency === undefined || frequency === null)
            return "–"
        if (page.dab)
            return page.dabNames[frequency] || String(frequency)
        return page.fm ? Number(frequency).toFixed(1).replace(".", Qt.locale((language.data || {}).language || "en").decimalPoint)
                       : String(frequency)
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
                model: [{ band: "fm", label: "FM" }, { band: "am", label: "AM" }, { band: "dab", label: "DAB+" }]  // untranslated: band names
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
                text: qsTrId("org.openhu.radio.main.simulated_stick")
                color: "#ffb74d"
                font.pixelSize: Theme.fontSmall
            }
            // what RDS / DAB needs and is missing: redsea or openhu-dab (both come with the plugin archive), one of
            // their libraries ("librtlsdr.so.0 (librtlsdr0)"), sox, pacat
            Text {
                visible: page.fm && !!radio.data.rdsMissing
                text: qsTrId("org.openhu.radio.main.rds_missing").arg(radio.data.rdsMissing || "")
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
            Text {
                visible: page.dab && !!radio.data.dabMissing
                text: qsTrId("org.openhu.radio.main.dab_missing").arg(radio.data.dabMissing || "")
                color: "#ff8a80"
                font.pixelSize: Theme.fontSmall
            }
        }

        // Frequency and RDS
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.fontHuge * 2.3
            radius: Theme.radius
            color: Theme.surface

            Image {
                id: logoImage
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacing
                height: parent.height - Theme.spacing * 2
                width: height
                visible: page.logo !== ""
                source: page.logo
                sourceSize.width: width
                sourceSize.height: height
                fillMode: Image.PreserveAspectFit
                opacity: radio.data.playing ? 1 : 0.6
            }

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
                        // DAB: the channel of the ensemble instead of a unit
                        text: page.dab ? ((((radio.data.bands || {}).dab || {}).services || {})[page.frequencyKey]
                                          || {}).channel || ""
                            : radio.data.unit || "MHz"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontLarge
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: radio.data.scanning ? (radio.data.scan
                            ? qsTrId("org.openhu.radio.main.scanning_channel").arg(radio.data.scan.channel)
                                .arg(radio.data.scan.done + 1).arg(radio.data.scan.total).arg(radio.data.scan.found)
                            : qsTrId("org.openhu.radio.main.scanning"))
                        : radio.data.error ? radio.data.error
                        : [radio.data.rds && radio.data.rds.ps, radio.data.rds && radio.data.rds.rt]
                            .filter(function(part) { return part }).join(" · ")
                    color: radio.data.error ? "#ff8a80" : Theme.primary
                    font.pixelSize: Theme.fontNormal
                    elide: Text.ElideRight
                    // centred: room for the logo on both sides
                    width: Math.min(implicitWidth, page.width - Theme.spacing * 6
                                    - (logoImage.visible ? (logoImage.width + Theme.spacing) * 2 : 0))
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
                // the DAB scan takes minutes and can be cancelled
                text: radio.data.scanning ? qsTrId("org.openhu.radio.main.cancel") : radio.data.playing ? qsTrId("org.openhu.radio.main.stop")
                    : qsTrId("org.openhu.radio.main.play")
                highlighted: true
                font.pixelSize: Theme.fontNormal
                Layout.preferredWidth: Theme.dockWidth * 1.8
                enabled: !radio.data.scanning || page.dab
                onClicked: page.command(radio.data.scanning ? "stop" : "toggle")
            }
            Button { text: "+"; font.pixelSize: Theme.fontLarge; onClicked: page.command("step", 1) }
            Button { text: "▶▶"; font.pixelSize: Theme.fontNormal; onClicked: page.command("seek", 1) }
            Button { text: "★"; font.pixelSize: Theme.fontLarge; onClicked: page.command("savePreset") }
            Button {
                text: qsTrId("org.openhu.radio.main.scan")
                visible: page.fm || page.dab
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
                text: page.fm || page.dab ? qsTrId("org.openhu.radio.main.no_stations") : ""
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
            }
        }
    }
}
