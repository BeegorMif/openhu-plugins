# Music (`org.openhu.media`)

Music player for USB sticks and the head unit: albums, artists, songs, playlists and folders, a visible queue with
the modes order, shuffle and random, gapless playback with `mpv`. Offline: it reads only the user's own files (tags
and covers from the files, no online lookups). Concept: openhu-plugins#38.

**Packages on the head unit** (Debian trixie; included in the OpenHU OS image, also in `packages` in the manifest):

| Package | What for |
|---|---|
| `mpv` | playback (JSON IPC, gapless) |
| `python3-mutagen` | tags and embedded covers |

Writing playlists to a stick that is mounted read-only uses `pkexec openhu-cli usb write` of the OpenHU OS
(openhu-os#43).

## Sources

- **USB sticks:** every mount under `/run/media/*` (checked every 2 s). A stick is recognised again by its file system
  UUID or label (`/dev/disk/by-uuid`, `by-label`), so the index and the queue of a stick survive re-plugging.
- **Head unit:** `$OPENHU_DATA_DIR/Music` of the plugin (shown as "Head unit").
- **More folders:** `folders` in `config.json`.

Formats: MP3, FLAC, Ogg Vorbis, Opus, M4A/AAC, WAV, WMA (whatever `mpv` plays; tags via mutagen: ID3, Vorbis
comments, MP4 atoms, ASF). Without an album tag the folder name is the album, without a title the file name.

The index is SQLite (`library.db` in the plugin data dir) and is read incrementally: only files whose mtime or size
changed are read again. Covers (embedded pictures, else `cover`, `folder` or `front` `.jpg`/`.png` in the folder) are
copied once into `covers/` (named after their content); the page loads them with `file://`, `media.metadata.cover`
gets a data URL (only for covers up to 512 KB). The scan runs in the background, its progress is in `music.state.scan`
and on the page.

## Page

- **Tabs** Albums, Artists, Songs, Playlists, Folders, all as the same grid of square tiles (3–6 per row, default 4;
  the gear opens the settings: tiles per row, the sources, read the library again). Each tile has a badge for its
  type at the top left and a marker at the top right when it holds the track that plays. Artists, playlists and
  folders show a 2×2 mosaic of their album covers; without a cover the initials of the name.
- **Songs:** sort chips (A–Z, artist, recently added) and "Shuffle all".
- **Playlists:** "New playlist" as the first tile, the type (M3U, PLS, XSPF, own) on each tile.
- **Folders:** path bar (each part can be tapped), back, "Play folder", the subfolders as tiles and the music files as
  rows.
- **Album / artist / playlist page:** Play, Shuffle, Add to playlist and the tracks (own playlists: reorder, rename,
  delete).
- **Long press** on a tile or row: Play, Play next, Add to queue, Add to playlist.
- **Mini bar** while there is a track: cover, title and artist; previous, play/pause and next in the centre; mode and
  time on the right; a thin progress line. A tap opens the player.
- **Player:** cover, title, artist, album and source; "Up next" (tap to jump there, drag the handle to reorder); the
  seek bar with both times; mode, previous, play/pause, next, repeat. The mode button cycles Order → Shuffle → Random
  (with a short notice).
- Empty state ("Plug in a USB stick with music") and the scan progress.

The icons are drawn for the plugin (`qml/Icons.js`, 24×24).

## Queue and modes

`bin/playqueue.py` (pure logic, tested with a seed):

- **Order:** the tracks in the order of the album, playlist, folder or sort.
- **Shuffle:** every track once per round in a random order; with repeat "all" the next round starts (its first track
  is not the last one of the round before).
- **Random:** draws freely from all tracks of the context (also repeats), 10 tracks ahead, so "Up next" shows them.
- **Repeat:** off, all, one (one: the track repeats on its own, next/previous still move on).
- **Previous:** after 3 s the track starts again, before that the previous track (in shuffle and random the one that
  played before).
- "Play next" puts a track after the current one, "Add to queue" at the end (in shuffle: somewhere in the rest of the
  round).

The queue is saved per source (`queues.json`): a stick that comes back continues where it was (paused).

## Playback

`bin/player.py` starts `mpv --idle --no-video --gapless-audio=yes ...` with a JSON IPC socket. Only the current and
the next track are in mpv's playlist, so the plugin keeps the queue and mpv still plays gaplessly. A file that cannot
be played is skipped (with a notice).

- **Media source** `music`: `media.metadata` / `media.status` (home page, Bluetooth car audio). The media keys
  (`media.play_pause`, `media.next`, ...) work while the music is the current media source.
- **Pause** when Android Auto or another local source starts playing (`pauseForAndroidAuto`).
- **Stick pulled:** when the stick of the track that plays is pulled, the music stops.
- **Actions** for steering wheel buttons: `music.toggle`, `music.next`, `music.previous`.

## Playlists

`bin/playlists.py` reads M3U, M3U8, PLS and XSPF (relative and absolute paths, Windows paths with backslashes and
drive letters, `file://` URLs, case-insensitive matches; an absolute path from another computer is matched by its
longest suffix that exists on the stick). Entries that are not on the stick are shown dimmed; internet streams are
ignored.

Own playlists are `Playlists/<name>.m3u8` on the stick (or in the head unit folder), with paths relative to the
playlist, so they also play on other players. On a stick that is mounted read-only they are written with
`pkexec openhu-cli usb write <stick> Playlists/<name>.m3u8` (the content on stdin). `openhu-cli` can only write, so
deleting or renaming a playlist of a read-only stick hides the old one on the head unit (`hiddenPlaylists`).

## Interface

State `music.state`, commands `music.command`, queries `music.query` → `music.result` and the configuration: see the
head of [`bin/media.py`](bin/media.py). Examples:

```
bus.emit {"topic": "music.command", "data": {"cmd": "playItems", "context": {"kind": "songs"}, "mode": "shuffle"}}
bus.emit {"topic": "music.query", "data": {"id": "q1", "cmd": "albums", "offset": 0, "limit": 50}}
  → event "music.result" {"id": "q1", "cmd": "albums", "ok": true, "total": 6, "items": [...]}
```

Configuration (`config.json` in the plugin data dir):

| Key | Default | |
|---|---|---|
| `columns` | `4` | tiles per row (3–6), set on the page |
| `folders` | `[]` | more music folders |
| `pauseForAndroidAuto` | `true` | pause when Android Auto or another source plays |
| `mediaRoot` | `/run/media` | where sticks are mounted |
| `mpv` | `mpv` | the program |

## Development

- `tools/fake-mpv/mpv`: answers mpv's JSON IPC with a clock instead of sound (`FAKE_MPV_DURATION` seconds per file,
  files ending in `.broken` fail). Set `"mpv": "<path>/tools/fake-mpv/mpv"` in `config.json`.
- `tools/make-test-music.py <folder>`: a test stick with tagged MP3/FLAC/Ogg/M4A/WAV files (tones from `ffmpeg`), own
  generated covers, nested folders, an M3U8 and a PLS playlist. Set `mediaRoot` to its parent folder.

Tests (`python3 -m unittest discover -s tests`): queue modes, playlists, library scan (with the test music, needs
`ffmpeg` and mutagen), player with the fake mpv, the plugin process (media source, sticks, commands, queries).
