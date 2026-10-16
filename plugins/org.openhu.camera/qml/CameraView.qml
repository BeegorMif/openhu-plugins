import QtQuick
import QtMultimedia
import OpenHU 1.0

// Camera picture with optional mirroring and parking guide lines (used by the overlay and the page).
Rectangle {
    id: view
    color: "black"
    clip: true

    property var config: ({})

    // Device id as text ("/dev/video0"); QCameraDevice.id is a byte array in QML
    function deviceId(device) {
        var bytes = new Uint8Array(device.id)
        var text = ""
        for (var i = 0; i < bytes.length; ++i)
            text += String.fromCharCode(bytes[i])
        return text
    }

    MediaDevices { id: devices }

    CaptureSession {
        camera: Camera {
            id: camera
            active: true
            // The device can still be busy for a moment (previous page, other program): try again
            onErrorOccurred: if (retry.attempts < 5) retry.start()
            cameraDevice: {
                var inputs = devices.videoInputs
                for (var i = 0; i < inputs.length; ++i)
                    if (view.deviceId(inputs[i]) === view.config.device)
                        return inputs[i]
                return devices.defaultVideoInput
            }
        }
        videoOutput: output
    }

    Timer {
        id: retry
        property int attempts: 0
        interval: 1000
        onTriggered: {
            attempts++
            camera.active = false
            camera.active = true
        }
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
        transform: Scale {
            origin.x: view.width / 2
            xScale: view.config.mirror ? -1 : 1
        }
    }

    // Guide lines: red (near) -> yellow -> green (far)
    Canvas {
        anchors.fill: parent
        visible: view.config.guides !== false
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height
            ctx.reset()
            ctx.lineWidth = Math.max(3, w / 200)
            var bands = [["#ff5252", 1.0, 0.82], ["#ffd740", 0.82, 0.66], ["#69f0ae", 0.66, 0.52]]
            for (var i = 0; i < bands.length; ++i) {
                var color = bands[i][0], y1 = h * bands[i][1], y2 = h * bands[i][2]
                // lanes narrow towards the horizon
                var x1 = w * (0.18 + (1 - bands[i][1]) * 0.6), x2 = w * (0.18 + (1 - bands[i][2]) * 0.6)
                ctx.strokeStyle = color
                ctx.beginPath()
                ctx.moveTo(x1, y1); ctx.lineTo(x2, y2)
                ctx.moveTo(w - x1, y1); ctx.lineTo(w - x2, y2)
                ctx.moveTo(x2, y2); ctx.lineTo(x2 + w * 0.05, y2)
                ctx.moveTo(w - x2, y2); ctx.lineTo(w - x2 - w * 0.05, y2)
                ctx.stroke()
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: !camera.active || camera.error !== Camera.NoError || devices.videoInputs.length === 0
        text: devices.videoInputs.length === 0 ? qsTrId("org.openhu.camera.view.no_camera")
                                                : (camera.errorString || qsTrId("org.openhu.camera.view.starting"))
        color: Theme.textDim
        font.pixelSize: Theme.fontNormal
    }
}
