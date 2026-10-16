import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import OpenHU 1.0

// Reverse camera page: camera picture, settings behind the gear button.
Item {
    id: page

    readonly property string pluginId: "org.openhu.camera"

    BusTopic { id: cameraConfig; topic: "camera.config" }

    property bool settingsOpen: false
    property bool overlayShown: plugins.overlayVisible(pluginId)
    Connections {
        target: plugins
        function onOverlayChanged(id, visible) {
            if (id === page.pluginId)
                page.overlayShown = visible
        }
    }

    readonly property bool inDock: {
        var list = plugins.plugins
        for (var i = 0; i < list.length; ++i)
            if (list[i].id === pluginId)
                return list[i].dock
        return false
    }

    MediaDevices { id: devices }

    // Device id as text ("/dev/video0"), stored in the plugin config; QCameraDevice.id is a byte array in QML
    function deviceId(device) {
        var bytes = new Uint8Array(device.id)
        var text = ""
        for (var i = 0; i < bytes.length; ++i)
            text += String.fromCharCode(bytes[i])
        return text
    }

    function set(key, value) {
        api.emitEvent("camera.command", { cmd: "set", key: key, value: value })
    }

    // Camera picture (not at the same time as the full screen overlay)
    Loader {
        anchors.fill: parent
        active: page.visible && !page.overlayShown
        sourceComponent: CameraView {
            config: cameraConfig.data
        }
    }

    // Settings button
    Rectangle {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.spacing
        width: Theme.dockWidth * 0.7
        height: width
        radius: width / 2
        color: page.settingsOpen ? Theme.primary : "#99000000"
        z: 2

        Image {
            anchors.centerIn: parent
            width: parent.width * 0.5
            height: width
            source: "qrc:/settings-hot.png"
            fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            anchors.fill: parent
            onClicked: page.settingsOpen = !page.settingsOpen
        }
    }

    // Settings panel
    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: Math.min(parent.width * 0.45, Theme.dockWidth * 4.5)
        visible: page.settingsOpen
        color: Theme.surface
        z: 1

        Flickable {
            anchors.fill: parent
            anchors.margins: Theme.spacing
            anchors.topMargin: Theme.dockWidth
            contentHeight: settingsColumn.implicitHeight
            clip: true

            ColumnLayout {
                id: settingsColumn
                width: parent.width
                spacing: Theme.spacing / 2

                Text {
                    text: qsTrId("org.openhu.camera.main.camera")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                ComboBox {
                    Layout.fillWidth: true
                    textRole: "description"
                    model: devices.videoInputs
                    currentIndex: {
                        var cameras = devices.videoInputs
                        for (var i = 0; i < cameras.length; ++i)
                            if (page.deviceId(cameras[i]) === cameraConfig.data.device)
                                return i
                        return 0
                    }
                    onActivated: index => page.set("device", page.deviceId(devices.videoInputs[index]))
                }

                Text {
                    text: qsTrId("org.openhu.camera.main.display_in_reverse")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                RadioButton {
                    text: qsTrId("org.openhu.camera.main.display_overlay")
                    checked: cameraConfig.data.display === "overlay"
                    onClicked: page.set("display", "overlay")
                }
                RadioButton {
                    text: qsTrId("org.openhu.camera.main.display_page")
                    checked: cameraConfig.data.display !== "overlay"
                    onClicked: page.set("display", "page")
                }

                Switch {
                    text: qsTrId("org.openhu.camera.main.show_in_dock")
                    checked: page.inDock
                    onToggled: api.request("plugin.setDock", { id: page.pluginId, dock: checked })
                }
                Switch {
                    text: qsTrId("org.openhu.camera.main.auto_reverse")
                    checked: cameraConfig.data.autoReverse !== false
                    onToggled: page.set("autoReverse", checked)
                }
                Switch {
                    text: qsTrId("org.openhu.camera.main.mirror")
                    checked: !!cameraConfig.data.mirror
                    onToggled: page.set("mirror", checked)
                }
                Switch {
                    text: qsTrId("org.openhu.camera.main.guides")
                    checked: cameraConfig.data.guides !== false
                    onToggled: page.set("guides", checked)
                }
                Button {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.spacing
                    visible: cameraConfig.data.display === "overlay"
                    text: qsTrId("org.openhu.camera.main.test_overlay")
                    highlighted: true
                    onClicked: api.emitEvent("camera.command", { cmd: "show" })
                }
            }
        }
    }
}
