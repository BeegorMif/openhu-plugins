import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import OpenHU 1.0

// CAN bus: interface, vehicle profile, live vehicle values and a frame monitor.
Item {
    id: page

    BusTopic { id: canState; topic: "can.state" }
    BusTopic { id: monitor; topic: "can.monitor" }

    // vehicle.* topics -> {topic: {field: value}}
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
        var topics = api.request("bus.topics").result || []
        for (var i = 0; i < topics.length; ++i)
            if (topics[i].indexOf("vehicle.") === 0)
                updateVehicle(topics[i], eventBus.last(topics[i]))
    }

    Connections {
        target: eventBus
        function onEvent(topic, data) {
            if (topic.indexOf("vehicle.") === 0)
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
                width: Theme.spacing * 0.7
                height: width
                radius: width / 2
                color: canState.data.connected ? Theme.success : "#ff8a80"
            }
            Text {
                text: canState.data.connected
                      ? canState.data.interface + " · " + (canState.data.framesPerSecond || 0) + " Frames/s"
                      : (canState.data.error || "Plugin-Prozess läuft nicht")
                color: Theme.text
                font.pixelSize: Theme.fontNormal
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            TextField {
                id: interfaceField
                Layout.preferredWidth: Theme.dockWidth * 1.3
                placeholderText: "can0"
                text: canState.data.interface || ""
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
            text: "Profil: " + canState.data.profileName
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
                        text: "Noch keine Fahrzeugdaten"
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
                            text: "CAN-Monitor"
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
