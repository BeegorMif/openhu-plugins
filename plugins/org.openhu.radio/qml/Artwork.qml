import QtQuick
import OpenHU 1.0
import "Placeholder.js" as Placeholder

// Picture of a station: its logo or DAB slideshow picture; without one the initials of its name on a colour of the
// name, without a name a radio icon
Rectangle {
    id: artwork

    property string source
    property string name

    readonly property bool hasImage: artwork.source !== "" && image.status === Image.Ready

    radius: Math.max(4, Math.round(width / 10))
    clip: true
    color: artwork.hasImage || artwork.name === "" ? Theme.surfaceHigh : Placeholder.color(artwork.name)

    Image {
        id: image
        anchors.fill: parent
        source: artwork.source
        sourceSize.width: width
        sourceSize.height: height
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        visible: artwork.hasImage
    }

    Text {
        anchors.centerIn: parent
        visible: !artwork.hasImage && artwork.name !== ""
        text: Placeholder.initials(artwork.name)
        color: Theme.text
        font.pixelSize: Math.round(artwork.height * 0.36)
        font.weight: Font.Medium
    }

    Icon {
        anchors.centerIn: parent
        visible: !artwork.hasImage && artwork.name === ""
        width: Math.round(artwork.width * 0.5)
        height: width
        name: "radio"
        color: Theme.textDim
    }
}
