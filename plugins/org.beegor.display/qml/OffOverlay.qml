import QtQuick

// Covers OpenHU and projected Android Auto during the ignition-off delay.
// Consume touches so the sleeping display cannot activate controls underneath.
Item {
    Rectangle {
        anchors.fill: parent
        color: "black"
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: mouse => { mouse.accepted = true }
    }
}
