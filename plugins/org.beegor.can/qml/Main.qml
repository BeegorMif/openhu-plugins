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
    // CAN monitor filtering
    property var selectedFrameIds: []

    property var availableFrameIds: {
        var frames = monitor.data.frames || []
        var ids = []
        for (var i = 0; i < frames.length; ++i) {
            var id = String(frames[i].id)
            if (ids.indexOf(id) === -1)
                ids.push(id)
        }
        return ids.sort(function(a, b) { return Number(a) - Number(b) })
    }

    property var filteredFrames: {
        var frames = monitor.data.frames || []
        if (selectedFrameIds.length === 0)
            return frames

        return frames.filter(function(frame) {
            return selectedFrameIds.indexOf(String(frame.id)) !== -1
        })
    }

    function toggleFrameFilter(id, checked) {
        var selected = selectedFrameIds.slice()

        // Empty selection means all frames, so initialise with all IDs.
        if (selected.length === 0)
            selected = availableFrameIds.slice()

        var index = selected.indexOf(id)

        if (checked && index === -1)
            selected.push(id)
        else if (!checked && index !== -1)
            selected.splice(index, 1)

        // Selecting everything is equivalent to clearing the filter.
        selectedFrameIds = selected.length === availableFrameIds.length
                ? [] : selected
    }

    function command(cmd, value) {
        api.emitEvent("can.command", { cmd: cmd, value: value })
    }

    // Name(s) of the signals the profile defines for a frame ID, or "" if unknown.
    function frameName(id) {
        var names = canState.data.frameNames || {}
        return names[String(Number(id))] || ""
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

            
            // Frame monitor with persistent scrolling and multi-ID filtering
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
                        // Number of currently visible frames
                        Text {
                            text: page.filteredFrames.length + " / " +
                                  page.availableFrameIds.length
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                        }
                        Switch {
                            checked: !!canState.data.monitor
                            onToggled: page.command("monitor", checked)
                        }
                    }

                    // Frame ID filter dropdown
                    Button {
                        id: filterButton
                        Layout.fillWidth: true
                        visible: !!canState.data.monitor
                        text: page.selectedFrameIds.length === 0
                              ? "All frame IDs (" + page.availableFrameIds.length + ")"
                              : "Filtered (" + page.selectedFrameIds.length + " selected)"

                        onClicked: filterPopup.open()
                        Popup {
                            id: filterPopup
                            parent: filterButton
                            x: 0
                            y: filterButton.height
                            width: filterButton.width
                            height: Math.min(filterContent.implicitHeight + Theme.spacing * 2, 300)
                            padding: Theme.spacing
                            modal: false
                            clip: true
                            background: Rectangle {
                                color: Theme.surface
                                radius: Theme.radius
                                border.color: Theme.textDim
                            }
                            ColumnLayout {
                                id: filterContent
                                anchors.fill: parent
                                spacing: Theme.spacing / 2
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Filter frame IDs"
                                        color: Theme.text
                                        font.bold: true
                                        font.pixelSize: Theme.fontNormal
                                    }
                                    Button {
                                        text: "Clear"
                                        onClicked: page.selectedFrameIds = []
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 1
                                    color: Theme.textDim
                                }
                                ListView {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    // ListView has no implicitHeight, so without this the
                                    // popup's height calculation ignores the list entirely.
                                    Layout.preferredHeight: Math.min(contentHeight, 220)
                                    clip: true
                                    model: page.availableFrameIds
                                    delegate: CheckBox {
                                        width: ListView.view.width
                                        text: "0x" + Number(modelData).toString(16).toUpperCase() +
                                              (page.frameName(modelData) !== ""
                                               ? "  " + page.frameName(modelData) : "")
                                        checked: page.selectedFrameIds.length === 0 ||
                                                 page.selectedFrameIds.indexOf(String(modelData)) !== -1
                                        onToggled: page.toggleFrameFilter(
                                                       String(modelData), checked)
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: page.availableFrameIds.length === 0
                                    text: "No frame IDs detected yet"
                                    color: Theme.textDim
                                    font.pixelSize: Theme.fontSmall
                                }
                            }
                        }
                    }
                    // Frame list
                    ListView {
                        id: frameList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        visible: !!canState.data.monitor
                        model: page.filteredFrames
                        // Preserve the scroll position when the backend
                        // replaces the frames array with a new update.
                        property real savedContentY: 0
                        property bool restoringPosition: false
                        onContentYChanged: {
                            if (!restoringPosition)
                                savedContentY = contentY
                        }
                        onModelChanged: {
                            restoringPosition = true
                            Qt.callLater(function() {
                                frameList.contentY = Math.min(
                                            frameList.savedContentY,
                                            Math.max(0, frameList.contentHeight -
                                                     frameList.height))
                                frameList.restoringPosition = false
                            })
                        }
                        delegate: Text {
                            width: ListView.view.width

                            text: "0x" +
                                  Number(modelData.id).toString(16).toUpperCase() +
                                  "   " + modelData.data +
                                  "   ×" + modelData.count

                            color: modelData.age < 1
                                   ? Theme.text : Theme.textDim

                            font.family: "monospace"
                            font.pixelSize: Theme.fontSmall
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: frameList.count === 0
                            text: "No frames to display"
                            color: Theme.textDim
                            font.pixelSize: Theme.fontNormal
                        }
                    }
                }
            }
        }
    }
}
