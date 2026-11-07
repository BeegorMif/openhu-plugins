#!/usr/bin/env python3
"""Makes a small music folder for tests and development: generated tones (ffmpeg) in mp3, flac, ogg, opus, m4a
and wav with mutagen tags (one without any), embedded covers and a cover.png in a folder, nested folders, an
M3U8 and a PLS playlist. Made-up artists, own drawn covers (no real music, no third-party pictures).

    tools/make-test-music.py <folder> [--seconds 3]

Needs ffmpeg and python3-mutagen. The tests use it as a module (make(folder, seconds)).
"""

import argparse
import os
import struct
import subprocess
import sys
import zlib

# (folder, file, title, artist, album artist, album, track, year, cover: "embedded" | "folder" | None, tone Hz)
TRACKS = [
    ("Music/Aurora Lane/Northern Lights", "01 First Light.mp3", "First Light", "Aurora Lane", "", "Northern Lights",
     1, 2021, "embedded", 330),
    ("Music/Aurora Lane/Northern Lights", "02 Polar Night.mp3", "Polar Night", "Aurora Lane", "", "Northern Lights",
     2, 2021, "embedded", 392),
    ("Music/Aurora Lane/Northern Lights", "03 Green Sky.mp3", "Green Sky", "Aurora Lane", "", "Northern Lights",
     3, 2021, "embedded", 440),
    ("Music/Aurora Lane/Harbour", "01 Low Tide.flac", "Low Tide", "Aurora Lane", "", "Harbour", 1, 2023,
     "embedded", 262),
    ("Music/Aurora Lane/Harbour", "02 Lighthouse.flac", "Lighthouse", "Aurora Lane", "", "Harbour", 2, 2023,
     "embedded", 294),
    ("Music/The Pebbles/Road Songs", "01 Mile Marker.ogg", "Mile Marker", "The Pebbles", "", "Road Songs", 1, 2019,
     "folder", 349),
    ("Music/The Pebbles/Road Songs", "02 Overpass.ogg", "Overpass", "The Pebbles", "", "Road Songs", 2, 2019,
     "folder", 370),
    ("Music/Compilations/Summer Drive", "01 Coast Road.opus", "Coast Road", "Marlo Vance", "Various Artists",
     "Summer Drive", 1, 2024, None, 415),
    ("Music/Compilations/Summer Drive", "02 Dunes.m4a", "Dunes", "Kit Harrow", "Various Artists", "Summer Drive",
     2, 2024, "embedded", 466),
    ("Music/Loose", "untagged recording.wav", None, None, None, None, 0, 0, None, 523),
    ("Music/Loose/Deep/Nested/Folder", "Echo.mp3", "Echo", "Quiet Hours", "", "Echo", 1, 2020, None, 587),
]
PLAYLISTS = {
    "Music/Road trip.m3u8": "#EXTM3U\n#EXTINF:3,The Pebbles - Mile Marker\nThe Pebbles/Road Songs/01 Mile Marker.ogg\n"
                            "#EXTINF:3,Aurora Lane - Green Sky\nAURORA LANE\\NORTHERN LIGHTS\\03 GREEN SKY.MP3\n"
                            "http://example.invalid/stream.mp3\n#EXTINF:3,Gone - Missing\nMissing/gone.mp3\n",
    "Music/Evening.pls": "[playlist]\nFile1=Aurora Lane/Harbour/02 Lighthouse.flac\nTitle1=Lighthouse\n"
                         "File2=Compilations/Summer Drive/02 Dunes.m4a\nNumberOfEntries=2\nVersion=2\n",
}
COLORS = {
    "Northern Lights": ((18, 64, 92), (98, 214, 160)),
    "Harbour": ((40, 52, 112), (232, 150, 92)),
    "Road Songs": ((104, 40, 52), (246, 196, 92)),
    "Dunes": ((92, 64, 24), (240, 210, 150)),
}


def png(size, top, bottom, rings=True):
    """A PNG cover: a vertical gradient with a few circles (an own drawing)."""
    rows = []
    centre = size / 2
    for y in range(size):
        t = y / (size - 1)
        base = [round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
        row = bytearray(b"\x00")
        for x in range(size):
            pixel = base
            if rings:
                distance = ((x - centre) ** 2 + (y - centre * 1.1) ** 2) ** 0.5
                if int(distance / (size / 12)) % 2 == 0 and distance < size * 0.42:
                    pixel = [min(255, value + 38) for value in base]
            row += bytes(pixel)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def tone(path, frequency, seconds):
    codec = {".mp3": ["-c:a", "libmp3lame", "-b:a", "64k"], ".flac": ["-c:a", "flac"],
             ".ogg": ["-c:a", "libvorbis", "-q:a", "1"], ".opus": ["-c:a", "libopus", "-b:a", "32k"],
             ".m4a": ["-c:a", "aac", "-b:a", "64k"], ".wav": ["-c:a", "pcm_s16le"]}[os.path.splitext(path)[1]]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=%d:duration=%s:sample_rate=44100" % (frequency, seconds), "-ac", "2",
                    "-map_metadata", "-1"] + codec + [path], check=True)


def tag(path, title, artist, albumartist, album, track, year, cover):
    import mutagen
    from mutagen.flac import Picture
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
    from mutagen.mp4 import MP4Cover
    extension = os.path.splitext(path)[1]
    if extension == ".mp3":
        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        if albumartist:
            tags.add(TPE2(encoding=3, text=albumartist))
        tags.add(TALB(encoding=3, text=album))
        tags.add(TRCK(encoding=3, text="%d/3" % track))
        tags.add(TDRC(encoding=3, text=str(year)))
        if cover:
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=cover))
        tags.save(path)
        return
    audio = mutagen.File(path)
    if extension == ".m4a":
        audio["\xa9nam"], audio["\xa9ART"], audio["\xa9alb"] = [title], [artist], [album]
        if albumartist:
            audio["aART"] = [albumartist]
        audio["trkn"] = [(track, 2)]
        audio["\xa9day"] = [str(year)]
        if cover:
            audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_PNG)]
        audio.save()
        return
    audio["title"], audio["artist"], audio["album"] = title, artist, album
    if albumartist:
        audio["albumartist"] = albumartist
    audio["tracknumber"], audio["date"] = str(track), str(year)
    if cover:
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, "image/png", cover
        picture.width = picture.height = 1
        if extension == ".flac":
            audio.add_picture(picture)
        else:
            import base64
            audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode()]
    audio.save()


def make(folder, seconds=3, size=160):
    for directory, name, title, artist, albumartist, album, track, year, cover, frequency in TRACKS:
        path = os.path.join(folder, *directory.split("/"), name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tone(path, frequency, seconds)
        top, bottom = COLORS.get(album, ((60, 60, 60), (160, 160, 160)))
        if cover == "folder":
            with open(os.path.join(os.path.dirname(path), "cover.png"), "wb") as file:
                file.write(png(size, top, bottom))
        if title is not None:
            tag(path, title, artist, albumartist, album, track, year,
                png(size, top, bottom) if cover == "embedded" else None)
    for name, text in PLAYLISTS.items():
        with open(os.path.join(folder, *name.split("/")), "w", encoding="utf-8") as file:
            file.write(text)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder")
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    make(args.folder, args.seconds)
    print("%d tracks, %d playlists in %s" % (len(TRACKS), len(PLAYLISTS), args.folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
