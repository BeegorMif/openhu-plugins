import QtQuick
import OpenHU 1.0

// Soft background from the picture of the station: the picture loaded at 6×6 pixels and stretched with smooth
// scaling gives large colour blobs like a strong blur, also with the software renderer (MultiEffect needs a GPU).
// Cross-fades when the picture changes; without one a faint tint.
Item {
    id: backdrop

    property string source
    property color tint: Theme.background

    property bool frontIsA: true

    Component.onCompleted: layerA.source = backdrop.source
    onSourceChanged: {
        // the hidden layer takes the new picture and fades in
        if (backdrop.frontIsA)
            layerB.source = backdrop.source
        else
            layerA.source = backdrop.source
        backdrop.frontIsA = !backdrop.frontIsA
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.background
    }

    Rectangle {
        anchors.fill: parent
        color: backdrop.tint
        opacity: backdrop.source === "" ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }

    Image {
        id: layerA
        anchors.fill: parent
        sourceSize.width: 6
        sourceSize.height: 6
        fillMode: Image.Stretch
        smooth: true
        opacity: backdrop.frontIsA && status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }

    Image {
        id: layerB
        anchors.fill: parent
        sourceSize.width: 6
        sourceSize.height: 6
        fillMode: Image.Stretch
        smooth: true
        opacity: !backdrop.frontIsA && status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }

    // darkens the picture so text and controls stay readable
    Rectangle {
        anchors.fill: parent
        color: Theme.background
        opacity: 0.72
    }
}
