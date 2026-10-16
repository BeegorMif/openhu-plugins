import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// Steering wheel keys: choose input devices, learn keys and assign actions.
Item {
    id: page

    BusTopic { id: swcState; topic: "swc.state" }

    property var actionNames: []
    property var learned: null  // last key pressed in learn mode

    function command(data) {
        api.emitEvent("swc.command", data)
    }

    function toggleDevice(name, use) {
        var selected = (swcState.data.selected || []).slice()
        var index = selected.indexOf(name)
        if (use && index < 0) selected.push(name)
        if (!use && index >= 0) selected.splice(index, 1)
        command({ cmd: "devices", value: selected })
    }

    Component.onCompleted: actionNames = Object.keys(api.request("input.actions").result || {}).sort()
    Component.onDestruction: if (swcState.data.learn) command({ cmd: "learn", value: false })

    Connections {
        target: eventBus
        function onEvent(topic, data) {
            if (topic === "swc.key")
                page.learned = data
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Devices
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.surface

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacing
                spacing: Theme.spacing / 2

                Text {
                    text: qsTrId("org.openhu.swc.main.input_devices")
                    color: Theme.text
                    font.pixelSize: Theme.fontNormal
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("org.openhu.swc.main.devices_hint")
                    wrapMode: Text.WordWrap
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                Switch {
                    text: qsTrId("org.openhu.swc.main.exclusive")
                    checked: swcState.data.grab !== false
                    onToggled: page.command({ cmd: "grab", value: checked })
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: swcState.data.devices || []
                    delegate: RowLayout {
                        width: ListView.view.width
                        Text {
                            Layout.fillWidth: true
                            text: modelData.name + (modelData.active ? "  ●" : "")
                            color: modelData.active ? Theme.success : Theme.text
                            font.pixelSize: Theme.fontSmall
                            elide: Text.ElideRight
                        }
                        Switch {
                            checked: (swcState.data.selected || []).indexOf(modelData.name) >= 0
                            onToggled: page.toggleDevice(modelData.name, checked)
                        }
                    }
                }
                Text {
                    visible: !!swcState.data.error
                    text: swcState.data.error || ""
                    color: "#ff8a80"
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        // Key mapping
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
                        text: qsTrId("org.openhu.swc.main.key_mapping")
                        color: Theme.text
                        font.pixelSize: Theme.fontNormal
                        font.bold: true
                    }
                    Switch {
                        text: qsTrId("org.openhu.swc.main.learn")
                        checked: !!swcState.data.learn
                        onToggled: {
                            page.learned = null
                            page.command({ cmd: "learn", value: checked })
                        }
                    }
                }

                // Learn mode: press a key, choose the action
                RowLayout {
                    Layout.fillWidth: true
                    visible: !!swcState.data.learn
                    Text {
                        Layout.fillWidth: true
                        text: page.learned ? qsTrId("org.openhu.swc.main.learned_key").arg(page.learned.name).arg(page.learned.code)
                                            : qsTrId("org.openhu.swc.main.press_key")
                        color: Theme.primary
                        font.pixelSize: Theme.fontNormal
                    }
                    ComboBox {
                        id: actionBox
                        visible: !!page.learned
                        Layout.preferredWidth: Theme.dockWidth * 2.4
                        model: page.actionNames
                    }
                    Button {
                        visible: !!page.learned
                        text: qsTrId("org.openhu.swc.main.assign")
                        highlighted: true
                        onClicked: {
                            page.command({ cmd: "map", code: page.learned.code, action: actionBox.currentText })
                            page.learned = null
                        }
                    }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: swcState.data.keys || []
                    delegate: RowLayout {
                        width: ListView.view.width
                        Text {
                            Layout.preferredWidth: parent.width * 0.4
                            text: modelData.name
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.action
                            color: Theme.text
                            font.pixelSize: Theme.fontSmall
                            elide: Text.ElideRight
                        }
                        Button {
                            text: "✕"
                            flat: true
                            onClicked: page.command({ cmd: "map", code: modelData.code, action: "" })
                        }
                    }
                }

                Button {
                    text: qsTrId("org.openhu.swc.main.default_mapping")
                    flat: true
                    onClicked: page.command({ cmd: "reset" })
                }
            }
        }
    }
}
