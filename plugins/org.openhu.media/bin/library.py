"""The music library (tests/test_library.py): sources, the SQLite index of their tags, covers and playlist files.

Sources: every mount under /run/media (OpenHU OS mounts USB sticks there read-only), $OPENHU_DATA_DIR/Music and
the folders of the config list "folders". A stick's key is its UUID (else its label, else its name in
/run/media), so its index, queue and playlists stay its own when it gets another device name next time.

Index (library.db in the data dir): one row per music file with its tags (mutagen: title, artist, album artist,
album, track and disc number, year, duration) and cover, kept per source. A scan rereads only files whose mtime or
size changed and drops the rows of files that are gone. Tracks are named "<source key>:<path on the source>".

Covers: embedded pictures (ID3 APIC, FLAC/Vorbis PICTURE, MP4 covr) or cover/folder/front .jpg/.png in the folder,
copied once into covers/ in the data dir (named after their content); the page loads them from there with file://.
"""

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time

import playlists

log = logging.getLogger("library")

AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma")
COVER_FILES = ("cover", "folder", "front")
COVER_EXTENSIONS = (".jpg", ".jpeg", ".png")
# media.metadata.cover (data URL) like the radio's logos; the page loads the file itself, so any size works there
MAX_COVER_URL_BYTES = 512 * 1024
SCHEMA_VERSION = 1
LOCAL, USB, FOLDER = "local", "usb", "folder"


# --- tags -------------------------------------------------------------------------------

def _first(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if hasattr(value, "text"):  # ID3 frames
        value = value.text[0] if value.text else ""
    if hasattr(value, "value"):  # ASF attributes
        value = value.value
    return str(value).strip() if value is not None else ""


def _number(value):
    """"3/12" -> 3, MP4 (3, 12) -> 3, "" -> 0"""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], tuple):
        value = value[0]
    if isinstance(value, tuple):
        return int(value[0]) if value and isinstance(value[0], int) else 0
    text = _first(value).split("/")[0].strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def _year(value):
    text = _first(value)
    return int(text[:4]) if text[:4].isdigit() else 0


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


# tag names: Vorbis comments/APE, ASF (WMA) and MP4 atoms; ID3 frames below
TAG_NAMES = {
    "title": ("title", "Title", "\xa9nam"),
    "artist": ("artist", "Author", "\xa9ART"),
    "albumartist": ("albumartist", "album artist", "WM/AlbumArtist", "aART"),
    "album": ("album", "WM/AlbumTitle", "\xa9alb"),
    "track": ("tracknumber", "WM/TrackNumber", "trkn"),
    "disc": ("discnumber", "WM/PartOfSet", "disk"),
    "year": ("date", "year", "WM/Year", "\xa9day"),
}
ID3_FRAMES = {"title": "TIT2", "artist": "TPE1", "albumartist": "TPE2", "album": "TALB", "track": "TRCK",
              "disc": "TPOS", "year": "TDRC"}


def _lookup(tags, names):
    if tags is None:
        return ""
    for name in names:
        for candidate in (name, name.upper()):
            try:
                if candidate in tags:
                    return tags[candidate]
            except (TypeError, ValueError, KeyError):
                pass
    return ""


def _embedded_cover(audio):
    """Bytes of the first embedded PNG/JPEG picture (front cover first), None without one."""
    pictures = []
    tags = getattr(audio, "tags", None)
    try:
        if tags is not None and hasattr(tags, "getall"):  # ID3 (mp3, wav, aiff)
            pictures += [(frame.type != 3, frame.data) for frame in tags.getall("APIC")]
        for picture in getattr(audio, "pictures", []) or []:  # FLAC
            pictures.append((picture.type != 3, picture.data))
        if tags is not None and "metadata_block_picture" in tags:  # Ogg Vorbis/Opus
            from mutagen.flac import Picture
            for value in tags["metadata_block_picture"]:
                try:
                    picture = Picture(base64.b64decode(value))
                    pictures.append((picture.type != 3, picture.data))
                except (ValueError, TypeError):
                    pass
        if tags is not None and "covr" in tags:  # MP4
            pictures += [(False, bytes(value)) for value in tags["covr"]]
        if tags is not None and "WM/Picture" in tags:  # ASF: type, size, mime, description, data
            for value in tags["WM/Picture"]:
                data = bytes(value.value)
                pictures += [(data[0] != 3, data[index:]) for index in (data.find(b"\x89PNG"), data.find(b"\xff\xd8\xff"))
                             if index > 0]
    except Exception as error:  # odd tags must not stop the scan
        log.debug("cover: %s", error)
    for _, data in sorted(pictures, key=lambda item: item[0]):
        if data and image_type(data):
            return data
    return None


def read_tags(path):
    """Tags of a music file -> ({title, artist, albumartist, album, track, disc, year, duration}, cover bytes or
    None). Missing tags are "" / 0; None for a file mutagen cannot read."""
    try:
        import mutagen
    except ImportError:
        return None, None
    try:
        audio = mutagen.File(path)
    except Exception as error:
        log.info("%s: %s", path, error)
        return None, None
    if audio is None:
        return None, None
    tags = audio.tags
    values = {}
    for key, names in TAG_NAMES.items():
        value = _lookup(tags, names)
        if value == "" and tags is not None and hasattr(tags, "getall"):
            frames = tags.getall(ID3_FRAMES[key])
            value = frames[0] if frames else ""
        values[key] = value
    result = {
        "title": _first(values["title"]),
        "artist": _first(values["artist"]),
        "albumartist": _first(values["albumartist"]),
        "album": _first(values["album"]),
        "track": _number(values["track"]),
        "disc": _number(values["disc"]),
        "year": _year(values["year"]),
        "duration": float(getattr(getattr(audio, "info", None), "length", 0) or 0),
    }
    return result, _embedded_cover(audio)


# --- sources ------------------------------------------------------------------------------

class Source:
    def __init__(self, key, name, path, kind, stick=None):
        self.key, self.name, self.path, self.kind = key, name, os.path.normpath(path), kind
        # name in /run/media of a USB stick (for openhu-cli usb write)
        self.stick = stick

    def to_dict(self):
        return {"key": self.key, "name": self.name, "kind": self.kind}

    def __eq__(self, other):
        return isinstance(other, Source) and (self.key, self.path) == (other.key, other.path)

    def __hash__(self):
        return hash((self.key, self.path))

    def __repr__(self):
        return "Source(%s, %s)" % (self.key, self.path)


def _unescape_udev(name):
    """/dev/disk/by-label names: "\\x20" -> " " """
    try:
        return name.encode("latin-1").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeError, ValueError):
        return name


def mount_devices(mounts="/proc/self/mounts"):
    """mount point -> device"""
    result = {}
    try:
        with open(mounts) as file:
            for line in file:
                parts = line.split()
                if len(parts) >= 2:
                    result[parts[1].replace("\\040", " ")] = parts[0]
    except OSError:
        pass
    return result


def disk_names(device, disk_dir="/dev/disk"):
    """(uuid, label) of a device from the udev links (readable without root), "" if unknown."""
    found = {}
    real = os.path.realpath(device)
    for kind in ("by-uuid", "by-label"):
        folder = os.path.join(disk_dir, kind)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if os.path.realpath(os.path.join(folder, name)) == real:
                found[kind] = _unescape_udev(name)
                break
    return found.get("by-uuid", ""), found.get("by-label", "")


def safe_key(text):
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in text)[:80]


def find_sources(media_root, local_dir, folders, devices=None, disk_dir="/dev/disk"):
    """The sources that are there now: the sticks in media_root, local_dir, the config folders."""
    sources = []
    devices = mount_devices() if devices is None else devices
    try:
        sticks = sorted(os.listdir(media_root))
    except OSError:
        sticks = []
    for name in sticks:
        path = os.path.join(media_root, name)
        if name.startswith(".") or not os.path.isdir(path):
            continue
        uuid, label = disk_names(devices[path], disk_dir) if path in devices else ("", "")
        key = "uuid-" + safe_key(uuid) if uuid else "label-" + safe_key(label) if label else "usb-" + safe_key(name)
        sources.append(Source(key, label or name, path, USB, stick=name))
    if local_dir and os.path.isdir(local_dir):
        sources.append(Source(LOCAL, "", local_dir, LOCAL))
    for folder in folders or []:
        folder = os.path.expanduser(str(folder))
        if os.path.isdir(folder):
            key = "folder-" + hashlib.sha1(os.path.abspath(folder).encode()).hexdigest()[:10]
            sources.append(Source(key, os.path.basename(os.path.normpath(folder)) or folder, folder, FOLDER))
    # one key once (the same stick twice is not possible; two config folders with the same path are)
    seen, result = set(), []
    for source in sources:
        if source.key not in seen:
            seen.add(source.key)
            result.append(source)
    return result


# --- the index ------------------------------------------------------------------------------

def track_id(source_key, path):
    return "%s:%s" % (source_key, path)


def split_id(track):
    source, _, path = str(track).partition(":")
    return source, path


def album_id(artist, album):
    return json.dumps([artist, album], ensure_ascii=False)


def parse_album_id(value):
    try:
        artist, album = json.loads(value)
        return str(artist), str(album)
    except (ValueError, TypeError):
        return None


TRACK_COLUMNS = "source, path, dir, title, artist, albumartist, aartist, album, track, disc, year, duration, cover, added"


class Library:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.cover_dir = os.path.join(data_dir, "covers")
        os.makedirs(self.cover_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "library.db")
        self.local = threading.local()
        self.sources = {}  # key -> Source, the ones that are there
        self.lock = threading.Lock()
        self.connections = []
        self._schema()

    # --- database ---

    def db(self):
        connection = getattr(self.local, "connection", None)
        if connection is None:
            # one connection per thread (the scan and the queries run in worker threads); closed together
            connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            with self.lock:
                self.connections.append(connection)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            self.local.connection = connection
        return connection

    def close(self):
        """Closes the connections of all threads (at the end)."""
        with self.lock:
            connections, self.connections = self.connections, []
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        self.local = threading.local()

    def _schema(self):
        db = self.db()
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            db.executescript("DROP TABLE IF EXISTS track; DROP TABLE IF EXISTS playlist; DROP TABLE IF EXISTS source;")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS track (
                source TEXT NOT NULL, path TEXT NOT NULL, dir TEXT NOT NULL, mtime REAL, size INTEGER,
                title TEXT, artist TEXT, albumartist TEXT, aartist TEXT, album TEXT, track INTEGER, disc INTEGER,
                year INTEGER, duration REAL, cover TEXT, added REAL,
                PRIMARY KEY (source, path)) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS track_album ON track (aartist, album);
            CREATE INDEX IF NOT EXISTS track_dir ON track (source, dir);
            CREATE TABLE IF NOT EXISTS playlist (
                source TEXT NOT NULL, path TEXT NOT NULL, mtime REAL, size INTEGER, kind TEXT, own INTEGER,
                name TEXT, entries TEXT,
                PRIMARY KEY (source, path)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS source (key TEXT PRIMARY KEY, name TEXT, seen REAL);
        """)
        db.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
        db.commit()

    def set_sources(self, sources):
        with self.lock:
            self.sources = {source.key: source for source in sources}
        db = self.db()
        for source in sources:
            db.execute("INSERT OR REPLACE INTO source VALUES (?, ?, ?)", (source.key, source.name, time.time()))
        db.commit()

    def active(self):
        with self.lock:
            return list(self.sources)

    def source(self, key):
        with self.lock:
            return self.sources.get(key)

    def _where(self, alias=""):
        keys = self.active()
        return "%ssource IN (%s)" % (alias, ",".join("?" * len(keys)) or "''"), keys

    # --- scan ---

    def store_cover(self, data):
        """Cover bytes -> file name in covers/ (written once per content)."""
        kind = image_type(data)
        if not kind:
            return ""
        name = hashlib.sha1(data).hexdigest()[:24] + "." + kind
        path = os.path.join(self.cover_dir, name)
        if not os.path.exists(path):
            temporary = path + ".tmp"
            with open(temporary, "wb") as file:
                file.write(data)
            os.replace(temporary, path)
        return name

    def folder_cover(self, directory, names, cache):
        """cover/folder/front .jpg/.png of a folder -> cache file name, "" without one."""
        if directory in cache:
            return cache[directory]
        result = ""
        lower = {name.lower(): name for name in names}
        for stem in COVER_FILES:
            for extension in COVER_EXTENSIONS:
                name = lower.get(stem + extension)
                if name:
                    try:
                        with open(os.path.join(directory, name), "rb") as file:
                            result = self.store_cover(file.read(16 * 1024 * 1024))
                    except OSError:
                        result = ""
                    if result:
                        break
            if result:
                break
        cache[directory] = result
        return result

    def scan(self, source, progress=None, stopped=None):
        """Indexes a source (in a worker thread): new and changed files are read, gone ones dropped.
        progress(done, total) is called now and then; stopped() True cancels. -> (files, read)"""
        db = self.db()
        known = {row["path"]: (row["mtime"], row["size"]) for row in
                 db.execute("SELECT path, mtime, size FROM track WHERE source=?", (source.key,))}
        known_lists = {row["path"]: (row["mtime"], row["size"]) for row in
                       db.execute("SELECT path, mtime, size FROM playlist WHERE source=?", (source.key,))}
        files, lists, folder_names = [], [], {}
        for root, dirs, names in os.walk(source.path, onerror=lambda error: log.info("scan: %s", error)):
            dirs[:] = sorted(name for name in dirs if not name.startswith(".") and name != "System Volume Information")
            folder_names[root] = names
            for name in sorted(names):
                if name.startswith("."):
                    continue
                extension = os.path.splitext(name)[1].lower()
                if extension in AUDIO_EXTENSIONS:
                    files.append(os.path.join(root, name))
                elif extension in playlists.KINDS:
                    lists.append(os.path.join(root, name))
            if stopped and stopped():
                return 0, 0
        total, read, seen = len(files), 0, set()
        covers = {}
        if progress:
            progress(0, total)
        for done, path in enumerate(files, 1):
            relative = os.path.relpath(path, source.path).replace(os.sep, "/")
            seen.add(relative)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if known.get(relative) == (stat.st_mtime, stat.st_size):
                continue
            tags, embedded = read_tags(path)
            read += 1
            if tags is None:
                tags = {"title": "", "artist": "", "albumartist": "", "album": "", "track": 0, "disc": 0, "year": 0,
                        "duration": 0.0}
            directory = os.path.dirname(path)
            cover = self.store_cover(embedded) if embedded else ""
            if not cover:
                cover = self.folder_cover(directory, folder_names.get(directory, []), covers)
            folder = os.path.dirname(relative)
            title = tags["title"] or os.path.splitext(os.path.basename(path))[0]
            # without an album tag the folder is the album (music sorted in folders)
            album = tags["album"] or (os.path.basename(folder) if folder else source.name)
            aartist = tags["albumartist"] or tags["artist"]
            db.execute("""INSERT INTO track (source, path, dir, mtime, size, title, artist, albumartist, aartist, album,
                              track, disc, year, duration, cover, added)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                          ON CONFLICT (source, path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size,
                              title=excluded.title, artist=excluded.artist, albumartist=excluded.albumartist,
                              aartist=excluded.aartist, album=excluded.album, track=excluded.track,
                              disc=excluded.disc, year=excluded.year, duration=excluded.duration,
                              cover=excluded.cover""",
                       (source.key, relative, folder, stat.st_mtime, stat.st_size, title, tags["artist"],
                        tags["albumartist"], aartist, album, tags["track"], tags["disc"], tags["year"],
                        tags["duration"], cover, stat.st_mtime))
            if read % 100 == 0:
                db.commit()
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
            if stopped and stopped():
                db.commit()
                return total, read
        for relative in set(known) - seen:
            db.execute("DELETE FROM track WHERE source=? AND path=?", (source.key, relative))
        db.commit()
        # playlist files, after the tracks (their entries point to tracks)
        seen_lists = set()
        for path in lists:
            relative = os.path.relpath(path, source.path).replace(os.sep, "/")
            seen_lists.add(relative)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if known_lists.get(relative) == (stat.st_mtime, stat.st_size):
                continue
            self.index_playlist(source, path, stat)
        for relative in set(known_lists) - seen_lists:
            db.execute("DELETE FROM playlist WHERE source=? AND path=?", (source.key, relative))
        db.commit()
        if progress:
            progress(total, total)
        return total, read

    def index_playlist(self, source, path, stat=None):
        db = self.db()
        relative = os.path.relpath(path, source.path).replace(os.sep, "/")
        try:
            stat = stat or os.stat(path)
            entries = playlists.read(path, source.path)
        except OSError as error:
            log.info("playlist %s: %s", path, error)
            return
        stored = []
        for found, raw, title in entries:
            track = self.track_of_path(found) if found else ""
            if not found and playlists.is_url(raw):
                continue
            stored.append([track or "", title or os.path.splitext(os.path.basename(raw.replace("\\", "/")))[0]])
        own = playlists.is_own(source.path, path)
        name = os.path.splitext(os.path.basename(path))[0]
        db.execute("INSERT OR REPLACE INTO playlist VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (source.key, relative, stat.st_mtime, stat.st_size, playlists.kind_of(path), 1 if own else 0, name,
                    json.dumps(stored, ensure_ascii=False)))
        db.commit()

    def drop_playlist(self, source_key, relative):
        db = self.db()
        db.execute("DELETE FROM playlist WHERE source=? AND path=?", (source_key, relative))
        db.commit()

    def track_of_path(self, path):
        """Track id of an absolute path on one of the sources, "" if it is on none."""
        path = os.path.normpath(path)
        with self.lock:
            sources = list(self.sources.values())
        for source in sources:
            if path.startswith(source.path + os.sep):
                return track_id(source.key, os.path.relpath(path, source.path).replace(os.sep, "/"))
        return ""

    def file_of(self, track):
        """Absolute path of a track, None if its source is not there."""
        key, relative = split_id(track)
        source = self.source(key)
        return os.path.join(source.path, *relative.split("/")) if source and relative else None

    def available(self, track):
        path = self.file_of(track)
        return bool(path) and os.path.exists(path)

    # --- reading ---

    def cover_url(self, name):
        return "file://" + os.path.join(self.cover_dir, name) if name else ""

    def cover_data_url(self, name):
        """media.metadata.cover: data URL of a cover of at most MAX_COVER_URL_BYTES, "" otherwise."""
        if not name:
            return ""
        path = os.path.join(self.cover_dir, name)
        try:
            if os.path.getsize(path) > MAX_COVER_URL_BYTES:
                return ""
            with open(path, "rb") as file:
                data = file.read()
        except OSError:
            return ""
        kind = image_type(data)
        return "data:image/%s;base64,%s" % ("jpeg" if kind == "jpg" else kind, base64.b64encode(data).decode()) \
            if kind else ""

    def row(self, row):
        """A track as the page shows it."""
        return {"kind": "song", "id": track_id(row["source"], row["path"]), "title": row["title"] or "", "artist": row["artist"] or "",
                "album": row["album"] or "", "albumArtist": row["aartist"] or "",
                "albumId": album_id(row["aartist"] or "", row["album"] or ""),
                "duration": round(row["duration"] or 0, 1), "track": row["track"] or 0, "disc": row["disc"] or 0,
                "cover": self.cover_url(row["cover"]), "coverName": row["cover"] or "", "source": row["source"],
                "folder": row["dir"], "year": row["year"] or 0, "available": True}

    def track(self, track):
        """One track (also of a source that is not there: from the index), None if unknown."""
        key, relative = split_id(track)
        found = self.db().execute("SELECT %s FROM track WHERE source=? AND path=?" % TRACK_COLUMNS,
                                  (key, relative)).fetchone()
        if found is None:
            return None
        result = self.row(found)
        result["available"] = key in self.active()
        return result

    def tracks(self, ids):
        """Tracks of a list of ids in its order; unknown ones as {"id", "available": False}."""
        result = []
        for track in ids:
            row = self.track(track) if track else None
            result.append(row or {"id": track or "", "title": "", "artist": "", "album": "", "duration": 0,
                                  "cover": "", "available": False})
        return result

    def count(self):
        where, keys = self._where()
        return self.db().execute("SELECT COUNT(*) FROM track WHERE " + where, keys).fetchone()[0]

    def source_counts(self):
        where, keys = self._where()
        return {row[0]: row[1] for row in
                self.db().execute("SELECT source, COUNT(*) FROM track WHERE %s GROUP BY source" % where, keys)}

    def _covers(self, condition, params, limit=4):
        """Up to limit covers of different albums (artist, playlist, folder tiles)."""
        rows = self.db().execute(
            "SELECT MAX(cover) AS c FROM track WHERE %s AND cover != '' GROUP BY aartist, album "
            "ORDER BY MIN(year), album LIMIT %d" % (condition, limit), params)
        return [self.cover_url(row["c"]) for row in rows]

    def albums(self, offset=0, limit=60, artist=None):
        where, keys = self._where()
        if artist is not None:
            where += " AND aartist=?"
            keys = keys + [artist]
        total = self.db().execute("SELECT COUNT(*) FROM (SELECT 1 FROM track WHERE %s GROUP BY aartist, album)"
                                  % where, keys).fetchone()[0]
        order = "MIN(year), album COLLATE NOCASE" if artist is not None else "album COLLATE NOCASE, aartist"
        rows = self.db().execute(
            "SELECT aartist, album, COUNT(*) AS n, MAX(cover) AS c, MIN(year) AS y, SUM(duration) AS d FROM track "
            "WHERE %s GROUP BY aartist, album ORDER BY %s LIMIT ? OFFSET ?" % (where, order),
            keys + [int(limit), int(offset)])
        items = [{"kind": "album", "id": album_id(row["aartist"] or "", row["album"] or ""), "title": row["album"] or "",
                  "subtitle": row["aartist"] or "", "covers": [self.cover_url(row["c"])] if row["c"] else [],
                  "count": row["n"], "year": row["y"] or 0, "duration": round(row["d"] or 0)} for row in rows]
        return {"total": total, "items": items}

    def artists(self, offset=0, limit=60):
        where, keys = self._where()
        total = self.db().execute("SELECT COUNT(DISTINCT aartist) FROM track WHERE " + where, keys).fetchone()[0]
        rows = self.db().execute(
            "SELECT aartist, COUNT(DISTINCT album) AS albums, COUNT(*) AS n FROM track WHERE %s GROUP BY aartist "
            "ORDER BY aartist = '', aartist COLLATE NOCASE LIMIT ? OFFSET ?" % where, keys + [int(limit), int(offset)])
        items = []
        for row in rows:
            items.append({"kind": "artist", "id": row["aartist"] or "", "title": row["aartist"] or "",
                          "albums": row["albums"], "count": row["n"],
                          "covers": self._covers(where + " AND aartist=?", keys + [row["aartist"]])})
        return {"total": total, "items": items}

    SONG_ORDER = {
        "title": "title COLLATE NOCASE, aartist COLLATE NOCASE",
        "artist": "aartist = '', aartist COLLATE NOCASE, album COLLATE NOCASE, disc, track, title COLLATE NOCASE",
        "added": "added DESC, source, path",
    }

    def songs(self, sort="title", offset=0, limit=60):
        where, keys = self._where()
        order = self.SONG_ORDER.get(sort, self.SONG_ORDER["title"])
        total = self.db().execute("SELECT COUNT(*) FROM track WHERE " + where, keys).fetchone()[0]
        rows = self.db().execute("SELECT %s FROM track WHERE %s ORDER BY %s LIMIT ? OFFSET ?"
                                 % (TRACK_COLUMNS, where, order), keys + [int(limit), int(offset)])
        return {"total": total, "items": [self.row(row) for row in rows]}

    def song_ids(self, sort="title"):
        where, keys = self._where()
        order = self.SONG_ORDER.get(sort, self.SONG_ORDER["title"])
        return [track_id(row[0], row[1]) for row in
                self.db().execute("SELECT source, path FROM track WHERE %s ORDER BY %s" % (where, order), keys)]

    def album_tracks(self, value):
        parsed = parse_album_id(value)
        if parsed is None:
            return []
        where, keys = self._where()
        rows = self.db().execute(
            "SELECT %s FROM track WHERE %s AND aartist=? AND album=? ORDER BY disc, track, path"
            % (TRACK_COLUMNS, where), keys + list(parsed))
        return [self.row(row) for row in rows]

    def album(self, value):
        tracks = self.album_tracks(value)
        parsed = parse_album_id(value) or ("", "")
        cover = next((track["cover"] for track in tracks if track["cover"]), "")
        return {"id": value, "kind": "album", "title": parsed[1], "artist": parsed[0], "cover": cover,
                "count": len(tracks), "duration": round(sum(track["duration"] for track in tracks)),
                "year": max([track["year"] for track in tracks] or [0]), "tracks": tracks}

    def artist_tracks(self, artist):
        where, keys = self._where()
        rows = self.db().execute(
            "SELECT %s FROM track WHERE %s AND aartist=? ORDER BY year, album COLLATE NOCASE, disc, track, path"
            % (TRACK_COLUMNS, where), keys + [artist])
        return [self.row(row) for row in rows]

    def artist(self, artist, offset=0, limit=60):
        result = self.albums(offset, limit, artist=artist)
        tracks = self.artist_tracks(artist)
        result.update({"id": artist, "kind": "artist", "title": artist, "count": len(tracks),
                       "duration": round(sum(track["duration"] for track in tracks)),
                       "covers": self._covers(self._where()[0] + " AND aartist=?", self._where()[1] + [artist])})
        return result

    # folders: a path on a source ("" its top)

    def folder_tracks(self, source, folder, recursive=True):
        folder = folder.strip("/")
        if recursive:
            condition = "source=? AND (dir=? OR substr(dir, 1, ?)=?)" if folder else "source=?"
            params = [source, folder, len(folder) + 1, folder + "/"] if folder else [source]
        else:
            condition, params = "source=? AND dir=?", [source, folder]
        rows = self.db().execute("SELECT %s FROM track WHERE %s ORDER BY dir, path" % (TRACK_COLUMNS, condition),
                                 params)
        return [self.row(row) for row in rows]

    def folder(self, source, folder):
        """{source, path, crumbs, folders: [tiles], files: [tracks]}; without source the sources (or the only one)."""
        active = self.active()
        if not source:
            if len(active) == 1:
                source = active[0]
            else:
                counts = self.source_counts()
                items = []
                for key in active:
                    item = self.source(key)
                    items.append({"kind": "folder", "id": json.dumps([key, ""]), "source": key, "path": "",
                                  "title": item.name if item else key, "sourceKind": item.kind if item else "",
                                  "count": counts.get(key, 0),
                                  "covers": self._covers("source=?", [key])})
                return {"source": "", "path": "", "crumbs": [], "folders": items, "files": []}
        folder = (folder or "").strip("/")
        prefix = folder + "/" if folder else ""
        if folder:
            rows = self.db().execute("SELECT DISTINCT dir FROM track WHERE source=? AND substr(dir, 1, ?)=?",
                                     (source, len(prefix), prefix))
        else:
            rows = self.db().execute("SELECT DISTINCT dir FROM track WHERE source=? AND dir != ''", (source,))
        children = {}
        for row in rows:
            rest = row[0][len(prefix):]
            if rest:
                children.setdefault(rest.split("/")[0], 0)
        folders = []
        for name in sorted(children, key=str.casefold):
            path = prefix + name
            count = self.db().execute("SELECT COUNT(*) FROM track WHERE source=? AND (dir=? OR substr(dir, 1, ?)=?)",
                                      (source, path, len(path) + 1, path + "/")).fetchone()[0]
            folders.append({"kind": "folder", "id": json.dumps([source, path]), "source": source, "path": path,
                            "title": name, "count": count,
                            "covers": self._covers("source=? AND (dir=? OR substr(dir, 1, ?)=?)",
                                                   [source, path, len(path) + 1, path + "/"])})
        item = self.source(source)
        crumbs = [{"title": item.name if item else source, "sourceKind": item.kind if item else "", "path": ""}]
        parts = folder.split("/") if folder else []
        for index, part in enumerate(parts):
            crumbs.append({"title": part, "path": "/".join(parts[:index + 1])})
        return {"source": source, "path": folder, "crumbs": crumbs, "folders": folders,
                "files": self.folder_tracks(source, folder, recursive=False), "multiple": len(active) > 1}

    # playlists

    def playlist_rows(self):
        where, keys = self._where()
        return self.db().execute("SELECT * FROM playlist WHERE %s ORDER BY own DESC, name COLLATE NOCASE"
                                 % where, keys).fetchall()

    def playlist_id(self, source, path):
        return json.dumps([source, path], ensure_ascii=False)

    def parse_playlist_id(self, value):
        try:
            source, path = json.loads(value)
            return str(source), str(path)
        except (ValueError, TypeError):
            return None

    def playlist_row(self, value):
        parsed = self.parse_playlist_id(value)
        if parsed is None:
            return None
        return self.db().execute("SELECT * FROM playlist WHERE source=? AND path=?", parsed).fetchone()

    def playlist_entries(self, row):
        try:
            return [(track, title) for track, title in json.loads(row["entries"] or "[]")]
        except (ValueError, TypeError):
            return []

    def playlists(self, hidden=()):
        items = []
        for row in self.playlist_rows():
            value = self.playlist_id(row["source"], row["path"])
            if value in hidden:
                continue
            tracks = [track for track, _ in self.playlist_entries(row) if track]
            covers, seen = [], set()
            for track in tracks:
                info = self.track(track)
                if info and info["cover"] and info["albumId"] not in seen:
                    seen.add(info["albumId"])
                    covers.append(info["cover"])
                    if len(covers) == 4:
                        break
            items.append({"kind": "playlist", "id": value, "title": row["name"], "source": row["source"],
                          "type": "own" if row["own"] else row["kind"], "own": bool(row["own"]),
                          "count": len(self.playlist_entries(row)), "covers": covers})
        return {"total": len(items), "items": items}

    def playlist(self, value):
        row = self.playlist_row(value)
        if row is None:
            return None
        entries = self.playlist_entries(row)
        tracks = []
        for index, (track, title) in enumerate(entries):
            info = self.track(track) if track else None
            if info is None:
                info = {"id": track, "title": title, "artist": "", "album": "", "duration": 0, "cover": "",
                        "available": False}
            elif not info["available"] or not self.available(track):
                info["available"] = False
            info["index"] = index
            tracks.append(info)
        covers = []
        for track in tracks:
            if track.get("cover") and track["cover"] not in covers:
                covers.append(track["cover"])
        return {"id": value, "kind": "playlist", "title": row["name"], "source": row["source"],
                "type": "own" if row["own"] else row["kind"], "own": bool(row["own"]), "count": len(tracks),
                "duration": round(sum(track.get("duration") or 0 for track in tracks)), "covers": covers[:4],
                "tracks": tracks}
