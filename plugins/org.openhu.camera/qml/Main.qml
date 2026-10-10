import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtMultimedia 5.15
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
                    text: "Kamera"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                ComboBox {
                    Layout.fillWidth: true
                    textRole: "displayName"
                    model: QtMultimedia.availableCameras
                    currentIndex: {
                        var cameras = QtMultimedia.availableCameras
                        for (var i = 0; i < cameras.length; ++i)
                            if (cameras[i].deviceId === cameraConfig.data.device)
                                return i
                        return 0
                    }
                    onActivated: page.set("device", QtMultimedia.availableCameras[index].deviceId)
                }

                Text {
                    text: "Anzeige beim Rückwärtsgang"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                RadioButton {
                    text: "Vollbild über allem"
                    checked: cameraConfig.data.display === "overlay"
                    onClicked: page.set("display", "overlay")
                }
                RadioButton {
                    text: "Im Inhaltsbereich (wie Radio)"
                    checked: cameraConfig.data.display !== "overlay"
                    onClicked: page.set("display", "page")
                }

                Switch {
                    text: "Im Menü anzeigen"
                    checked: page.inDock
                    onToggled: api.request("plugin.setDock", { id: page.pluginId, dock: checked })
                }
                Switch {
                    text: "Automatisch beim Rückwärtsgang"
                    checked: cameraConfig.data.autoReverse !== false
                    onToggled: page.set("autoReverse", checked)
                }
                Switch {
                    text: "Spiegeln"
                    checked: !!cameraConfig.data.mirror
                    onToggled: page.set("mirror", checked)
                }
                Switch {
                    text: "Hilfslinien"
                    checked: cameraConfig.data.guides !== false
                    onToggled: page.set("guides", checked)
                }
                Button {
                    Layout.fillWidth: true
                    Layout.topMargin: Theme.spacing
                    visible: cameraConfig.data.display === "overlay"
                    text: "Vollbild testen"
                    highlighted: true
                    onClicked: api.emitEvent("camera.command", { cmd: "show" })
                }
            }
        }
    }
}
