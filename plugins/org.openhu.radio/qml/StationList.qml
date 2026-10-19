import QtQuick
import OpenHU 1.0

// Station list: favorites first, then the other stations. Each entry: {key, name, title, detail, text, logo,
// favorite, current}; a header entry: {header: "..."}. A tap tunes, the heart on the right toggles the favorite.
Rectangle {
    id: list

    property var entries: []
    property bool playing: false
    property bool scanAvailable: true
    property bool scanning: false
    property bool canCancel: false
    // -1: without known progress
    property real scanProgress: -1
    property string scanText
    property string emptyText

    signal tuneRequested(var key)
    signal favoriteToggled(var key)
    signal scanRequested()
    signal cancelRequested()

    radius: Theme.radius
    color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.55)

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: Theme.spacing
        anchors.rightMargin: Theme.spacing / 2
        anchors.topMargin: Theme.spacing / 2
        height: scanButton.height

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: qsTrId("org.openhu.radio.main.stations")
            color: Theme.text
            font.pixelSize: Theme.fontNormal
            font.weight: Font.Medium
        }

        IconButton {
            id: scanButton
            anchors.right: parent.right
            visible: list.scanAvailable
            implicitWidth: Math.round(52 * Theme.scale)
            iconName: list.scanning ? "close" : "scan"
            enabled: !list.scanning || list.canCancel
            Accessible.name: list.scanning ? qsTrId("org.openhu.radio.main.cancel") : qsTrId("org.openhu.radio.main.scan")
            onClicked: list.scanning ? list.cancelRequested() : list.scanRequested()
        }
    }

    Column {
        id: progress
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.margins: Theme.spacing
        anchors.topMargin: Theme.spacing / 2
        spacing: Theme.spacing / 3
        visible: list.scanning
        height: visible ? implicitHeight : 0

        Rectangle {
            id: track
            width: parent.width
            height: Math.max(3, Math.round(4 * Theme.scale))
            radius: height / 2
            color: Theme.outline
            clip: true

            Rectangle {
                id: bar
                height: parent.height
                radius: height / 2
                color: Theme.primary
                width: list.scanProgress >= 0 ? parent.width * Math.min(1, list.scanProgress) : parent.width * 0.3

                // without a known progress the bar runs back and forth
                SequentialAnimation on x {
                    running: list.scanning && list.scanProgress < 0
                    loops: Animation.Infinite
                    NumberAnimation { from: 0; to: track.width * 0.7; duration: 900; easing.type: Easing.InOutQuad }
                    NumberAnimation { from: track.width * 0.7; to: 0; duration: 900; easing.type: Easing.InOutQuad }
                }
            }
        }
        Text {
            width: parent.width
            text: list.scanText
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
            elide: Text.ElideRight
        }
    }

    ListView {
        id: view
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: progress.bottom
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spacing / 2
        anchors.topMargin: list.scanning ? Theme.spacing / 2 : 0
        clip: true
        model: list.entries
        boundsBehavior: Flickable.StopAtBounds

        delegate: Item {
            id: entry
            required property var modelData
            readonly property bool isHeader: entry.modelData.header !== undefined
            readonly property bool active: !entry.isHeader && entry.modelData.current === true

            width: ListView.view.width
            height: entry.isHeader ? Math.round(Theme.fontSmall * 2.2) : Math.round(Math.max(56 * Theme.scale, Theme.fontNormal * 3))

            Text {
                visible: entry.isHeader
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.leftMargin: Theme.spacing / 2
                anchors.bottomMargin: Theme.spacing / 4
                text: entry.modelData.header || ""
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }

            Rectangle {
                visible: !entry.isHeader
                anchors.fill: parent
                radius: Theme.radius / 2
                color: entry.active ? Theme.selected : rowArea.pressed ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
            }

            MouseArea {
                id: rowArea
                visible: !entry.isHeader
                anchors.fill: parent
                onClicked: list.tuneRequested(entry.modelData.key)
            }

            Artwork {
                id: thumb
                visible: !entry.isHeader
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacing / 2
                height: Math.round(parent.height * 0.7)
                width: height
                source: entry.modelData.logo || ""
                name: entry.modelData.name || ""
            }

            Column {
                visible: !entry.isHeader
                anchors.left: thumb.right
                anchors.right: onAir.visible ? onAir.left : heart.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacing * 0.75
                anchors.rightMargin: Theme.spacing / 2

                Text {
                    width: parent.width
                    text: entry.modelData.title || ""
                    color: entry.active ? Qt.lighter(Theme.primary, 1.25) : Theme.text
                    font.pixelSize: Theme.fontNormal
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    // the station that plays shows its radio text, the others frequency or channel and ensemble
                    readonly property bool live: entry.active && list.playing && !!entry.modelData.text
                    visible: text !== ""
                    text: live ? entry.modelData.text : (entry.modelData.detail || "")
                    color: live ? Qt.lighter(Theme.primary, 1.25) : Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                }
            }

            Icon {
                id: onAir
                visible: entry.active && list.playing
                anchors.right: heart.left
                anchors.verticalCenter: parent.verticalCenter
                width: Math.round(Theme.fontNormal * 1.1)
                height: width
                name: "onAir"
                color: Qt.lighter(Theme.primary, 1.25)
            }

            IconButton {
                id: heart
                visible: !entry.isHeader
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: Math.round(52 * Theme.scale)
                flat: true
                iconScale: 0.46
                iconName: entry.modelData.favorite ? "heartFilled" : "heart"
                iconColor: entry.modelData.favorite ? "#ff6b81" : "#5d6b78"
                Accessible.name: qsTrId("org.openhu.radio.main.favorite")
                onClicked: list.favoriteToggled(entry.modelData.key)
            }
        }

        Text {
            anchors.centerIn: parent
            width: parent.width - Theme.spacing * 2
            visible: view.count === 0
            text: list.emptyText
            color: Theme.textDim
            font.pixelSize: Theme.fontNormal
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
