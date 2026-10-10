import QtQuick 2.15
import QtMultimedia 5.15
import OpenHU 1.0

// Camera picture with optional mirroring and parking guide lines (used by the overlay and the page).
Rectangle {
    id: view
    color: "black"
    clip: true

    property var config: ({})

    Camera {
        id: camera
        deviceId: view.config.device || ""
        captureMode: Camera.CaptureViewfinder
    }

    VideoOutput {
        anchors.fill: parent
        source: camera
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
        visible: camera.cameraStatus !== Camera.ActiveStatus
        text: camera.errorString || "Kamera wird gestartet …"
        color: Theme.textDim
        font.pixelSize: Theme.fontNormal
    }
}
