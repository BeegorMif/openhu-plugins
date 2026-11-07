import QtQuick
import OpenHU 1.0
import "Placeholder.js" as Placeholder

// A cover or station logo: the picture (cropped to the square, fit: whole); without one the initials of the name on
// a colour of the name, without a name the icon
Rectangle {
    id: artwork

    property string source
    property string name
    property string icon: "note"
    // the whole picture (station logos) instead of filling the square (covers)
    property bool fit: false

    readonly property bool hasImage: artwork.source !== "" && image.status === Image.Ready

    // small: Rectangle clips without its radius, the corners of a cover stay square
    radius: Math.max(3, Math.round(width / 28))
    clip: true
    color: artwork.hasImage || artwork.name === "" ? Theme.surfaceHigh : Placeholder.color(artwork.name)

    Image {
        id: image
        anchors.fill: parent
        source: artwork.source
        sourceSize.width: width
        sourceSize.height: height
        fillMode: artwork.fit ? Image.PreserveAspectFit : Image.PreserveAspectCrop
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
        name: artwork.icon
        color: Theme.textDim
    }
}
