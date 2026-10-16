import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

// Vehicle data logger: switch logging on, what to log, interval, size limit, storage use, delete all data.
// Showing the data (trips, charts, export) is up to other plugins (logger.query, README.md).
Item {
    id: page

    BusTopic { id: loggerState; topic: "logger.state" }

    readonly property var info: loggerState.data || {}
    readonly property var groups: info.groups || {}
    readonly property var usage: info.usage || {}
    readonly property var limits: [100, 250, 500, 1024, 2048, 4096, 8192, 16384]
    // rate of vehicle.*: seconds (whole or tenths) or "update" (every change); unset = every change
    readonly property var vehicleRate: (info.rates || {})["vehicle.*"] === undefined ? "update"
                                                                                   : info.rates["vehicle.*"]
    // 0 = every n seconds, 1 = every 0.n seconds, 2 = every change
    readonly property int vehicleMode: vehicleRate === "update" ? 2 : (Number(vehicleRate) < 1 ? 1 : 0)
    property bool confirmDelete: false

    function set(key, value) {
        api.emitEvent("logger.command", { cmd: "set", key: key, value: value })
    }

    function number(value, decimals) {
        return Number(value).toLocaleString(Qt.locale(), "f", decimals)
    }

    function size(bytes) {
        var mb = (bytes || 0) / 1048576
        return mb >= 1024 ? number(mb / 1024, 1) + " GB" : number(mb, mb >= 10 ? 0 : 1) + " MB"
    }

    function duration(ms) {
        var minutes = Math.floor((ms || 0) / 60000)
        return Math.floor(minutes / 60) + ":" + ("0" + minutes % 60).slice(-2) + " h"
    }

    function dateTime(ms) {
        return new Date(ms).toLocaleString(Qt.locale(), Locale.ShortFormat)
    }

    Timer {
        interval: 5000
        running: page.confirmDelete
        onTriggered: page.confirmDelete = false
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Settings
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.surface

            Flickable {
                anchors.fill: parent
                anchors.margins: Theme.spacing
                contentHeight: settings.implicitHeight
                clip: true

                ColumnLayout {
                    id: settings
                    width: parent.width
                    spacing: Theme.spacing / 2

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: qsTrId("org.openhu.logger.main.logging")
                            color: Theme.text
                            font.pixelSize: Theme.fontNormal
                            font.bold: true
                        }
                        Switch {
                            checked: !!page.info.enabled
                            onToggled: page.set("enabled", checked)
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: page.info.enabled ? qsTrId("org.openhu.logger.main.logging_on")
                                                : qsTrId("org.openhu.logger.main.logging_off")
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }

                    Repeater {
                        model: [
                            { key: "vehicle", label: qsTrId("org.openhu.logger.main.group_vehicle") },
                            { key: "openhu", label: qsTrId("org.openhu.logger.main.group_openhu") },
                            { key: "health", label: qsTrId("org.openhu.logger.main.group_health") },
                            { key: "position", label: qsTrId("org.openhu.logger.main.group_position") }
                        ]
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            enabled: !!page.info.enabled
                            Text {
                                Layout.fillWidth: true
                                text: modelData.label
                                wrapMode: Text.WordWrap
                                color: parent.enabled ? Theme.text : Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                            Switch {
                                checked: !!page.groups[modelData.key]
                                onToggled: page.set("groups." + modelData.key, checked)
                            }
                        }
                    }

                    // vehicle data: every n seconds, every 0.n seconds or every change
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: qsTrId("org.openhu.logger.main.vehicle_rate")
                            wrapMode: Text.WordWrap
                            color: Theme.text
                            font.pixelSize: Theme.fontSmall
                        }
                        ComboBox {
                            id: vehicleMode
                            Layout.preferredWidth: Theme.dockWidth * 2.2
                            model: [qsTrId("org.openhu.logger.main.rate_seconds"),
                                    qsTrId("org.openhu.logger.main.rate_tenths"),
                                    qsTrId("org.openhu.logger.main.rate_update")]
                            currentIndex: page.vehicleMode
                            onActivated: function (index) {
                                page.set("rates.vehicle.*", index === 2 ? "update" : (index === 1 ? 0.5 : 5))
                            }
                        }
                        SpinBox {
                            visible: page.vehicleMode !== 2
                            from: 1
                            to: page.vehicleMode === 1 ? 9 : 60
                            value: page.vehicleMode === 1 ? Math.round(Number(page.vehicleRate) * 10)
                                                          : Math.round(Number(page.vehicleRate))
                            textFromValue: function (value) {
                                return page.vehicleMode === 1 ? page.number(value / 10, 1) : String(value)
                            }
                            onValueModified: page.set("rates.vehicle.*", page.vehicleMode === 1 ? value / 10 : value)
                        }
                    }

                    // head unit values (CPU, memory, disk): read every n seconds
                    RowLayout {
                        Layout.fillWidth: true
                        visible: !!page.groups.health
                        Text {
                            Layout.fillWidth: true
                            text: qsTrId("org.openhu.logger.main.interval")
                            wrapMode: Text.WordWrap
                            color: Theme.text
                            font.pixelSize: Theme.fontSmall
                        }
                        SpinBox {
                            from: 1
                            to: 60
                            value: page.info.interval || 5
                            onValueModified: page.set("interval", value)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: qsTrId("org.openhu.logger.main.limit")
                            color: Theme.text
                            font.pixelSize: Theme.fontSmall
                        }
                        ComboBox {
                            id: limitBox
                            Layout.preferredWidth: Theme.dockWidth * 1.6
                            model: page.limits.map(function (mb) { return page.size(mb * 1048576) })
                            currentIndex: {
                                var index = page.limits.indexOf(page.info.limitMB || 1024)
                                return index >= 0 ? index : 3
                            }
                            onActivated: function (index) { page.set("limitMB", page.limits[index]) }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTrId("org.openhu.logger.main.limit_hint")
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                }
            }
        }

        // Status
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.surface

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacing
                spacing: Theme.spacing / 2

                Text {
                    text: qsTrId("org.openhu.logger.main.storage")
                    color: Theme.text
                    font.pixelSize: Theme.fontNormal
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("org.openhu.logger.main.used").arg(page.size(page.usage.usedBytes))
                                                               .arg(page.size(page.usage.limitBytes))
                    color: Theme.text
                    font.pixelSize: Theme.fontSmall
                }
                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: page.usage.limitBytes || 1
                    value: page.usage.usedBytes || 0
                }
                Text {
                    Layout.fillWidth: true
                    text: qsTrId("org.openhu.logger.main.trips").arg(page.usage.trips || 0)
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                Text {
                    Layout.fillWidth: true
                    visible: !!page.usage.oldestSample
                    text: qsTrId("org.openhu.logger.main.oldest").arg(page.dateTime(page.usage.oldestSample || 0))
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: page.info.recording
                              ? qsTrId("org.openhu.logger.main.recording_running").arg(page.dateTime(page.info.recording.start))
                              : qsTrId("org.openhu.logger.main.recordings").arg(page.usage.recordings || 0)
                                    .arg(page.size(page.usage.recordingBytes)).arg(page.size(page.usage.recordingLimitBytes))
                        color: page.info.recording ? Theme.success : Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }
                    Button {
                        enabled: !!page.info.enabled
                        text: page.info.recording ? qsTrId("org.openhu.logger.main.record_stop")
                                                  : qsTrId("org.openhu.logger.main.record_start")
                        onClicked: api.emitEvent("logger.command", { cmd: "record", action: page.info.recording ? "stop" : "start" })
                    }
                }

                Text {
                    Layout.topMargin: Theme.spacing / 2
                    text: qsTrId("org.openhu.logger.main.current_trip")
                    color: Theme.text
                    font.pixelSize: Theme.fontNormal
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: page.info.trip
                          ? qsTrId("org.openhu.logger.main.trip_running").arg(page.dateTime(page.info.trip.start))
                                .arg(page.number(page.info.trip.distance || 0, 1)).arg(page.duration(page.info.trip.duration))
                          : qsTrId("org.openhu.logger.main.no_trip")
                    color: page.info.trip ? Theme.success : Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                Text {
                    Layout.fillWidth: true
                    visible: !page.info.vehicleData
                    wrapMode: Text.WordWrap
                    text: qsTrId("org.openhu.logger.main.no_vehicle_data")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
                Text {
                    Layout.fillWidth: true
                    visible: !!page.info.error || !!page.info.recovered || !!page.info.oldSchema
                    wrapMode: Text.WordWrap
                    text: page.info.error ? qsTrId("org.openhu.logger.main.error").arg(page.info.error)
                          : page.info.recovered ? qsTrId("org.openhu.logger.main.recovered").arg(page.info.recovered)
                                                : qsTrId("org.openhu.logger.main.old_schema").arg(page.info.oldSchema || "")
                    color: "#ff8a80"
                    font.pixelSize: Theme.fontSmall
                }

                Item { Layout.fillHeight: true }

                Button {
                    text: page.confirmDelete ? qsTrId("org.openhu.logger.main.delete_confirm")
                                             : qsTrId("org.openhu.logger.main.delete")
                    highlighted: page.confirmDelete
                    onClicked: {
                        if (page.confirmDelete)
                            api.emitEvent("logger.command", { cmd: "clear" })
                        page.confirmDelete = !page.confirmDelete
                    }
                }
            }
        }
    }
}
