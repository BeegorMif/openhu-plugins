import QtQuick
import OpenHU 1.0

// Frequency scale of FM/AM with a needle. Tap or drag anywhere to choose a frequency: moved() while the finger
// moves (snapped to the raster), chosen() when it is lifted.
Item {
    id: tuning

    property real minimum: 87.5
    property real maximum: 108
    property real step: 0.1
    property real value: minimum
    // ticks: a long one with a label every majorStep, short ones every minorStep
    property real majorStep: 2
    property real minorStep: 0.5
    readonly property bool dragging: area.pressed

    signal moved(real value)
    signal chosen(real value)

    implicitHeight: Math.round(Theme.fontNormal * 3.6)

    function xOf(frequency) {
        return (frequency - tuning.minimum) / (tuning.maximum - tuning.minimum) * tuning.width
    }

    function snapped(x) {
        var frequency = tuning.minimum + Math.max(0, Math.min(1, x / tuning.width)) * (tuning.maximum - tuning.minimum)
        var steps = Math.round((frequency - tuning.minimum) / tuning.step)
        var result = Math.min(tuning.maximum, tuning.minimum + steps * tuning.step)
        return Math.round(result * 10) / 10
    }

    readonly property var ticks: {
        var result = []
        if (tuning.minorStep <= 0 || tuning.maximum <= tuning.minimum)
            return result
        var first = Math.ceil(tuning.minimum / tuning.minorStep) * tuning.minorStep
        for (var frequency = first; frequency <= tuning.maximum + 1e-6; frequency += tuning.minorStep) {
            var rounded = Math.round(frequency * 10) / 10
            var ratio = rounded / tuning.majorStep
            result.push({ frequency: rounded, major: Math.abs(ratio - Math.round(ratio)) < 1e-6 })
        }
        return result
    }

    readonly property int lineY: Math.round(tuning.height * 0.36)

    Rectangle {
        y: tuning.lineY - height / 2
        width: parent.width
        height: Math.max(2, Math.round(2 * Theme.scale))
        radius: height / 2
        color: Theme.textDim
        opacity: 0.35
    }

    Repeater {
        model: tuning.ticks

        Item {
            id: tick
            required property var modelData
            x: tuning.xOf(tick.modelData.frequency)
            y: 0

            Rectangle {
                x: -width / 2
                y: tuning.lineY - height / 2
                width: Math.max(1, Math.round(1.5 * Theme.scale))
                height: Math.round(Theme.fontSmall * (tick.modelData.major ? 1.1 : 0.6))
                color: Theme.textDim
                opacity: tick.modelData.major ? 0.6 : 0.3
            }
            Text {
                visible: tick.modelData.major
                x: -width / 2
                y: tuning.lineY + Theme.fontSmall * 0.7
                text: tick.modelData.frequency
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }
    }

    // needle with a knob
    Item {
        x: tuning.xOf(Math.max(tuning.minimum, Math.min(tuning.maximum, tuning.value)))
        Behavior on x {
            enabled: !tuning.dragging
            NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        Rectangle {
            x: -width / 2
            y: tuning.lineY - Theme.fontSmall * 1.2
            width: Math.max(3, Math.round(4 * Theme.scale))
            height: Math.round(Theme.fontSmall * 2.4)
            radius: width / 2
            color: Theme.primary
        }
        Rectangle {
            x: -width / 2
            y: tuning.lineY - Theme.fontSmall * 1.2 - height / 2
            width: Math.round(Theme.fontSmall * (tuning.dragging ? 1.4 : 1))
            height: width
            radius: width / 2
            color: Theme.primary
            Behavior on width { NumberAnimation { duration: 120 } }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        preventStealing: true
        onPressed: function(mouse) { tuning.moved(tuning.snapped(mouse.x)) }
        onPositionChanged: function(mouse) { tuning.moved(tuning.snapped(mouse.x)) }
        onReleased: function(mouse) { tuning.chosen(tuning.snapped(mouse.x)) }
    }
}
