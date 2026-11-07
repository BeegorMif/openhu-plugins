import QtQuick
import OpenHU 1.0

// The Folders tab: a path bar (stick › Music › Artist › …, each part can be tapped), back and "Play folder", the
// subfolders as tiles (the same as in the other tabs) and the music files of the folder as rows below them.
// Without a chosen folder: the sources (or the folders of the only one).
Item {
    id: folders

    property var page
    property int version: 0
    property int columns: 4
    property string source
    property string path
    property var info: ({})
    property int generation: 0
    property bool stale: true

    readonly property var crumbs: folders.info.crumbs || []
    readonly property var subfolders: folders.info.folders || []
    readonly property var files: folders.info.files || []
    readonly property bool atTop: folders.crumbs.length === 0
        || folders.crumbs.length === 1 && !(folders.info.multiple === true)

    function open(source, path) {
        folders.source = source
        folders.path = path
        flick.contentY = 0
        folders.reload()
    }

    function up() {
        if (folders.path !== "") {
            var parts = folders.path.split("/")
            parts.pop()
            folders.open(folders.source, parts.join("/"))
        } else if (folders.info.multiple === true) {
            folders.open("", "")
        }
    }

    function reload() {
        if (!folders.visible || !folders.page) {
            folders.stale = true
            return
        }
        folders.stale = false
        var generation = ++folders.generation
        folders.page.query("folder", { source: folders.source, path: folders.path }, function(result) {
            if (generation !== folders.generation)
                return
            if (result.ok === false && folders.source !== "") {
                // the stick is gone: back to the top
                folders.open("", "")
                return
            }
            folders.info = result
            if (result.source !== undefined && result.source !== folders.source && folders.source === "")
                folders.source = result.source
        })
    }

    onVersionChanged: folders.reload()
    onVisibleChanged: if (folders.visible && folders.stale) folders.reload()
    Component.onCompleted: folders.reload()

    readonly property real cell: Math.floor(flick.width / folders.columns)
    readonly property real gap: Math.round(Theme.spacing * 0.75)

    Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: column
            width: flick.width
            spacing: Math.round(Theme.spacing * 0.5)

            // path bar
            Item {
                width: parent.width
                height: folders.page ? folders.page.touch : 48
                visible: folders.crumbs.length > 0

                IconButton {
                    id: upButton
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: parent.height
                    flat: true
                    iconName: "back"
                    iconScale: 0.5
                    enabled: !folders.atTop
                    Accessible.name: qsTrId("org.openhu.media.main.back")
                    onClicked: folders.up()
                }

                ListView {
                    id: crumbList
                    anchors.left: upButton.right
                    anchors.right: playFolder.left
                    anchors.rightMargin: Math.round(Theme.spacing * 0.5)
                    height: parent.height
                    orientation: ListView.Horizontal
                    clip: true
                    model: folders.crumbs
                    boundsBehavior: Flickable.StopAtBounds
                    onCountChanged: Qt.callLater(crumbList.positionViewAtEnd)

                    delegate: Item {
                        id: crumb
                        required property var modelData
                        required property int index
                        readonly property bool last: crumb.index === crumbList.count - 1
                        width: crumbText.implicitWidth + chevron.width + Theme.spacing * 0.8
                        height: crumbList.height

                        Icon {
                            id: chevron
                            visible: crumb.index > 0
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: crumb.index > 0 ? Math.round(Theme.fontSmall * 1.1) : 0
                            height: width
                            name: "chevronRight"
                            color: Theme.textDim
                        }
                        Text {
                            id: crumbText
                            anchors.left: chevron.right
                            anchors.leftMargin: Math.round(Theme.spacing * 0.4)
                            anchors.verticalCenter: parent.verticalCenter
                            text: crumb.index === 0 && folders.page ? folders.page.sourceTitle(crumb.modelData) : crumb.modelData.title
                            color: crumb.last ? Theme.text : Theme.textDim
                            font.pixelSize: Theme.fontNormal * 0.85
                            font.weight: crumb.last ? Font.Medium : Font.Normal
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: folders.open(folders.source, crumb.modelData.path)
                        }
                    }
                }

                PillButton {
                    id: playFolder
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    touch: parent.height
                    iconName: "play"
                    primary: true
                    text: qsTrId("org.openhu.media.main.play_folder")
                    onClicked: folders.page.playContext({ kind: "folder", source: folders.source, path: folders.path },
                                                        null, null)
                }
            }

            // subfolders (or the sources) as tiles
            Flow {
                width: parent.width
                visible: folders.subfolders.length > 0

                Repeater {
                    model: folders.subfolders

                    Item {
                        id: folderCell
                        required property var modelData
                        width: folders.cell
                        height: folders.cell - folders.gap + Math.round(Theme.fontNormal * 2.9)

                        Tile {
                            x: Math.round(folders.gap / 2)
                            width: folders.cell - folders.gap
                            height: parent.height
                            kind: folderCell.modelData.path === "" && folderCell.modelData.sourceKind
                                ? (folderCell.modelData.sourceKind === "local" ? "local" : "source") : "folder"
                            covers: folderCell.modelData.covers || []
                            title: folders.page ? folders.page.tileTitle(folderCell.modelData) : ""
                            subtitle: folders.page ? folders.page.tileSubtitle(folderCell.modelData) : ""
                            placeholderIcon: "folder"
                            playing: folders.page ? folders.page.holds(folderCell.modelData) : false
                            onClicked: folders.open(folderCell.modelData.source, folderCell.modelData.path)
                            onHeld: folders.page.openMenu(folderCell.modelData)
                        }
                    }
                }
            }

            // the music files of the folder
            Repeater {
                model: folders.files

                TrackRow {
                    id: fileRow
                    required property var modelData
                    width: column.width
                    touch: folders.page ? folders.page.touch : 48
                    title: fileRow.modelData.title || ""
                    subtitle: fileRow.modelData.artist || ""
                    cover: fileRow.modelData.cover || ""
                    duration: fileRow.modelData.duration || 0
                    playing: folders.page ? folders.page.playingTrack(fileRow.modelData) : false
                    onClicked: folders.page.playContext({ kind: "folder", source: folders.source, path: folders.path,
                                                          recursive: false }, fileRow.modelData.id, null)
                    onHeld: folders.page.openMenu(fileRow.modelData)
                }
            }

            Text {
                width: parent.width
                visible: folders.crumbs.length > 0 && folders.subfolders.length === 0 && folders.files.length === 0
                topPadding: Theme.spacing * 2
                horizontalAlignment: Text.AlignHCenter
                text: qsTrId("org.openhu.media.main.empty_folder")
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
            }
        }
    }
}
