import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// Digital instrument cluster. Prefer the public vehicle.* topics, fall back to decoded can.*
// topics so the display also works when org.openhu.vehicle is not installed.
Item {
    id: page

    property var values: ({})
    property var canState: ({})
    property var monitor: ({})

    function updateTopic(topic, data) {
        if (topic === "can.state") {
            canState = data || ({})
            return
        }
        if (topic === "can.monitor") {
            monitor = data || ({})
            return
        }
        var copy = Object.assign({}, values)
        copy[topic] = data || ({})
        values = copy
    }

    function dataFor(name) {
        var vehicle = values["vehicle." + name]
        if (vehicle && vehicle.available !== false && Object.keys(vehicle).length)
            return vehicle
        return values["can." + name] || ({})
    }

    function field(name, key, fallback) {
        var data = dataFor(name)
        if (data.available === false || data[key] === undefined || data[key] === null)
            return fallback
        return data[key]
    }

    function shown(value, decimals) {
        if (value === undefined || value === null || value === "")
            return "—"
        var number = Number(value)
        return isNaN(number) ? String(value) : number.toLocaleString(Qt.locale(), "f", decimals === undefined ? 0 : decimals)
    }

    function onOff(value) {
        if (value === undefined || value === null)
            return "—"
        return value ? qsTrId("org.beegor.cluster.main.on") : qsTrId("org.beegor.cluster.main.off")
    }

    function refreshTopics() {
        var topics = api.request("bus.topics").result || []
        for (var i = 0; i < topics.length; ++i) {
            var topic = topics[i]
            if (topic.indexOf("vehicle.") === 0 || topic.indexOf("can.") === 0)
                updateTopic(topic, eventBus.last(topic))
        }
    }

    Component.onCompleted: refreshTopics()

    Connections {
        target: eventBus
        function onEvent(topic, data) {
            if (topic.indexOf("vehicle.") === 0 || topic.indexOf("can.") === 0)
                page.updateTopic(topic, data)
        }
    }

    component Panel: Rectangle {
        radius: Theme.radius
        color: Theme.surface
        border.width: 1
        border.color: Theme.textDim
        opacity: 0.98
    }

    component PanelTitle: Text {
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        font.bold: true
        font.letterSpacing: 1
        text: ""
    }

    component ValueText: Text {
        color: Theme.text
        font.pixelSize: Theme.fontLarge
        font.bold: true
        text: "—"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Header: connection state, selected profile and CAN frame rate.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            Rectangle {
                Layout.preferredWidth: Theme.spacing
                Layout.preferredHeight: Theme.spacing
                radius: width / 2
                color: page.canState.connected ? Theme.success : "#ff8a80"
            }

            Text {
                Layout.fillWidth: true
                text: page.canState.connected
                      ? qsTrId("org.beegor.cluster.main.connected")
                      : qsTrId("org.beegor.cluster.main.disconnected")
                color: Theme.text
                font.pixelSize: Theme.fontNormal
                elide: Text.ElideRight
            }

            Text {
                visible: !!page.canState.profileName
                text: qsTrId("org.beegor.cluster.main.profile").arg(page.canState.profileName || "")
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }

            Text {
                visible: page.canState.connected
                text: qsTrId("org.beegor.cluster.main.frames").arg(page.canState.framesPerSecond || 0)
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }

        // Main driving instruments.
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacing

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1.15

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing * 2
                    spacing: Theme.spacing / 2

                    PanelTitle {
                        Layout.fillWidth: true
                        text: qsTrId("org.beegor.cluster.main.speed")
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: Theme.spacing

                        Text {
                            text: shown(field("speed", "mph", field("speed", "kmh", null)))
                            color: Theme.text
                            font.pixelSize: Math.min(Theme.fontExtraLarge * 3.0, parent.height * 0.9)
                            font.bold: true
                            font.family: "monospace"
                            verticalAlignment: Text.AlignVCenter
                        }

                        ColumnLayout {
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 0
                            Text {
                                text: field("speed", "kmh", null) !== null ? "km/h" : "mph" // untranslated: unit
                                color: Theme.textDim
                                font.pixelSize: Theme.fontNormal
                            }
                            Text {
                                text: qsTrId("org.beegor.cluster.main.speed")
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: page.canState.connected
                              ? qsTrId("org.beegor.cluster.main.available")
                              : qsTrId("org.beegor.cluster.main.waiting")
                        color: page.canState.connected ? Theme.success : Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing * 2
                    spacing: Theme.spacing

                    PanelTitle {
                        Layout.fillWidth: true
                        text: qsTrId("org.beegor.cluster.main.rpm")
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacing

                        ValueText {
                            text: shown(field("engine", "rpm", null))
                            font.pixelSize: Theme.fontExtraLarge * 1.7
                            font.family: "monospace"
                        }

                        Text {
                            text: "RPM" // untranslated: standard unit
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                    }

                    // Segmented tachometer bar; a conservative 7,000 rpm scale.
                    Row {
                        Layout.fillWidth: true
                        spacing: Theme.spacing / 3
                        Repeater {
                            model: 28
                            Rectangle {
                                required property int index
                                width: (parent.width - (27 * Theme.spacing / 3)) / 28
                                height: Theme.spacing * 2.4
                                radius: Theme.radius / 3
                                color: {
                                    var rpm = Number(field("engine", "rpm", 0))
                                    var lit = rpm > index * 250
                                    if (!lit)
                                        return Theme.textDim
                                    return index >= 24 ? "#ff625d" : index >= 20 ? "#ffb74d" : Theme.success
                                }
                                opacity: Number(field("engine", "rpm", null)) === null ? 0.25 : 1.0
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text: qsTrId("org.beegor.cluster.main.outside_temperature")
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                        Item { Layout.fillWidth: true }
                        ValueText {
                            text: shown(field("climate", "outsideTemp", null), 1) + " °C"
                            font.pixelSize: Theme.fontNormal
                        }
                    }
                }
            }
        }

        // Vehicle info strip.
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.spacing * 10
            spacing: Theme.spacing

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing
                    spacing: Theme.spacing / 3
                    PanelTitle { Layout.fillWidth: true; text: qsTrId("org.beegor.cluster.main.climate") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.cabin_temperature"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: shown(field("climate", "temperatureC", null), 1) + " °C"; font.pixelSize: Theme.fontNormal }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.fan"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: shown(field("climate", "fanSpeed", null)); font.pixelSize: Theme.fontNormal }
                    }
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing
                    spacing: Theme.spacing / 3
                    PanelTitle { Layout.fillWidth: true; text: qsTrId("org.beegor.cluster.main.fuel") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.range"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: shown(field("fuel", "rangeMiles", field("fuel", "rangeKm", null))) + " mi"; font.pixelSize: Theme.fontNormal }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.odometer"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: shown(field("odometer", "odometerMiles", field("odometer", "odometerKm", null))); font.pixelSize: Theme.fontNormal }
                    }
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing
                    spacing: Theme.spacing / 3
                    PanelTitle { Layout.fillWidth: true; text: qsTrId("org.beegor.cluster.main.vehicle_status") }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.ignition"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: onOff(field("ignition", "terminal15", null)); font.pixelSize: Theme.fontNormal }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: qsTrId("org.beegor.cluster.main.lights"); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                        Item { Layout.fillWidth: true }
                        ValueText { text: onOff(field("lights", "dipBeam", null)); font.pixelSize: Theme.fontNormal }
                    }
                }
            }
        }

        // Raw monitor is read-only. The CAN plugin publishes frames only when its Monitor option is enabled.
        Panel {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.spacing * 7

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacing
                spacing: Theme.spacing / 3

                RowLayout {
                    Layout.fillWidth: true
                    PanelTitle {
                        Layout.fillWidth: true
                        text: qsTrId("org.beegor.cluster.main.raw_can")
                    }
                    Text {
                        text: page.monitor.frames ? page.monitor.frames.length : 0
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }

                Text {
                    visible: !page.monitor.frames || !page.monitor.frames.length
                    Layout.fillWidth: true
                    text: qsTrId("org.beegor.cluster.main.no_raw")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                }

                ListView {
                    visible: page.monitor.frames && page.monitor.frames.length > 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    orientation: ListView.Horizontal
                    spacing: Theme.spacing
                    model: page.monitor.frames ? page.monitor.frames.slice(0, 5) : []
                    delegate: Rectangle {
                        required property var modelData
                        width: Theme.spacing * 16
                        height: Theme.spacing * 4
                        radius: Theme.radius / 2
                        color: Theme.background
                        Column {
                            anchors.fill: parent
                            anchors.margins: Theme.spacing / 2
                            spacing: 0
                            Text { text: modelData.id || ""; color: Theme.text; font.pixelSize: Theme.fontSmall; font.bold: true }
                            Text { text: modelData.data || ""; color: Theme.textDim; font.pixelSize: Theme.fontSmall; font.family: "monospace"; elide: Text.ElideRight; width: parent.width }
                        }
                    }
                }
            }
        }
    }
}
