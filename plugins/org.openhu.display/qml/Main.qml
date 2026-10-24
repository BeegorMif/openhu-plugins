import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

Item {
    id: page
    property bool settingsOpen: false
    BusTopic { id: state; topic: "display.state" }

    function command(cmd, extra) {
        var data = extra || {}
        data.cmd = cmd
        api.emitEvent("display.command", data)
    }

    Rectangle {
        anchors.fill: parent
        color: "black"

        // The status bar shortcut opens this deliberately empty, black page.
        Button {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.spacing / 2
            width: Theme.spacing * 1.5
            height: width
            visible: !page.settingsOpen
            text: "⚙"
            font.pixelSize: Theme.fontNormal
            background: Rectangle { color: "transparent" }
            contentItem: Text { text: parent.text; color: "#777"; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            onClicked: page.settingsOpen = true
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacing * 1.5
            spacing: Theme.spacing
            visible: page.settingsOpen

            RowLayout {
                Layout.fillWidth: true
                Button { text: "‹"; onClicked: page.settingsOpen = false }
                Text { Layout.fillWidth: true; text: qsTr("Display settings"); color: Theme.text; font.pixelSize: Theme.fontHuge }
            }
            Text {
                Layout.fillWidth: true
                text: state.data.error || qsTr("CAN brightness: %1% from %2.%3")
                      .arg(state.data.lastSignal === undefined || state.data.lastSignal === null ? "—" : state.data.lastSignal)
                      .arg(state.data.topic || "can.display").arg(state.data.field || "dimByte")
                color: state.data.error ? "#ff8a80" : Theme.textDim
                font.pixelSize: Theme.fontNormal
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                CheckBox { id: canEnabled; text: qsTr("Use CAN brightness"); checked: state.data.enabled !== false }
                Button {
                    text: qsTr("Save")
                    onClicked: page.command("configure", {topic: topic.text, field: field.text, display: display.text, enabled: canEnabled.checked})
                }
            }
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                Text { text: qsTr("CAN topic"); color: Theme.textDim }
                TextField { id: topic; Layout.fillWidth: true; text: state.data.topic || "can.display"; placeholderText: "can.display" } // untranslated: example CAN topic
                Text { text: qsTr("Signal field"); color: Theme.textDim }
                TextField { id: field; Layout.fillWidth: true; text: state.data.field || "dimByte"; placeholderText: "dimByte" } // untranslated: example CAN field
                Text { text: qsTr("Display number (optional)"); color: Theme.textDim }
                TextField { id: display; Layout.fillWidth: true; text: state.data.display || ""; placeholderText: qsTr("Auto detect"); inputMethodHints: Qt.ImhDigitsOnly }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.outline }
            Text { text: qsTr("Manual brightness"); color: Theme.text; font.pixelSize: Theme.fontLarge }
            RowLayout {
                Layout.fillWidth: true
                Slider {
                    id: brightness
                    Layout.fillWidth: true
                    from: 0
                    to: 100
                    value: state.data.lastSignal === undefined || state.data.lastSignal === null ? 50 : state.data.lastSignal
                    onPressedChanged: if (!pressed) page.command("manual", {value: value})
                }
                Text { text: Math.round(brightness.value) + "%"; color: Theme.text; font.pixelSize: Theme.fontNormal }
            }
            Button { text: qsTr("Black screen"); onClicked: page.settingsOpen = false }
            Item { Layout.fillHeight: true }
        }
    }
}
