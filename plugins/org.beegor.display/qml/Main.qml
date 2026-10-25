import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

Item {
    id: page
    property bool settingsOpen: false
BusTopic {
    id: state
    topic: "display.state"
}

function command(cmd, extra) {
    var data = extra || {}
    data.cmd = cmd
    api.emitEvent("display.command", data)
}

// Reusable controls with theme defaults.
component AppHeading: AppText {
    font.bold: true
    Layout.fillWidth: true
}

component AppText: Text {
    font.pixelSize: Theme.fontNormal
    color: Theme.text
}

component AppSecondaryText: AppText {
    color: Theme.textDim
}

component AppCard: Rectangle {
    radius: Theme.radius
    color: Theme.surface
}

component AppLabel: Label {
    font.pixelSize: Theme.fontNormal
}

component AppButton: Button {
    font.pixelSize: Theme.fontNormal
}

component AppCheckBox: CheckBox {
    font.pixelSize: Theme.fontNormal
}

component AppTextField: TextField {
    font.pixelSize: Theme.fontNormal
    Layout.fillWidth: true
}

// The black screen covers the whole window, dock and status bar included.
function showBlackout() {
    if (page.visible && !page.settingsOpen)
        blackout.open()
}

function openAndroidAuto() {
    blackout.close()
    api.request("ui.navigate", { page: "aa" })
}

function openSettings() {
    blackout.close()
    page.settingsOpen = true
}

onVisibleChanged: if (visible) showBlackout(); else blackout.close()
Component.onCompleted: showBlackout()

component GearButton: Button {
    id: gear
    width: Theme.spacing * 3
    height: width
    text: "⚙"
    font.pixelSize: Theme.fontExtraLarge
    background: Rectangle {
        color: "transparent"
    }
    contentItem: Text {
        text: gear.text
        color: "#777"
        font: gear.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}

// Full-window black. Touch anywhere leaves it for Android Auto, the gear opens the settings.
Popup {
    id: blackout
    parent: page.Overlay.overlay || (page.Window.window ? page.Window.window.contentItem : null)
    x: 0
    y: 0
    width: parent ? parent.width : 0
    height: parent ? parent.height : 0
    padding: 0
    modal: true
    dim: false
    closePolicy: Popup.NoAutoClose
    enter: Transition {}
    exit: Transition {}

    background: Rectangle {
        color: "black"
    }

    contentItem: Item {
        MouseArea {
            anchors.fill: parent
            onClicked: page.openAndroidAuto()
        }

        GearButton {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.spacing * 1.5
            onClicked: page.openSettings()
        }
    }
}

// The settings page; the black screen above is the only other state.
Rectangle {
    anchors.fill: parent
    color: "black"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing
        visible: page.settingsOpen

        // Title; Black Out goes back to the black screen.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            AppHeading {
                text: qsTr("Display settings")
                font.pixelSize: Theme.fontLarge
                elide: Text.ElideRight
            }

            AppButton {
                text: qsTr("Black Out")
                onClicked: {
                    page.settingsOpen = false
                    page.showBlackout()
                }
            }
        }

        // Brightness source.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            Rectangle {
                Layout.preferredWidth: Theme.spacing * 0.7
                Layout.preferredHeight: Theme.spacing * 0.7
                radius: width / 2
                color: state.data.error ? "#ff8a80" : Theme.success
            }

            AppText {
                Layout.fillWidth: true
                text: state.data.error || qsTr("CAN brightness: %1%")
                      .arg(state.data.lastSignal === undefined || state.data.lastSignal === null
                           ? "—" : state.data.lastSignal)
                color: state.data.error ? "#ff8a80" : Theme.textDim
                wrapMode: Text.Wrap
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacing

            // CAN brightness.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.spacing

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1
                    implicitHeight: brightnessContent.implicitHeight + Theme.spacing * 2

                    ColumnLayout {
                        id: brightnessContent
                        anchors.fill: parent
                        anchors.margins: Theme.spacing
                        spacing: Theme.spacing / 2

                        AppHeading {
                            text: qsTr("Display Brightness")
                        }

                        RowLayout {
                            Layout.fillWidth: true

                            AppCheckBox {
                                id: canEnabled
                                Layout.fillWidth: true
                                text: qsTr("Use CAN Brightness")
                                checked: state.data.enabled !== false
                            }

                            AppButton {
                                text: qsTr("Save")
                                onClicked: page.command("configure", {
                                    topic: topic.text,
                                    field: field.text,
                                    display: display.text,
                                    enabled: canEnabled.checked,
                                    lightsTopic: lightsTopic.text,
                                    lightsField: lightsField.text
                                })
                            }
                        }

                        GridLayout {
                            columns: 2
                            Layout.fillWidth: true
                            columnSpacing: Theme.spacing

                            AppSecondaryText {
                                text: qsTr("Brightness CAN topic")
                            }

                            AppTextField {
                                id: topic
                                text: state.data.canTopic || "can.display"
                                placeholderText: qsTr("can.display")
                            }

                            AppSecondaryText {
                                text: qsTr("Brightness CAN field")
                            }

                            AppTextField {
                                id: field
                                text: state.data.field || "dimByte"
                                placeholderText: qsTr("dimByte")
                            }

                            AppSecondaryText {
                                text: qsTr("Lights CAN Topic")
                            }

                            AppTextField {
                                id: lightsTopic
                                text: state.data.lightsTopic || ""
                                placeholderText: qsTr("can.display")
                            }

                            AppSecondaryText {
                                text: qsTr("Lights CAN Field")
                            }

                            AppTextField {
                                id: lightsField
                                text: state.data.lightsField || ""
                                placeholderText: qsTr("lightsOn")
                            }
                        }

                        Item {
                            Layout.fillHeight: false
                        }
                    }
                }

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: false
                    implicitHeight: canDataContent.implicitHeight + Theme.spacing * 2

                    ColumnLayout {
                        id: canDataContent
                        anchors.fill: parent
                        anchors.margins: Theme.spacing
                        spacing: Theme.spacing / 2

                        AppHeading {
                            text: qsTr("CAN Data")
                        }

                        GridLayout {
                            columns: 2
                            Layout.fillWidth: false
                            columnSpacing: Theme.spacing

                            AppSecondaryText {
                                Layout.fillWidth: true
                                text: qsTr("Lights:")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignRight
                                text: String("%1").arg(state.data.lightsState || "UNKNOWN")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                text: qsTr("Brightness:")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignRight
                                text: String("%1").arg(state.data.brightnessState || "UNKNOWN")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                text: qsTr("Ignition:")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignRight
                                text: String("%1").arg(state.data.ignitionState || "UNKNOWN")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                text: qsTr("Dim Overlay:")
                            }

                            AppSecondaryText {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignRight
                                text: String("%1").arg(state.data.extraDim ? qsTr("On") : qsTr("Off"))
                            }
                        }
                    }
                }
            }
ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.spacing

                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1
                    implicitHeight: extraDimContent.implicitHeight + Theme.spacing * 2

                    ColumnLayout {
                        id: extraDimContent
                        anchors.fill: parent
                        anchors.margins: Theme.spacing
                        spacing: Theme.spacing / 2

                        AppHeading {
                            text: qsTr("Extra Dimming")
                        }

AppCheckBox {
                        Layout.fillWidth: true
                        text: qsTr("Dim the whole interface")
                        checked: state.data.extraDim === true
                        onToggled: page.command("extraDim", { enabled: checked })
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        AppCheckBox {
                            id: autoExtraDim
                            Layout.fillWidth: true
                            text: qsTr("Dim automatically when brightness is below")
                            checked: state.data.autoExtraDim === true
                            onToggled: page.command("autoExtraDim", {
                                enabled: checked,
                                below: autoDimBelow.text || "10"
                            })
                        }

                        AppTextField {
                            id: autoDimBelow
                            Layout.preferredWidth: Theme.spacing * 4
                            text: String(state.data.autoExtraDimBelow !== undefined
                                         ? state.data.autoExtraDimBelow : 10)
                            placeholderText: "10"
                            inputMethodHints: Qt.ImhDigitsOnly
                            enabled: autoExtraDim.checked
                            onEditingFinished: {
                                if (autoExtraDim.checked)
                                    page.command("autoExtraDim", {
                                        enabled: true,
                                        below: text || "10"
                                    })
                            }
                        }

                        AppSecondaryText {
                            text: "%"
                        }
                    }

                    AppCheckBox {
                        Layout.fillWidth: true
                        text: qsTr("Dim off when the lights are off (CAN)")
                        checked: state.data.extraDimLightsOff === true
                        onToggled: page.command("extraDimLightsOff", { enabled: checked })
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        AppCheckBox {
                            id: ignitionPowerOff
                            Layout.fillWidth: true
                            text: qsTr("Black out and shutdown after ignition off")
                            checked: state.data.ignitionPowerOff === true
                            onToggled: page.command("ignitionPowerOff", {
                                enabled: checked,
                                delayMinutes: ignitionDelay.text || "5"
                            })
                        }

                        AppTextField {
                            id: ignitionDelay
                            Layout.preferredWidth: Theme.spacing * 4
                            text: String(Math.max(1, Math.round(
                                (state.data.ignitionDelaySeconds || 300) / 60)))
                            placeholderText: "5"
                            inputMethodHints: Qt.ImhDigitsOnly
                            enabled: ignitionPowerOff.checked
                            onEditingFinished: {
                                if (ignitionPowerOff.checked)
                                    page.command("ignitionPowerOff", {
                                        enabled: true,
                                        delayMinutes: text || "5"
                                    })
                            }
                        }

                        AppSecondaryText {
                            text: qsTr("min")
                        }
                    }
                    Item {
                        Layout.fillHeight: true
                    }
                }
                }
                AppCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: false
                    implicitHeight: canDataContentA.implicitHeight + Theme.spacing * 2

                    ColumnLayout {
                        id: canDataContentA
                        anchors.fill: parent
                        anchors.margins: Theme.spacing
                        spacing: Theme.spacing / 2

                        AppHeading {
                            text: qsTr("Manual Control")
                        }

                        Slider {
                            id: brightness
                            Layout.fillWidth: true
                            enabled: !canEnabled.checked
                            from: 0
                            to: 100
                            value: state.data.lastSignal === undefined || state.data.lastSignal === null
                                   ? 50 : state.data.lastSignal
                            onPressedChanged: {
                                if (!pressed)
                                    page.command("manual", { value: value })
                            }
                        }

                        AppText {
                            text: Math.round(brightness.value) + "%"
                            color: Theme.text
                        }
                    }
                }
            }
        }
    }
}
}
