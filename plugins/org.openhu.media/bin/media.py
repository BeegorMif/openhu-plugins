#!/usr/bin/env python3
"""Music player: music files from USB sticks, $OPENHU_DATA_DIR/Music and the config's folders, with playlists, a
visible queue and the modes order, shuffle and random (openhu-plugins#38). mpv plays (player.py), the plugin owns
the queue (playqueue.py), the library is an SQLite index of the tags (library.py), playlists.py reads and writes
the playlist files.

State:   "music.state" {state: playing|paused|stopped, track: {id, title, artist, album, albumId, duration, cover
         (file URL), source, sourceName, sourceKind, folder} or null, position, positionTime (ms since 1970, the
         page counts on from there), mode: order|shuffle|random, repeat: off|all|one, queue: {version, length,
         index}, context: {kind, id}, sources: [{key, name, kind, tracks}], scan: {active, done, total, source},
         library: {version, tracks}, columns, error}
Commands: bus.emit "music.command" {cmd, ...}
         play, pause, toggle, stop, next, previous, seek {value: s}, mode {value: order|shuffle|random, without:
         the next one}, repeat {value: off|all|one, without: the next one}, playItems {context, start (track id or
         index), mode}, enqueue {context, next: true = play next}, jump {key}, move {key, to}, remove {key},
         set {key: "columns", value: 3-6}, rescan,
         createPlaylist {name, source, context}, renamePlaylist {playlist, name}, deletePlaylist {playlist},
         addToPlaylist {playlist, context}, removeFromPlaylist {playlist, index}, movePlaylistItem {playlist, from,
         to}
         context: {kind: album|artist|folder|playlist|songs|track|tracks, id, source, path, sort, ids}
         With an "id" the result comes as "music.result" {id, cmd, ok, error}.
Queries: bus.emit "music.query" {id, cmd, ...} -> "music.result" {id, cmd, ok, ...}
         albums/artists/playlists {offset, limit}, songs {sort: title|artist|added, offset, limit}, album {album},
         artist {artist}, playlist {playlist}, folder {source, path}, sources, queue {limit} (the entries after
         the current one; with repeat the ones after the end of the list follow with "repeat": true)
Notices: "music.notice" {text, error} (one-shot): a short message for a toast (playlist saved, stick removed)
Media:   media.metadata / media.status with source "music" (home page, media keys, Bluetooth car audio); the media
         keys work while the music is the current media source. Pauses when Android Auto or another local source
         starts playing (pauseForAndroidAuto), stops when the stick of the track that plays is pulled.
Actions: music.toggle, music.next, music.previous (e.g. for steering wheel buttons)
Config (the config store in OpenHU, settings in Settings → Apps): columns (tiles per row, 3-6), folders (more music folders), pauseForAndroidAuto,
         mediaRoot (default /run/media), mpv (the program), hiddenPlaylists (own playlists deleted on a read-only
         stick: hidden here, {playlist: mtime})
"""

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import library  # noqa: E402
import playlists  # noqa: E402
from player import Player, PlayerError  # noqa: E402
from playqueue import MODES, ORDER, REPEAT_OFF, REPEAT_ONE, REPEATS, PlayQueue  # noqa: E402

import openhu  # noqa: E402
from openhu import OpenHU, Texts, setup_logging  # noqa: E402

log = logging.getLogger("music")

DEFAULTS = {
    "columns": 4,
    "folders": [],
    "pauseForAndroidAuto": True,
    "mediaRoot": "/run/media",
    "mpv": "mpv",
    "hiddenPlaylists": {},
}
SOURCE_SECONDS = 2
RESCAN_SECONDS = 300  # the data folder and the config folders (sticks are read-only)
STATE_SECONDS = 5  # music.state while playing (the page counts the position on by itself)
SAVE_SECONDS = 30
MAX_SAVED_QUEUES = 20
QUERY_LIMIT = 200
MEDIA_KEYS = {
    "media.next": {"cmd": "next"},
    "media.previous": {"cmd": "previous"},
    "media.play_pause": {"cmd": "toggle"},
    "media.play": {"cmd": "play"},
    "media.pause": {"cmd": "pause"},
}
OWN_ACTIONS = {"music.toggle": {"cmd": "toggle"}, "music.next": {"cmd": "next"},
               "music.previous": {"cmd": "previous"}}


def action_command(action, music_is_source):
    """music.command for an input action, None if the music player does not handle it."""
    if action in OWN_ACTIONS:
        return dict(OWN_ACTIONS[action])
    if music_is_source and action in MEDIA_KEYS:
        return dict(MEDIA_KEYS[action])
    return None


def now_ms():
    return int(time.time() * 1000)


def load_config(data_dir):
    # the config store in OpenHU (columns and pauseForAndroidAuto are settings in Settings → Apps, openhu#152)
    config = openhu.load_config(DEFAULTS, data_dir)
    try:
        config["columns"] = max(3, min(6, int(config["columns"])))
    except (TypeError, ValueError):
        config["columns"] = DEFAULTS["columns"]
    if not isinstance(config["folders"], list):
        config["folders"] = []
    if not isinstance(config["hiddenPlaylists"], dict):
        config["hiddenPlaylists"] = {}
    return config


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as file:
        json.dump(data, file, indent=1)
    os.replace(path + ".tmp", path)


class CommandError(Exception):
    pass


class MusicPlugin:
    def __init__(self, api=None, data_dir=None, mpv=None):
        self.data_dir = data_dir or openhu.DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.config = load_config(self.data_dir)
        self.api = api or OpenHU()
        self.texts = Texts(os.path.join(HERE, "..", "i18n"))
        if hasattr(self.api, "on"):
            self.texts.follow(self.api, self.publish_state)
        if hasattr(self.api, "on_config"):
            # changed in Settings → Apps
            openhu.follow_config(self.api, self.config, lambda keys: self.publish_state(), self.data_dir)
        self.library = library.Library(self.data_dir)
        self.queue = PlayQueue(available=self.track_available)
        mpv = mpv or self.config.get("mpv") or "mpv"
        self.mpv_missing = shutil.which(mpv) is None
        self.player = Player(mpv=mpv, on_event=self.on_player_event)
        self.mutagen_missing = not self.has_mutagen()
        self.queue_source = None  # key of the source the queue belongs to (saved per source)
        self.context = {}
        self.state = "stopped"
        self.loaded = False  # the current track is in mpv
        self.position = 0.0
        self.position_time = now_ms()
        self.duration = 0.0
        self.track_info = None
        self.sources = []
        self.scan_state = {"active": False, "done": 0, "total": 0, "source": ""}
        self.scan_pending = []
        self.scan_task = None
        self.library_version = 0
        self.error = ""
        self.media_owner = None
        self.android_auto_playing = False
        self.metadata_sent = None
        self.status_sent = None
        self.tasks = []
        self.failures = 0  # files in a row that could not be played
        self.last_save = 0
        self.lock = asyncio.Lock()
        self.saved = self.read_saved()
        if hasattr(self.api, "on"):
            self.api.on("music.command", self.on_command)
            self.api.on("music.query", self.on_query)
            self.api.on("input.action", self.on_action)
            self.api.on("media.status", self.on_media_status)

    @staticmethod
    def has_mutagen():
        try:
            import mutagen  # noqa: F401
            return True
        except ImportError:
            return False

    def track_available(self, track):
        return self.library.available(track)

    # --- saved queues (per source) -----------------------------------------------------

    @property
    def saved_path(self):
        return os.path.join(self.data_dir, "queues.json")

    def read_saved(self):
        try:
            with open(self.saved_path) as file:
                data = json.load(file)
            if isinstance(data, dict) and isinstance(data.get("queues"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"current": None, "queues": {}}

    def remember_queue(self):
        """Keeps the queue, position and mode under its source (in memory, write_saved() writes them)."""
        if self.queue_source is None or not len(self.queue):
            return
        self.saved["queues"][self.queue_source] = {"queue": self.queue.to_dict(), "position": round(self.position, 1),
                                                   "context": self.context, "saved": time.time()}
        self.saved["current"] = self.queue_source
        queues = self.saved["queues"]
        for key in sorted(queues, key=lambda key: queues[key].get("saved", 0))[:-MAX_SAVED_QUEUES]:
            del queues[key]

    def write_saved(self):
        self.remember_queue()
        try:
            write_json(self.saved_path, self.saved)
        except OSError as error:
            log.warning("queues: %s", error)
        self.last_save = time.monotonic()

    def restore_queue(self, source_key):
        """Takes the saved queue of a source (paused, mpv loads it on play); True if there was one."""
        saved = self.saved["queues"].get(source_key)
        queue = PlayQueue(available=self.track_available)
        if not saved or not queue.load(saved.get("queue") or {}):
            return False
        self.queue = queue
        self.queue_source = source_key
        self.context = saved.get("context") or {}
        self.position = float(saved.get("position") or 0)
        self.position_time = now_ms()
        self.loaded = False
        self.state = "paused"
        self.update_track_info()
        log.info("queue of %s restored: %d tracks", source_key, len(queue))
        return True

    # --- sources and scan -----------------------------------------------------------

    def find_sources(self):
        return library.find_sources(self.config.get("mediaRoot") or "/run/media", os.path.join(self.data_dir, "Music"),
                                    self.config.get("folders"))

    async def update_sources(self):
        sources = self.find_sources()
        if [(s.key, s.path) for s in sources] == [(s.key, s.path) for s in self.sources]:
            return False
        old = {source.key for source in self.sources}
        new = {source.key for source in sources}
        self.sources = sources
        self.library.set_sources(sources)
        log.info("sources: %s", ", ".join("%s (%s)" % (s.key, s.path) for s in sources) or "none")
        gone = old - new
        current = self.queue.current()
        if gone:
            if self.queue_source in gone:
                # the stick of the queue: stop, the queue waits for the stick (saved)
                self.position = await self.current_position()
                self.write_saved()
                if self.loaded:
                    await self.safe_player(self.player.stop())
                self.queue = PlayQueue(available=self.track_available)
                self.queue_source, self.context, self.loaded, self.track_info = None, {}, False, None
                if self.state != "stopped":
                    await self.notice("org.openhu.media.notice.stick_removed")
                self.state = "stopped"
            elif current and library.split_id(current)[0] in gone and self.state != "stopped":
                await self.safe_player(self.player.stop())
                self.loaded = False
                self.state = "stopped"
                await self.notice("org.openhu.media.notice.stick_removed")
            elif self.loaded:
                # the next track may have been on it
                await self.preload_next()
        for source in sources:
            if source.key not in old:
                self.request_scan(source)
        if not len(self.queue):
            # a queue of a stick plugged in again (or the last one after a start)
            for key in [self.saved.get("current")] + [source.key for source in sources if source.key in (new - old)]:
                if key in new and self.restore_queue(key):
                    break
        self.library_version += 1
        await self.publish_state()
        return True

    def request_scan(self, source):
        if source.key not in [pending.key for pending in self.scan_pending]:
            self.scan_pending.append(source)
        if self.scan_task is None or self.scan_task.done():
            self.scan_task = asyncio.create_task(self.run_scans())

    async def run_scans(self):
        loop = asyncio.get_running_loop()
        while self.scan_pending:
            source = self.scan_pending.pop(0)
            if source.key not in self.library.active():
                continue
            self.scan_state = {"active": True, "done": 0, "total": 0, "source": source.name, "sourceKind": source.kind}
            await self.publish_state()
            last = [0.0]

            def progress(done, total):
                if time.monotonic() - last[0] > 0.5 or done == total:
                    last[0] = time.monotonic()
                    loop.call_soon_threadsafe(self.scan_progress, done, total)

            def stopped():
                return source.key not in self.library.active()

            try:
                # without mutagen the files are indexed by their names
                files, read = await asyncio.to_thread(self.library.scan, source, progress, stopped)
                log.info("scan %s: %d files, %d read", source.key, files, read)
            except Exception as error:
                log.warning("scan %s: %s", source.key, error)
            self.library_version += 1
            self.scan_state = {"active": False, "done": 0, "total": 0, "source": ""}
            self.update_track_info()
            await self.publish_state()

    def scan_progress(self, done, total):
        if self.scan_state.get("active"):
            self.scan_state.update(done=done, total=total)
            asyncio.ensure_future(self.publish_state())

    async def watch(self):
        rescan = time.monotonic()
        while True:
            try:
                await self.update_sources()
                if time.monotonic() - rescan > RESCAN_SECONDS:
                    rescan = time.monotonic()
                    for source in self.sources:
                        if source.kind != library.USB:
                            self.request_scan(source)
            except Exception:
                log.exception("sources")
            await asyncio.sleep(SOURCE_SECONDS)

    async def tick(self):
        """While playing: the position now and then into music.state, the queue into queues.json."""
        last_state = time.monotonic()
        while True:
            await asyncio.sleep(1)
            if self.state != "playing" or not self.loaded:
                continue
            try:
                self.position = await self.player.position()
                self.position_time = now_ms()
                if self.position > 1:
                    self.failures = 0
                if time.monotonic() - last_state >= STATE_SECONDS:
                    last_state = time.monotonic()
                    await self.publish_state()
                if time.monotonic() - self.last_save >= SAVE_SECONDS:
                    self.write_saved()
            except Exception:
                log.exception("tick")

    # --- playback ----------------------------------------------------------------------

    async def safe_player(self, coroutine):
        try:
            return await coroutine
        except PlayerError as error:
            log.warning("mpv: %s", error)
            self.error = self.texts.text("org.openhu.media.error.player", str(error))
            return None

    async def current_position(self):
        if self.loaded and self.state != "stopped":
            position = await self.safe_player(self.player.position())
            if position is not None:
                return position
        return self.position

    def update_track_info(self):
        current = self.queue.current()
        info = self.library.track(current) if current else None
        if info is not None:
            source = self.library.source(info["source"])
            info["sourceName"] = source.name if source else ""
            info["sourceKind"] = source.kind if source else ""
            info["queueKey"] = self.queue.current_key
        elif current:
            info = {"id": current, "title": os.path.basename(library.split_id(current)[1]), "artist": "", "album": "",
                    "duration": 0, "cover": "", "available": False, "queueKey": self.queue.current_key}
        self.track_info = info
        self.duration = (info or {}).get("duration") or 0

    async def preload_next(self):
        if not self.loaded:
            return
        following = self.queue.peek()
        await self.safe_player(self.player.set_next(self.library.file_of(following) if following else None))

    async def load_current(self, position=0.0, paused=False):
        """Plays the current track of the queue (skipping tracks that are not there)."""
        if self.mpv_missing:
            self.error = self.texts.text("org.openhu.media.error.no_mpv")
            self.state = "stopped"
            await self.publish_state()
            return
        track = self.queue.current()
        if track is not None and not self.track_available(track):
            track = self.queue.next()
            position = 0.0
        if track is None:
            await self.stop_playback()
            return
        following = self.queue.peek()
        self.error = ""
        result = await self.safe_player(self.player.load(
            self.library.file_of(track), self.library.file_of(following) if following else None, position, paused))
        if result is None and self.error:
            self.loaded = False
            self.state = "stopped"
        else:
            self.loaded = True
            self.state = "paused" if paused else "playing"
            if not paused:
                self.media_owner = "music"
        self.position = position
        self.position_time = now_ms()
        self.update_track_info()
        await self.publish_state()
        self.write_saved()

    async def stop_playback(self):
        if self.loaded:
            await self.safe_player(self.player.stop())
        self.loaded = False
        self.state = "stopped"
        self.position = 0.0
        self.position_time = now_ms()
        self.update_track_info()
        await self.publish_state()

    async def play(self):
        if self.state == "playing" and self.loaded:
            return
        if self.loaded and self.state == "paused":
            await self.safe_player(self.player.set_paused(False))
            self.state = "playing"
            self.media_owner = "music"
            self.position_time = now_ms()
            await self.publish_state()
            return
        if not len(self.queue):
            # nothing chosen yet (a media key, the home card): all songs shuffled
            tracks = await asyncio.to_thread(self.library.song_ids)
            if not tracks:
                return
            self.set_queue(tracks, None, "shuffle", {"kind": "songs"})
            await self.load_current()
            return
        await self.load_current(self.position if self.state == "paused" else 0.0)

    async def pause(self):
        if self.state != "playing":
            return
        self.position = await self.current_position()
        self.position_time = now_ms()
        if self.loaded:
            await self.safe_player(self.player.set_paused(True))
        self.state = "paused"
        await self.publish_state()
        self.write_saved()

    def set_queue(self, tracks, start, mode, context):
        """A new queue. Mode and repeat stay as they are (those of the source's saved queue when nothing was
        loaded); mode switches it (Shuffle, Shuffle all)."""
        if self.queue_source is not None:
            self.remember_queue()
        if len(self.queue):
            current_mode, current_repeat = self.queue.mode, self.queue.repeat
        else:
            saved = self.saved["queues"].get(library.split_id(tracks[0])[0], {}).get("queue", {}) if tracks else {}
            current_mode, current_repeat = saved.get("mode", ORDER), saved.get("repeat", REPEAT_OFF)
        self.queue = PlayQueue(available=self.track_available)
        self.queue.mode = current_mode if current_mode in MODES else ORDER
        self.queue.repeat = current_repeat if current_repeat in REPEATS else REPEAT_OFF
        self.queue.set_tracks(tracks, start, mode)
        first = self.queue.current() or (tracks[0] if tracks else None)
        self.queue_source = library.split_id(first)[0] if first else None
        self.context = {key: value for key, value in (context or {}).items()
                        if key in ("kind", "id", "source", "path", "sort", "recursive")}

    async def next_track(self, auto=False):
        track = self.queue.next(auto=auto)
        if track is None:
            await self.stop_at_end()
            return
        await self.load_current()

    async def stop_at_end(self):
        """The end of the queue: stopped, the last track stays current (play starts it again)."""
        await self.stop_playback()

    async def previous_track(self):
        position = await self.current_position()
        track, restart = self.queue.previous(position)
        if track is None:
            return
        if restart and self.loaded:
            await self.safe_player(self.player.seek(0))
            self.position = 0.0
            self.position_time = now_ms()
            if self.state == "paused":
                await self.safe_player(self.player.set_paused(False))
                self.state = "playing"
            await self.publish_state()
            return
        await self.load_current()

    async def on_player_event(self, name, data):
        if name == "advanced":
            # gapless: mpv plays the preloaded next track
            async with self.lock:
                self.queue.next(auto=True)
                self.position = 0.0
                self.position_time = now_ms()
                self.update_track_info()
                await self.preload_next()
                await self.publish_state()
                self.write_saved()
        elif name == "ended":
            async with self.lock:
                if self.state == "playing":
                    await self.next_track(auto=True)
        elif name == "error":
            log.warning("cannot play %s: %s", data.get("path"), data.get("error"))
            async with self.lock:
                if self.state != "playing":
                    return
                self.failures += 1
                if self.failures > max(3, min(len(self.queue), 50)):
                    # nothing in the queue plays (all broken?): stop instead of trying forever
                    self.failures = 0
                    await self.stop_playback()
                    return
                await self.notice("org.openhu.media.error.play_failed", os.path.basename(data.get("path") or ""),
                                  error=True)
                current = self.queue.current()
                if current and self.library.file_of(current) != data.get("path"):
                    # the preloaded one failed: move onto it first
                    self.queue.next(auto=False)
                await self.next_track()
        elif name == "exited":
            self.loaded = False
            if self.state == "playing":
                self.state = "paused"
            await self.publish_state()

    # --- contexts: what the page plays -------------------------------------------------------

    def resolve(self, context):
        """A context of the page -> track ids (blocking, in a thread)."""
        context = context or {}
        kind = context.get("kind")
        if kind == "album":
            return [track["id"] for track in self.library.album_tracks(context.get("id", ""))]
        if kind == "artist":
            return [track["id"] for track in self.library.artist_tracks(context.get("id", ""))]
        if kind == "folder":
            source = context.get("source") or (self.library.active() or [""])[0]
            return [track["id"] for track in self.library.folder_tracks(source, context.get("path", ""),
                                                                         context.get("recursive", True) is not False)]
        if kind == "playlist":
            row = self.library.playlist_row(context.get("id", ""))
            return [track for track, _ in self.library.playlist_entries(row) if track] if row else []
        if kind == "songs":
            return self.library.song_ids(context.get("sort", "title"))
        if kind == "track" and context.get("id"):
            return [str(context["id"])]
        if kind == "tracks":
            return [str(track) for track in context.get("ids", []) if track]
        raise CommandError("unknown context")

    # --- commands ------------------------------------------------------------------------

    async def on_command(self, topic, data):
        async with self.lock:
            try:
                result = await self.handle_command(data)
            except (CommandError, playlists.PlaylistError, ValueError, TypeError) as error:
                log.warning("%s: %s", data.get("cmd"), error)
                await self.reply(data, error=str(error))
                return
            await self.reply(data, result or {})

    async def reply(self, data, result=None, error=None):
        if data.get("id") is None:
            return
        # the request's id wins over an "id" of the answer (an album or playlist has one, the page knows it)
        message = dict(result or {}) if error is None else {"error": error}
        message.update(id=data.get("id"), cmd=data.get("cmd"), ok=error is None)
        await self.api.safe(self.api.emit("music.result", **message))

    async def notice(self, text_id, *args, error=False):
        text = str(self.texts.text(text_id, *args))
        await self.api.safe(self.api.emit("music.notice", text=text, error=error))

    async def handle_command(self, data):
        command, value = data.get("cmd"), data.get("value")
        if command == "play":
            await self.play()
        elif command in ("pause", "stop"):
            await self.pause()
        elif command == "toggle":
            await (self.pause() if self.state == "playing" else self.play())
        elif command == "next":
            if len(self.queue):
                await self.next_track()
        elif command == "previous":
            if len(self.queue):
                await self.previous_track()
        elif command == "seek":
            seconds = max(0.0, float(value or 0))
            if self.loaded:
                await self.safe_player(self.player.seek(seconds))
            self.position, self.position_time = seconds, now_ms()
            await self.publish_state()
        elif command == "mode":
            if value in MODES:
                self.queue.set_mode(value)
            else:
                self.queue.cycle_mode()
            await self.preload_next()
            await self.publish_state()
            self.write_saved()
            return {"mode": self.queue.mode}
        elif command == "repeat":
            if value in REPEATS:
                self.queue.set_repeat(value)
            else:
                self.queue.cycle_repeat()
            await self.preload_next()
            await self.publish_state()
            self.write_saved()
            return {"repeat": self.queue.repeat}
        elif command == "playItems":
            tracks = await asyncio.to_thread(self.resolve, data.get("context"))
            if not tracks:
                raise CommandError("nothing to play")
            start = data.get("start")
            if isinstance(start, str):
                start = tracks.index(start) if start in tracks else 0
            elif start is not None:
                start = int(start)
            mode = data.get("mode") if data.get("mode") in MODES else None
            if start is None and mode is None:
                start = 0
            self.set_queue(tracks, start, mode, data.get("context"))
            await self.load_current()
        elif command == "enqueue":
            tracks = await asyncio.to_thread(self.resolve, data.get("context"))
            if not tracks:
                raise CommandError("nothing to add")
            if not len(self.queue):
                self.set_queue(tracks, 0, None, data.get("context"))
                await self.load_current()
            else:
                (self.queue.play_next if data.get("next") else self.queue.enqueue)(tracks)
                await self.preload_next()
                await self.publish_state()
                await self.notice("org.openhu.media.notice.play_next" if data.get("next")
                                  else "org.openhu.media.notice.queued", len(tracks))
        elif command == "jump":
            if self.queue.jump(int(value if value is not None else data.get("key"))) is not None:
                await self.load_current()
        elif command == "move":
            if self.queue.move(int(data.get("key")), int(data.get("to", 0))):
                await self.preload_next()
                await self.publish_state()
        elif command == "remove":
            if self.queue.remove(int(value if value is not None else data.get("key"))):
                await self.preload_next()
                await self.publish_state()
        elif command == "set":
            if data.get("key") != "columns":
                raise CommandError("unknown setting")
            self.config["columns"] = max(3, min(6, int(value)))
            self.save_config()
            await self.publish_state()
        elif command == "rescan":
            for source in self.sources:
                self.request_scan(source)
        elif command in ("createPlaylist", "renamePlaylist", "deletePlaylist", "addToPlaylist", "removeFromPlaylist",
                         "movePlaylistItem"):
            result = await self.playlist_command(command, data)
            self.library_version += 1
            await self.publish_state()
            return result
        else:
            raise CommandError("unknown command %s" % command)
        return None

    def save_config(self):
        openhu.save_config(self.config, self.data_dir)

    # --- own playlists --------------------------------------------------------------------

    def playlist_source(self, key, context_tracks):
        source = self.library.source(key) if key else None
        if source is None and context_tracks:
            source = self.library.source(library.split_id(context_tracks[0])[0])
        if source is None:
            sources = self.library.sources.values()
            source = next((item for item in sources if item.kind == library.USB), None) or \
                next(iter(sources), None)
        if source is None:
            raise CommandError("no source")
        return source

    def entries_of(self, path, root):
        """The entries of an own playlist file as they are (also those of sticks that are not there)."""
        if not os.path.isfile(path):
            return []
        result = []
        for found, raw, title in playlists.read(path, root):
            info = self.library.track(self.library.track_of_path(found)) if found else None
            result.append((raw, (info or {}).get("duration") or 0, title))
        return result

    def entry_of(self, playlist_path, track):
        path = self.library.file_of(track)
        if not path:
            return None
        info = self.library.track(track) or {}
        title = " - ".join(part for part in (info.get("artist"), info.get("title")) if part)
        return (playlists.relative(playlist_path, path), info.get("duration") or 0, title)

    def write_playlist(self, source, name, entries):
        """Writes and indexes an own playlist (blocking)."""
        path = playlists.own_path(source.path, name)
        playlists.write(source.path, name, playlists.format_m3u8(entries), stick=source.stick)
        self.library.index_playlist(source, path)
        hidden = self.config.get("hiddenPlaylists", {})
        hidden.pop(self.library.playlist_id(source.key, os.path.relpath(path, source.path).replace(os.sep, "/")),
                   None)
        return path

    def own_playlist(self, value):
        row = self.library.playlist_row(value or "")
        if row is None or not row["own"]:
            raise CommandError("not an own playlist")
        source = self.library.source(row["source"])
        if source is None:
            raise CommandError("source not there")
        path = os.path.join(source.path, *row["path"].split("/"))
        return row, source, path

    def hide_playlist(self, value, path):
        try:
            self.config.setdefault("hiddenPlaylists", {})[value] = os.path.getmtime(path)
        except OSError:
            return
        self.save_config()

    def playlist_command_blocking(self, command, data):
        if command == "createPlaylist":
            name = playlists.valid_name(data.get("name"))
            tracks = self.resolve(data["context"]) if data.get("context") else []
            source = self.playlist_source(data.get("source"), tracks)
            path = playlists.own_path(source.path, name)
            value = self.library.playlist_id(source.key, os.path.relpath(path, source.path).replace(os.sep, "/"))
            if os.path.exists(path) and value not in self.config.get("hiddenPlaylists", {}):
                raise CommandError(str(self.texts.text("org.openhu.media.error.playlist_exists", name)))
            entries = [entry for entry in (self.entry_of(path, track) for track in tracks) if entry]
            self.write_playlist(source, name, entries)
            self.save_config()
            return {"playlist": value}, ("org.openhu.media.notice.playlist_created", name)
        row, source, path = self.own_playlist(data.get("playlist"))
        entries = self.entries_of(path, source.path)
        if command == "addToPlaylist":
            tracks = self.resolve(data.get("context"))
            entries += [entry for entry in (self.entry_of(path, track) for track in tracks) if entry]
            self.write_playlist(source, row["name"], entries)
            return {}, ("org.openhu.media.notice.added_to_playlist", len(tracks), row["name"])
        if command == "removeFromPlaylist":
            index = int(data.get("index"))
            if 0 <= index < len(entries):
                entries.pop(index)
            self.write_playlist(source, row["name"], entries)
            return {}, None
        if command == "movePlaylistItem":
            start, to = int(data.get("from")), int(data.get("to"))
            if 0 <= start < len(entries):
                entry = entries.pop(start)
                entries.insert(max(0, min(to, len(entries))), entry)
            self.write_playlist(source, row["name"], entries)
            return {}, None
        if command == "renamePlaylist":
            name = playlists.valid_name(data.get("name"))
            if name == row["name"]:
                return {}, None
            target = playlists.own_path(source.path, name)
            if os.path.exists(target):
                raise CommandError(str(self.texts.text("org.openhu.media.error.playlist_exists", name)))
            # the entries are relative to Playlists/: the same in the new file
            self.write_playlist(source, name, entries)
            value = self.library.playlist_id(source.key, os.path.relpath(target, source.path).replace(os.sep, "/"))
            if playlists.delete(source.path, row["name"]):
                self.library.drop_playlist(source.key, row["path"])
            else:
                self.hide_playlist(data.get("playlist"), path)
            return {"playlist": value}, ("org.openhu.media.notice.playlist_renamed", name)
        if command == "deletePlaylist":
            if playlists.delete(source.path, row["name"]):
                self.library.drop_playlist(source.key, row["path"])
                return {}, ("org.openhu.media.notice.playlist_deleted", row["name"])
            # a read-only stick: openhu-cli can only write playlists, so it stays there and is hidden here
            self.hide_playlist(data.get("playlist"), path)
            return {}, ("org.openhu.media.notice.playlist_hidden", row["name"])
        raise CommandError("unknown command")

    async def playlist_command(self, command, data):
        try:
            result, notice = await asyncio.to_thread(self.playlist_command_blocking, command, data)
        except playlists.PlaylistError as error:
            await self.notice("org.openhu.media.error.playlist", str(error), error=True)
            raise
        except CommandError as error:
            await self.notice("org.openhu.media.error.playlist", str(error), error=True)
            raise
        if notice:
            await self.notice(*notice)
        return result

    def hidden_playlists(self):
        """Own playlists deleted on a read-only stick and not changed since."""
        hidden = set()
        for value, mtime in self.config.get("hiddenPlaylists", {}).items():
            row = self.library.playlist_row(value)
            if row is not None and abs((row["mtime"] or 0) - float(mtime)) < 0.001:
                hidden.add(value)
        return hidden

    # --- queries --------------------------------------------------------------------------

    def query_blocking(self, command, data, queue_entries):
        offset = max(0, int(data.get("offset") or 0))
        limit = max(1, min(QUERY_LIMIT, int(data.get("limit") or 60)))
        if command == "albums":
            return self.library.albums(offset, limit)
        if command == "artists":
            return self.library.artists(offset, limit)
        if command == "songs":
            return self.library.songs(data.get("sort", "title"), offset, limit)
        if command == "album":
            return self.library.album(data.get("album", ""))
        if command == "artist":
            return self.library.artist(data.get("artist", ""), offset, limit)
        if command == "playlists":
            return self.library.playlists(self.hidden_playlists())
        if command == "playlist":
            result = self.library.playlist(data.get("playlist", ""))
            if result is None:
                raise CommandError("unknown playlist")
            return result
        if command == "folder":
            return self.library.folder(data.get("source", ""), data.get("path", ""))
        if command == "sources":
            counts = self.library.source_counts()
            return {"items": [dict(source.to_dict(), tracks=counts.get(source.key, 0)) for source in self.sources]}
        if command == "queue":
            infos = self.library.tracks([track for _, track, _ in queue_entries])
            items = []
            for (key, _, repeat), info in zip(queue_entries, infos):
                info["key"] = key
                info["repeat"] = repeat
                info["available"] = info.get("available", False) and self.library.available(info["id"])
                items.append(info)
            return {"items": items, "mode": self.queue.mode, "version": self.queue.version}
        raise CommandError("unknown query %s" % command)

    async def on_query(self, topic, data):
        command = data.get("cmd")
        entries = []
        if command == "queue":
            # with repeat the list goes on after its end: those entries come with "repeat"
            limit = max(1, min(QUERY_LIMIT, int(data.get("limit") or 100)))
            entries = [(key, track, False) for key, track in self.queue.upcoming(limit)]
            entries += [(key, track, True) for key, track in self.queue.wrapped(limit - len(entries))]
        try:
            result = await asyncio.to_thread(self.query_blocking, command, data, entries)
        except (CommandError, ValueError, TypeError) as error:
            await self.reply(data, error=str(error))
            return
        except Exception as error:  # database errors must not end the plugin
            log.exception("query %s", command)
            await self.reply(data, error=str(error))
            return
        await self.reply(data, result)

    # --- media source ---------------------------------------------------------------------

    async def on_action(self, topic, data):
        if data.get("phase") == "release":
            return
        command = action_command(data.get("action"), self.media_owner == "music")
        if command:
            await self.on_command(topic, command)

    async def on_media_status(self, topic, data):
        source, playing = data.get("source"), data.get("state") == "playing"
        if source == "music":
            return
        if source == "androidauto":
            started = playing and not self.android_auto_playing
            self.android_auto_playing = playing
        else:
            started = playing and self.media_owner != source
        if not started:
            return
        self.media_owner = source
        if self.config.get("pauseForAndroidAuto", True) and self.state == "playing":
            log.info("%s started playing, music paused", source)
            async with self.lock:
                await self.pause()

    async def publish_media(self):
        info = self.track_info
        if self.state in ("playing", "paused") and info and (self.loaded or self.metadata_sent is not None):
            metadata = {"title": info.get("title") or "", "artist": info.get("artist") or "",
                        "album": info.get("album") or "", "playlist": "", "duration": round(self.duration or 0),
                        "cover": self.library.cover_data_url(info.get("coverName")),
                        "source": "music"}
            status = {"state": self.state, "app": "Music", "position": round(self.position),
                      "shuffle": self.queue.mode != ORDER, "repeat": self.queue.repeat != REPEAT_OFF,
                      "repeatOne": self.queue.repeat == REPEAT_ONE, "source": "music"}
            if metadata != self.metadata_sent:
                self.metadata_sent = metadata
                await self.api.safe(self.api.publish("media.metadata", **metadata))
            if status != self.status_sent:
                self.status_sent = status
                if self.state == "playing":
                    self.media_owner = "music"
                await self.api.safe(self.api.publish("media.status", **status))
        elif self.metadata_sent is not None:
            self.metadata_sent = self.status_sent = None
            # do not overwrite Android Auto's status when its music paused this one
            if self.media_owner == "music":
                await self.api.safe(self.api.publish("media.status", state="stopped", app="Music", source="music"))

    def state_data(self):
        counts = self.library.source_counts()
        error = self.error
        if not error and self.mpv_missing:
            error = self.texts.text("org.openhu.media.error.no_mpv")
        if not error and self.mutagen_missing:
            error = self.texts.text("org.openhu.media.error.no_mutagen")
        return {
            "state": self.state,
            "track": self.track_info,
            "position": round(self.position, 1),
            "positionTime": self.position_time,
            "duration": round(self.duration or 0, 1),
            "mode": self.queue.mode,
            "repeat": self.queue.repeat,
            "queue": {"version": self.queue.version, "length": len(self.queue), "index": self.queue.played_count(),
                      "upcoming": len(self.queue.order) - self.queue.pos - 1 if self.queue.pos >= 0 else 0},
            "context": self.context,
            "sources": [dict(source.to_dict(), tracks=counts.get(source.key, 0)) for source in self.sources],
            "scan": self.scan_state,
            "library": {"version": self.library_version, "tracks": sum(counts.values())},
            "columns": self.config["columns"],
            "error": str(error),
        }

    async def publish_state(self):
        if not getattr(self.api, "connected", True):
            return
        await self.publish_media()
        await self.api.safe(self.api.publish("music.state", **self.state_data()))

    async def on_connect(self):
        self.metadata_sent = self.status_sent = None
        if not self.tasks:
            try:
                os.makedirs(os.path.join(self.data_dir, "Music"), exist_ok=True)
            except OSError:
                pass
            self.tasks = [asyncio.create_task(self.watch()), asyncio.create_task(self.tick())]
        await self.publish_state()

    async def shutdown(self):
        self.position = await self.current_position()
        self.write_saved()
        await self.player.close()
        for task in self.tasks + ([self.scan_task] if self.scan_task else []):
            task.cancel()
        self.library.close()


async def main():
    plugin = MusicPlugin()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    runner = asyncio.create_task(plugin.api.run(plugin.on_connect))
    await stop.wait()
    runner.cancel()
    await plugin.shutdown()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
