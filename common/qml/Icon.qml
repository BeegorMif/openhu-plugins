import QtQuick
import OpenHU 1.0
import "Icons.js" as Icons

// An icon of Icons.js in a colour (opaque colours only: the SVG takes "#rrggbb")
Image {
    property string name
    property color color: Theme.text

    sourceSize.width: width
    sourceSize.height: height
    fillMode: Image.PreserveAspectFit
    source: name ? Icons.url(name, String(color)) : ""
}
