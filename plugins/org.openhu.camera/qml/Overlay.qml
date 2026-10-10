import QtQuick 2.15
import OpenHU 1.0

// Full screen camera above the shell and Android Auto.
Item {
    BusTopic { id: cameraConfig; topic: "camera.config" }

    CameraView {
        anchors.fill: parent
        config: cameraConfig.data
    }

    // Close
    Rectangle {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.spacing
        width: Theme.dockWidth * 0.7
        height: width
        radius: width / 2
        color: "#99000000"

        Text {
            anchors.centerIn: parent
            text: "✕"
            color: "white"
            font.pixelSize: Theme.fontLarge
        }
        MouseArea {
            anchors.fill: parent
            onClicked: api.emitEvent("camera.command", { cmd: "hide" })
        }
    }
}
