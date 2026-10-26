
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OpenHU 1.0

Item {
    id: page

    property var values: ({})
    property var monitor: ({})
    property var clusterState: ({})
    property var canState: ({})
    property var displayItems: []

    property bool useImperialUnits: true

    // Responsive square card sizing.
    property int cardTargetWidth: 300
    property int cardSpacing: Theme.spacing

    property var enabledDisplayItems: displayItems.filter(function(item) {
        return item.enabled !== false
    })

    // Read the configured field from its source topic.
    function configuredValue(item) {
        var topic = item.topic || ""
        var key = item.field || item.key || ""

        var sourceValue = field(topic, key, null)

        if (sourceValue === null)
            return null

        var conversion = item.conversion || {}
        var value = Number(sourceValue)

        if (isNaN(value))
            return sourceValue

        if (conversion.type === "multiply")
            return value * Number(conversion.factor)

        switch (conversion) {
        case "kmhToMph":
            return value * 0.621371192237334
        case "kmToMiles":
            return value * 0.621371192237334
        case "mphToKmh":
            return value / 0.621371192237334
        case "milesToKm":
            return value / 0.621371192237334
        default:
            return sourceValue
        }
    }

    function displayIcon(item) {
        var value = configuredValue(item)
console.log("DISPLAY:", item.id,
            "type:", item.displayType,
            "value:", value,
            "labels:", JSON.stringify(item.valueLabels))
        if (value === null || value === undefined)
            return ""

        var icons = item.iconValues || {}
        var key = typeof value === "boolean"
            ? (value ? "1" : "0")
            : String(value)

        if (icons[key] !== undefined)
            return icons[key]

        return ""
    }

    // Interpret common representations of true and false.
    function isActive(value) {
        if (value === undefined || value === null)
            return false

        if (typeof value === "boolean")
            return value

        if (typeof value === "number")
            return value !== 0

        var text = String(value).toLowerCase().trim()

        return text !== ""
                && text !== "0"
                && text !== "false"
                && text !== "off"
                && text !== "no"
                && text !== "null"
    }

    // Format the card value according to its display configuration.
    function displayValue(item) {
        var value = configuredValue(item)

        if (value === null || value === undefined || value === "")
            return "—"

        if (item.displayType === "mapped"
            || item.displayType === "dynamicIcon") {
            var labels = item.valueLabels || {}
            var key = String(value)

            // Boolean values need to match numeric 0/1 mappings.
            if (typeof value === "boolean")
                key = value ? "1" : "0"

            if (labels[key] !== undefined)
                return labels[key]

            return shown(
                value,
                item.decimals === undefined ? 0 : item.decimals
            )
        }

        if (item.displayType === "boolean") {
            return isActive(value)
                    ? (item.onText || "On")
                    : (item.offText || "Off")
        }

        if (item.displayType === "iconText") {
            return isActive(value)
                    ? (item.onText || "On")
                    : (item.offText || "Off")
        }

        if (item.type === "boolean")
            return onOff(value)

        return shown(
            value,
            item.decimals === undefined ? 0 : item.decimals
        )
    }
    
    function configuredUnit(item) {
        if (item.displayType === "boolean"
                || item.displayType === "iconText"
                || item.displayType === "dynamicIcon"
                || item.displayType === "mapped"
                || item.type === "boolean")
            return ""

        if (item.unit !== undefined && item.unit !== "")
            return item.unit

        if (item.type === "speed")
            return useImperialUnits ? "mph" : "km/h"

        if (item.type === "distance")
            return useImperialUnits ? "mi" : "km"

        return ""
    }


    function updateTopic(topic, data) {
        if (topic === "can.odometer"
        || topic === "can.ignition"
        || topic === "can.lights") {
    console.log("VEHICLE DATA:", topic, JSON.stringify(data))
}
        if (topic === "cluster.state") {
            page.clusterState = data || ({})
            page.displayItems = page.clusterState.items || []
            return
        }

        if (topic === "cluster.data") {
            var originalTopic = data ? data.sourceTopic : ""

            if (!originalTopic)
                return

            var copy = Object.assign({}, page.values)
            copy[originalTopic] = data.data || ({})
            page.values = copy
            return
        }

        if (topic === "cluster.monitor" || topic === "can.monitor") {
            page.monitor = data || ({})
            return
        }

        // Cache the payload under its exact published topic.
        var valuesCopy = Object.assign({}, page.values)
        valuesCopy[topic] = data || ({})
        page.values = valuesCopy
    }

    // Prefer an exact topic match. Fall back to legacy topic names.
    
    function dataFor(name) {
        var topic = name || ""

        // Exact topic match.
        var data = values[topic]
        if (data && data.available !== false
                && Object.keys(data).length)
            return data

        // Try common topic aliases.
        var aliases = []

        if (topic.indexOf("vehicle.") === 0)
            aliases.push(topic.substring(8))
        else
            aliases.push("vehicle." + topic)

        if (topic.indexOf("can.") === 0)
            aliases.push(topic.substring(4))
        else
            aliases.push("can." + topic)

        if (topic.indexOf("cluster.") === 0)
            aliases.push(topic.substring(8))
        else
            aliases.push("cluster." + topic)

        for (var i = 0; i < aliases.length; ++i) {
            data = values[aliases[i]]

            if (data && data.available !== false
                    && Object.keys(data).length)
                return data
        }

        // Try decoded cluster data cached under its original topic.
        var shortName = topic
            .replace(/^vehicle\./, "")
            .replace(/^can\./, "")
            .replace(/^cluster\./, "")

        data = values[shortName]

        if (data && data.available !== false)
            return data

        return ({})
    }


    function field(name, key, fallback) {
        var data = dataFor(name)

        if (data.available === false
                || data[key] === undefined
                || data[key] === null)
            return fallback

        return data[key]
    }

    function shown(value, decimals) {
        if (value === undefined || value === null || value === "")
            return "—"

        var number = Number(value)

        return isNaN(number)
                ? String(value)
                : number.toLocaleString(
                      Qt.locale(),
                      "f",
                      decimals === undefined ? 0 : decimals
                  )
    }

    function onOff(value) {
        if (value === undefined || value === null)
            return "—"

        return isActive(value)
                ? qsTrId("org.beegor.cluster.main.on")
                : qsTrId("org.beegor.cluster.main.off")
    }

    function refreshTopics() {
        var topics = api.request("bus.topics").result || []

        for (var i = 0; i < topics.length; ++i) {
            var topic = topics[i]

            if (topic === "cluster.state") {
                var state = eventBus.last(topic) || ({})
                page.clusterState = state
                page.displayItems = state.items || []
            } else if (topic === "cluster.monitor"
                       || topic === "can.monitor") {
                page.monitor = eventBus.last(topic) || ({})
            } else if (topic === "can.state") {
                page.canState = eventBus.last(topic) || ({})
            } else if (topic.indexOf("vehicle.") === 0
                       || topic.indexOf("can.") === 0
                       || topic.indexOf("cluster.") === 0) {
                page.updateTopic(topic, eventBus.last(topic))
            }
        }
    }

    Component.onCompleted: refreshTopics()

    Connections {
        target: eventBus

        function onEvent(topic, data) {
            if (topic === "cluster.state") {
                page.clusterState = data || ({})
                page.displayItems = page.clusterState.items || []
            } else if (topic === "cluster.data") {
                page.updateTopic(topic, data)
            } else if (topic === "can.state") {
                page.canState = data || ({})
            } else if (topic === "can.monitor"
                       || topic === "cluster.monitor") {
                page.monitor = data || ({})
            } else if (topic.indexOf("vehicle.") === 0
                       || topic.indexOf("can.") === 0) {
                page.updateTopic(topic, data)
            }
        }
    }

    component Panel: Rectangle {
        radius: Theme.radius
        color: Theme.surface
        border.width: 1
        border.color: Theme.textDim
        opacity: 0.98
    }

    component PanelTitle: Text {
        color: Theme.textDim
        font.pixelSize: Theme.fontSmall
        font.bold: true
        font.letterSpacing: 1
        text: ""
    }

    component ValueText: Text {
        color: Theme.text
        font.pixelSize: Theme.fontLarge
        font.bold: true
        text: "—"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacing * 1.5
        spacing: Theme.spacing

        // Profile selector and frame rate.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacing

            ComboBox {
                id: profileSelector

                Layout.fillWidth: true
                Layout.minimumWidth: 80
                Layout.maximumWidth: 300

                model: page.clusterState.profiles || []

                onActivated: function(index) {
                    var profiles = page.clusterState.profiles || []

                    if (index >= 0 && index < profiles.length) {
                        api.request("bus.emit", {
                            topic: "cluster.command",
                            data: {
                                cmd: "profile",
                                value: profiles[index]
                            }
                        })
                    }
                }
            }

            Text {
                visible: !!page.clusterState.profileName

                text: qsTrId("org.beegor.cluster.profile ") + (page.clusterState.profileName || "")

                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
                Layout.maximumWidth: 180
            }

            Text {
                visible: !!page.canState.connected

                text: qsTrId("org.beegor.cluster.Frames/Sec ")
                      + (page.canState.framesPerSecond || 0)

                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }

        // Responsive grid of square vehicle cards.
        GridLayout {
            id: cardGrid

            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 0

            rowSpacing: page.cardSpacing
            columnSpacing: page.cardSpacing

            columns: {
                var count = page.enabledDisplayItems.length

                if (count === 0)
                    return 1

                var gap = columnSpacing
                var available = Math.max(1, width)
                var target = page.cardTargetWidth

                var fit = Math.max(
                    1,
                    Math.floor((available + gap) / (target + gap))
                )

                return Math.min(count, fit)
            }

            Repeater {
                model: page.enabledDisplayItems

                delegate: Panel {
                    id: card

                    required property var modelData

                    Layout.fillWidth: true
                    Layout.fillHeight: false
                    Layout.minimumWidth: 0
                    Layout.minimumHeight: 0
                    Layout.preferredHeight: width

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: Theme.spacing
                        spacing: Theme.spacing / 2

                        PanelTitle {
                            Layout.fillWidth: true

                            text: card.modelData.title
                                  || card.modelData.label
                                  || card.modelData.id

                            font.letterSpacing: 0
                            elide: Text.ElideRight
                            maximumLineCount: 2
                            wrapMode: Text.Wrap
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 0

                            Column {
                                anchors.centerIn: parent
                                width: parent.width
                                spacing: Theme.spacing / 3

                                // Optional configured symbol.
                                Text {
                                    width: parent.width
                                    visible: card.modelData.displayType === "dynamicIcon"
                                            ? !!page.displayIcon(card.modelData)
                                            : !!card.modelData.icon

                                    text: card.modelData.displayType === "dynamicIcon"
                                        ? page.displayIcon(card.modelData)
                                        : (card.modelData.icon || "")
                                    color: Theme.text
                                    font.pixelSize: Theme.fontExtraLarge
                                    horizontalAlignment: Text.AlignHCenter
                                }

                                // Status text below the icon.
                                Text {
                                    width: parent.width

                                    visible: card.modelData.displayType === "dynamicIcon"
                                            || card.modelData.displayType === "iconText"

                                    text: page.displayValue(card.modelData)
                                    color: Theme.text
                                    font.pixelSize: Theme.fontExtraLarge
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter

                                    fontSizeMode: Text.Fit
                                    minimumPixelSize: Theme.fontSmall
                                    wrapMode: Text.NoWrap
                                }

                                // Numeric values and mapped labels.
                                Row {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: parent.width
                                    spacing: Theme.spacing / 2

                                    visible: !(card.modelData.displayType === "iconText"
                                            || card.modelData.displayType === "dynamicIcon")

                                    Text {
                                        id: cardValue

                                        width: unitLabel.visible
                                               ? Math.max(
                                                     0,
                                                     parent.width
                                                     - unitLabel.implicitWidth
                                                     - parent.spacing
                                                 )
                                               : parent.width

                                        text: page.displayValue(card.modelData)
                                        color: Theme.text
                                        font.pixelSize: Theme.fontExtraLarge
                                        font.family: "monospace"
                                        font.bold: true

                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter

                                        fontSizeMode: Text.Fit
                                        minimumPixelSize: Theme.fontSmall
                                        wrapMode: Text.NoWrap
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        id: unitLabel

                                        anchors.verticalCenter: parent.verticalCenter
                                        text: page.configuredUnit(card.modelData)
                                        visible: !(card.modelData.displayType === "iconText"
                                                || card.modelData.displayType === "dynamicIcon")

                                        color: Theme.textDim
                                        font.pixelSize: Theme.fontSmall
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true

                            visible: card.modelData.group !== undefined
                            text: card.modelData.group || ""

                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
