import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// CAN bus: interface, vehicle profile, live vehicle values and a frame monitor.
Item {
    id: page

    BusTopic { id: canState; topic: "can.state" }
    BusTopic { id: monitor; topic: "can.monitor" }

    // Decoded values -> {topic: {field: value}}. Ignition remains can.ignition because it is not
    // an Android Auto vehicle sensor, so include it explicitly alongside vehicle.* here.
    property var vehicle: ({})

    function command(cmd, value) {
        api.emitEvent("can.command", { cmd: cmd, value: value })
    }

    function updateVehicle(topic, data) {
        var copy = Object.assign({}, vehicle)
        copy[topic] = data
        vehicle = copy
    }

    Component.onCompleted: {
        interfaceField.text = canState.data.interface || ""
        var topics = api.request("bus.topics").result || []
        for (var i = 0; i < topics.length; ++i)
            if (topics[i].indexOf("vehicle.") === 0 || topics[i] === "can.ignition")
                updateVehicle(topics[i], eventBus.last(topics[i]))
    }

    Connections {
        target: eventBus
        function onEvent(topic, data) {
            if (topic === "can.state" && !interfaceField.activeFocus)
                interfaceField.text = data.interface || ""
            else if (topic.indexOf("vehicle.") === 0 || topic === "can.ignition")
                page.updateVehicle(topic, data)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Connection and profile
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            Rectangle {
                Layout.preferredWidth: Theme.spacing * 0.7
                Layout.preferredHeight: Theme.spacing * 0.7
                radius: width / 2
                color: canState.data.connected ? Theme.success : "#ff8a80"
            }
            Text {
                text: canState.data.connected
                      ? qsTrId("org.beegor.can.main.frames_per_second").arg(canState.data.interface).arg(canState.data.framesPerSecond || 0)
                      : (canState.data.error || qsTrId("org.beegor.can.main.process_not_running"))
                color: Theme.text
                font.pixelSize: Theme.fontNormal
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            TextField {
                id: interfaceField
                Layout.preferredWidth: Theme.dockWidth * 1.3
                placeholderText: "can0"  // untranslated: an interface name
                // Keep the user's draft while editing; CAN state is republished every second.
                onAccepted: page.command("interface", text)
            }
            ComboBox {
                id: profileBox
                Layout.preferredWidth: Theme.dockWidth * 2.5
                model: canState.data.profiles || []
                currentIndex: model.indexOf ? model.indexOf(canState.data.profile) : -1
                onActivated: page.command("profile", currentText)
            }
        }

        Text {
            visible: !!canState.data.profileName
            text: qsTrId("org.beegor.can.main.profile").arg(canState.data.profileName)
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacing

            // Vehicle values
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface

                ListView {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing
                    clip: true
                    model: Object.keys(page.vehicle).sort()
                    delegate: Column {
                        width: ListView.view.width
                        bottomPadding: Theme.spacing / 2
                        Text {
                            text: modelData
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                        Text {
                            width: parent.width
                            wrapMode: Text.WrapAnywhere
                            text: {
                                var data = page.vehicle[modelData] || {}
                                return Object.keys(data).map(function(key) { return key + ": " + data[key] }).join("   ")
                            }
                            color: Theme.text
                            font.pixelSize: Theme.fontNormal
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: parent.count === 0
                        text: qsTrId("org.beegor.can.main.no_vehicle_data")
                        color: Theme.textDim
                        font.pixelSize: Theme.fontNormal
                    }
                }
            }

            // Frame monitor to find the ids of a car
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: Theme.radius
                color: Theme.surface

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacing
                    spacing: Theme.spacing / 2

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: qsTrId("org.beegor.can.main.monitor")
                            color: Theme.text
                            font.pixelSize: Theme.fontNormal
                            font.bold: true
                        }
                        Switch {
                            checked: !!canState.data.monitor
                            onToggled: page.command("monitor", checked)
                        }
                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: !!canState.data.monitor
                        model: monitor.data.frames || []
                        delegate: Text {
                            width: ListView.view.width
                            text: modelData.id + "   " + modelData.data + "   ×" + modelData.count
                            color: modelData.age < 1 ? Theme.text : Theme.textDim
                            font.family: "monospace"
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                }
            }
        }
    }
}
