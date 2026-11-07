"""mpv as the player (tests/test_player.py against tools/fake-mpv): a child process that ends with the plugin,
controlled over its JSON IPC (a unix socket) with asyncio.

The plugin owns the queue. mpv only gets the current track and the next one, so the change between them stays
gapless (--gapless-audio). When mpv moves on to the next one by itself, the player reports "advanced" and the
plugin hands it the one after.

Events (on_event(name, data)): "advanced" (mpv plays the preloaded next track), "ended" (the last track ended),
"error" {path, error} (a file could not be played), "pause" {paused}, "exited" (mpv ended).
"""

import asyncio
import ctypes
import json
import logging
import os
import signal
import tempfile

log = logging.getLogger("player")

MPV_ARGS = ["--idle=yes", "--no-video", "--no-terminal", "--gapless-audio=yes", "--no-config", "--keep-open=no",
            "--audio-display=no", "--volume=100", "--audio-client-name=OpenHU", "--title=Music"]


def die_with_parent():
    """preexec_fn: mpv gets SIGTERM when the plugin dies (like radiolib.spawn)."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


class PlayerError(Exception):
    pass


class Player:
    def __init__(self, mpv="mpv", on_event=None, socket_dir=None, env=None):
        self.mpv = mpv
        self.on_event = on_event
        self.socket_dir = socket_dir
        self.env = env
        self.process = None
        self.reader = self.writer = None
        self.next_request = 0
        self.pending = {}
        self.tasks = []
        self.socket = None
        self.current = None  # path that plays (or is loading)
        self.next_path = None  # path preloaded after it
        self.loading = 0  # loadfile replace sent, file-loaded not seen yet
        self.paused = True
        self.seek_to = None  # position for the file that is loading
        self.lock = asyncio.Lock()

    @property
    def running(self):
        return self.process is not None and self.process.returncode is None and self.writer is not None

    async def start(self):
        if self.running:
            return
        directory = self.socket_dir or tempfile.mkdtemp(prefix="openhu-music-")
        self.socket = os.path.join(directory, "mpv.sock")
        try:
            os.unlink(self.socket)
        except OSError:
            pass
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.mpv, *MPV_ARGS, "--input-ipc-server=" + self.socket, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, preexec_fn=die_with_parent,
                env=self.env)
        except OSError as error:
            raise PlayerError("%s: %s" % (self.mpv, error))
        for _ in range(100):
            if self.process.returncode is not None:
                break
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(self.socket)
                break
            except OSError:
                await asyncio.sleep(0.05)
        if self.writer is None:
            stderr = b""
            if self.process.returncode is not None:
                stderr = await self.process.stderr.read()
            await self.close()
            raise PlayerError("mpv did not start: %s" % stderr.decode(errors="replace").strip())
        self.current, self.next_path, self.loading, self.paused = None, None, 0, True
        self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._log_stderr())]
        await self.command("observe_property", 1, "pause")
        await self.command("observe_property", 2, "idle-active")

    async def close(self):
        process, self.process = self.process, None
        writer, self.writer = self.writer, None
        for task in self.tasks:
            task.cancel()
        self.tasks = []
        if writer is not None:
            try:
                writer.write(b'{"command": ["quit"]}\n')
                await writer.drain()
                writer.close()
            except (OSError, RuntimeError):
                pass
        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    process.kill()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(PlayerError("mpv ended"))
        self.pending.clear()
        self.current = self.next_path = None

    async def command(self, *args):
        """A command over the IPC -> its data; PlayerError when mpv answers with an error."""
        if not self.running:
            await self.start()
        self.next_request += 1
        request = self.next_request
        future = asyncio.get_running_loop().create_future()
        self.pending[request] = future
        try:
            self.writer.write((json.dumps({"command": list(args), "request_id": request}) + "\n").encode())
            await self.writer.drain()
            reply = await asyncio.wait_for(future, 5)
        except (OSError, asyncio.TimeoutError, RuntimeError) as error:
            raise PlayerError("%s: %s" % (args[0], error or "timeout"))
        finally:
            self.pending.pop(request, None)
        if reply.get("error") not in (None, "success"):
            raise PlayerError("%s: %s" % (args[0], reply.get("error")))
        return reply.get("data")

    async def get(self, name, default=None):
        try:
            return await self.command("get_property", name)
        except PlayerError:
            return default

    async def _emit(self, name, **data):
        if self.on_event is not None:
            try:
                result = self.on_event(name, data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("player event %s", name)

    async def _read(self):
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if "request_id" in message and "event" not in message:
                    future = self.pending.get(message["request_id"])
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                # events in their own task: a handler may send commands and wait for their replies
                asyncio.create_task(self._event(message))
        except (OSError, asyncio.CancelledError):
            pass
        if self.process is not None:
            log.warning("mpv ended")
            self.writer = None
            await self._emit("exited")

    async def _log_stderr(self):
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                log.info("mpv: %s", line.decode(errors="replace").rstrip())
        except (OSError, AttributeError, asyncio.CancelledError):
            pass

    async def _event(self, message):
        event = message.get("event")
        if event == "property-change" and message.get("name") == "pause":
            self.paused = bool(message.get("data"))
            await self._emit("pause", paused=self.paused)
        elif event == "file-loaded":
            if self.loading > 0:
                self.loading -= 1
                if self.seek_to:
                    position, self.seek_to = self.seek_to, None
                    try:
                        await self.command("seek", position, "absolute")
                    except PlayerError as error:
                        log.info("seek: %s", error)
                return
            # mpv moved on to the preloaded next track by itself (gapless)
            async with self.lock:
                self.current, self.next_path = self.next_path, None
                try:
                    # the one that ended goes: the playlist is again [current]
                    await self.command("playlist-remove", 0)
                except PlayerError:
                    pass
            await self._emit("advanced", path=self.current)
        elif event == "end-file":
            reason = message.get("reason")
            if reason == "error":
                if self.loading:
                    self.loading -= 1
                    failed = self.current
                else:
                    # the preloaded next one, after the current one ended
                    failed, self.current, self.next_path = self.next_path or self.current, None, None
                await self._emit("error", path=failed, error=message.get("file_error", "error"))
            elif reason == "eof" and self.next_path is None and not self.loading:
                self.current = None
                await self._emit("ended")

    # --- playing ---

    async def load(self, path, next_path=None, position=0.0, paused=False):
        """Plays path (from position), with next_path preloaded."""
        async with self.lock:
            if not self.running:
                await self.start()
            await self.command("set_property", "pause", bool(paused))
            self.paused = bool(paused)
            self.loading += 1
            self.seek_to = position if position and position > 0 else None
            self.current, self.next_path = path, None
            try:
                await self.command("loadfile", path, "replace")
            except PlayerError:
                self.loading = max(0, self.loading - 1)
                raise
            if next_path:
                await self.command("loadfile", next_path, "append")
                self.next_path = next_path

    async def set_next(self, next_path):
        """The track after the current one (None: none)."""
        async with self.lock:
            if not self.running or next_path == self.next_path and next_path is not None:
                return
            count = await self.get("playlist-count", 0) or 0
            position = await self.get("playlist-pos", 0)
            position = 0 if position is None or position < 0 else position
            # drop everything after the current entry
            for index in range(count - 1, position, -1):
                try:
                    await self.command("playlist-remove", index)
                except PlayerError:
                    pass
            self.next_path = None
            if next_path and self.current:
                await self.command("loadfile", next_path, "append")
                self.next_path = next_path

    async def set_paused(self, paused):
        await self.command("set_property", "pause", bool(paused))
        self.paused = bool(paused)

    async def seek(self, seconds):
        await self.command("seek", max(0.0, float(seconds)), "absolute")

    async def stop(self):
        async with self.lock:
            self.current = self.next_path = None
            self.loading = 0
            if self.running:
                await self.command("stop")

    async def position(self):
        value = await self.get("time-pos")
        return float(value) if isinstance(value, (int, float)) else 0.0

    async def duration(self):
        value = await self.get("duration")
        return float(value) if isinstance(value, (int, float)) else 0.0
