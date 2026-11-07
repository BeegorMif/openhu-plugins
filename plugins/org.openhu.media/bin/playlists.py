"""Playlist files (tests/test_playlists.py): reading M3U/M3U8 (#EXTINF), PLS and XSPF, writing the own playlists as
Playlists/<name>.m3u8 with relative paths (they work in other players too).

Paths in playlists: relative to the playlist's folder, absolute (also of another computer or mount point: the part
that exists on the source is found), file:// URLs, Windows paths with backslashes and drive letters. FAT sticks
do not care about case, playlists made on Windows often do not match it: each part of the path is matched without
case when the exact one does not exist. Other URLs (http, ...) are ignored: plugins use no internet services.

Writing: directly when the folder is writable (the data folder, Docker, a writable stick), otherwise (USB sticks
are mounted read-only by OpenHU OS) through "pkexec openhu-cli usb write <stick> Playlists/<name>.m3u8" with the
content on stdin (openhu-os#42).
"""

import os
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ElementTree

KINDS = {".m3u": "m3u", ".m3u8": "m3u", ".pls": "pls", ".xspf": "xspf"}
OWN_FOLDER = "Playlists"
OWN_EXTENSION = ".m3u8"
# what the OS writes (usb-stick write): at most 1 MB, one file name of at most 200 bytes
MAX_BYTES = 1024 * 1024
MAX_NAME_BYTES = 200
URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


class PlaylistError(Exception):
    pass


def kind_of(path):
    """"m3u" / "pls" / "xspf" for a playlist file name, None for anything else."""
    return KINDS.get(os.path.splitext(path)[1].lower())


def decode(data):
    """Bytes of a playlist file as text: UTF-8 (with or without BOM), else Latin-1 (old .m3u files)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_m3u(text):
    """[(path, title)]: title from #EXTINF ("Artist - Title"), "" without one."""
    entries, title = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.upper().startswith("#EXTINF:"):
                title = line.split(",", 1)[1].strip() if "," in line else ""
            continue
        entries.append((line, title))
        title = ""
    return entries


def parse_pls(text):
    files, titles = {}, {}
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"^(File|Title)(\d+)\s*=\s*(.*)$", line, re.IGNORECASE)
        if not match:
            continue
        table = files if match.group(1).lower() == "file" else titles
        table[int(match.group(2))] = match.group(3).strip()
    return [(files[number], titles.get(number, "")) for number in sorted(files) if files[number]]


def parse_xspf(text):
    try:
        root = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
        return []
    entries = []
    for track in root.iter():
        if not track.tag.endswith("track"):
            continue
        location = title = creator = ""
        for child in track:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "location" and not location:
                location = (child.text or "").strip()
            elif name == "title":
                title = (child.text or "").strip()
            elif name == "creator":
                creator = (child.text or "").strip()
        if location and not location.lower().startswith("file:") and not is_url(location):
            # a relative URI: percent-encoded
            location = urllib.parse.unquote(location)
        if location:
            entries.append((location, " - ".join(part for part in (creator, title) if part)))
    return entries


def parse(text, kind):
    return {"m3u": parse_m3u, "pls": parse_pls, "xspf": parse_xspf}.get(kind, lambda text: [])(text)


def is_url(entry):
    """A URL that is not a local file (ignored)."""
    return bool(URL.match(entry)) and not entry.lower().startswith("file:")


def _match_part(directory, part, cache):
    """The entry of directory named part, without case if the exact one does not exist (FAT, Windows lists)."""
    exact = os.path.join(directory, part)
    if os.path.lexists(exact):
        return exact
    if directory not in cache:
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        cache[directory] = {}
        for name in names:
            cache[directory].setdefault(name.casefold(), name)
    name = cache[directory].get(part.casefold())
    return os.path.join(directory, name) if name else None


def find(base, parts, cache=None):
    """base joined with parts, each matched without case if needed; None if it does not exist."""
    cache = {} if cache is None else cache
    path = base
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            path = os.path.dirname(path)
            continue
        path = _match_part(path, part, cache)
        if path is None:
            return None
    return path if os.path.isfile(path) else None


def resolve(entry, playlist_dir, root, cache=None):
    """Absolute path of a playlist entry on the source (root: the source's folder), None if it is not there or a URL.
    Relative entries are relative to the playlist's folder; absolute ones are taken as they are when they exist,
    else the longest end of them that exists under root (a playlist made on a computer, "/media/usb/Music/a.mp3"
    or "D:\\Music\\a.mp3" on the stick "Music/a.mp3")."""
    entry = entry.strip()
    if not entry or is_url(entry):
        return None
    if entry.lower().startswith("file:"):
        entry = urllib.parse.unquote(urllib.parse.urlparse(entry).path)
        if DRIVE.match(entry.lstrip("/")):
            entry = entry.lstrip("/")
    entry = entry.replace("\\", "/")
    cache = {} if cache is None else cache
    drive = bool(DRIVE.match(entry))
    if drive:
        entry = entry[2:]
    if not entry.startswith("/"):
        return find(playlist_dir, entry.split("/"), cache)
    if not drive and os.path.isfile(entry):
        return os.path.normpath(entry)
    parts = [part for part in entry.split("/") if part]
    for start in range(len(parts)):
        found = find(root, parts[start:], cache)
        if found:
            return found
    return None


def read(path, root):
    """A playlist file -> [(absolute path or None, raw entry, title)] (None: not found on the source or a URL)."""
    with open(path, "rb") as file:
        text = decode(file.read(MAX_BYTES * 4))
    cache = {}
    directory = os.path.dirname(path)
    return [(resolve(entry, directory, root, cache), entry, title) for entry, title in parse(text, kind_of(path))]


def valid_name(name):
    """A playlist name that the OS accepts as Playlists/<name>.m3u8 (and FAT can store); else PlaylistError."""
    name = (name or "").strip()
    if not name or name.startswith(".") or re.search(r'[/\\<>:"|?*]', name) or any(ord(c) < 32 for c in name):
        raise PlaylistError("invalid name")
    if len((name + OWN_EXTENSION).encode("utf-8")) > MAX_NAME_BYTES:
        raise PlaylistError("name too long")
    return name


def own_path(root, name):
    return os.path.join(root, OWN_FOLDER, valid_name(name) + OWN_EXTENSION)


def is_own(root, path):
    """An own playlist: Playlists/<name>.m3u8 at the top of the source."""
    relative = os.path.relpath(path, root).replace(os.sep, "/")
    return relative.count("/") == 1 and relative.split("/")[0] == OWN_FOLDER and relative.lower().endswith(OWN_EXTENSION)


def relative(playlist_path, path):
    """An absolute track path as an entry of the playlist: relative to its folder, with forward slashes."""
    return os.path.relpath(path, os.path.dirname(playlist_path)).replace(os.sep, "/")


def format_m3u8(entries):
    """Text of an own playlist. entries: [(entry, seconds, "Artist - Title")], the entry a path relative to the
    playlist's folder (relative()) or an entry kept from the file as it was."""
    lines = ["#EXTM3U"]
    for entry, seconds, title in entries:
        lines.append("#EXTINF:%d,%s" % (round(seconds) if seconds else -1, (title or "").replace("\n", " ")))
        lines.append(entry.replace("\n", " "))
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise PlaylistError("playlist too large")
    return text


def write_direct(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = os.path.join(os.path.dirname(path), ".openhu-write.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def usb_write_command(stick, name):
    return ["pkexec", "openhu-cli", "usb", "write", stick, "%s/%s%s" % (OWN_FOLDER, name, OWN_EXTENSION)]


def write(root, name, text, stick=None, run=subprocess.run):
    """Writes Playlists/<name>.m3u8 on the source: directly if possible, else (a read-only USB stick, its name in
    /run/media) through openhu-cli. Returns "direct" or "usb"; PlaylistError on failure."""
    path = own_path(root, name)
    try:
        write_direct(path, text)
        return "direct"
    except OSError as error:
        if not stick:
            raise PlaylistError(str(error))
    try:
        result = run(usb_write_command(stick, valid_name(name)), input=text.encode("utf-8"), capture_output=True,
                     timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise PlaylistError(str(error))
    if result.returncode != 0:
        message = (result.stderr or b"").decode(errors="replace").strip().splitlines()
        raise PlaylistError(message[-1] if message else "openhu-cli usb write failed")
    return "usb"


def delete(root, name):
    """Deletes an own playlist; False if the source is read-only (openhu-cli can only write playlists)."""
    try:
        os.remove(own_path(root, name))
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False
