import QtQuick
import OpenHU 1.0

// A short message above the mini bar (mode changed, playlist saved, stick removed)
Rectangle {
    id: toast

    property bool error: false

    function show(text, error) {
        label.text = text
        toast.error = error === true
        toast.opacity = 1
        hide.restart()
    }

    width: Math.min(label.implicitWidth + Theme.spacing * 2, parent ? parent.width - Theme.spacing * 2 : 400)
    height: label.implicitHeight + Theme.spacing
    radius: height / 2
    color: toast.error ? "#5a2626" : Theme.surfaceHigh
    border.color: toast.error ? "#ff8a80" : Theme.outline
    border.width: 1
    opacity: 0
    visible: opacity > 0
    z: 30
    Behavior on opacity { NumberAnimation { duration: 180 } }

    Text {
        id: label
        anchors.centerIn: parent
        width: Math.min(implicitWidth, toast.width - Theme.spacing * 2)
        color: Theme.text
        font.pixelSize: Theme.fontNormal * 0.9
        elide: Text.ElideRight
    }

    Timer {
        id: hide
        interval: 2200
        onTriggered: toast.opacity = 0
    }
}
