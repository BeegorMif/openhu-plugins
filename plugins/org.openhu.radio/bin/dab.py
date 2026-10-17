"""DAB/DAB+ for the radio plugin: playback, DLS, slideshow and the scan with openhu-dab (see dablib.py).

openhu-dab (shipped in the plugin archive as bin/<arch>/openhu-dab) tunes the channel (ensemble) of the station and
writes the service's audio as PCM straight into pacat; its events (ensemble, services, DLS, slideshow pictures as
files, errors) arrive as JSON lines on a pipe (--events-fd). No network port. One stick: the band switch stops the
FM/AM processes and vice versa (radio.py starts one or the other).
"""

import asyncio
import base64
import collections
import logging
import os
import tempfile
import time

import dablib
import radiolib
from openhu import save_config

log = logging.getLogger("radio")

# no "playing" event (the ensemble with the station) after this long: "no reception" (openhu-dab keeps trying, the
# error goes away when it finds the station)
SYNC_SECONDS = 20
MAX_SLIDE_BYTES = 512 * 1024
# event lines carry slides as files (--slides), so they are short; base64 slides would be < 1 MB
EVENT_LINE_LIMIT = 2 * 1024 * 1024
# error codes of openhu-dab that mean: no usable stick
STICK_ERRORS = ("no-device", "device-busy", "device-lost")


async def drain(stream, lines):
    """Reads stderr (library debug output, loader errors; a full pipe would block the tool), keeps the last lines."""
    while True:
        line = await stream.readline()
        if not line:
            return
        lines.append(line.decode(errors="replace").strip())


async def open_events(read_fd):
    """StreamReader for the read end of the events pipe."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=EVENT_LINE_LIMIT)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(read_fd, "rb", 0))
    return reader


async def next_event(reader, timeout=None):
    """Next openhu-dab event; None at the end of the pipe, {} on a timeout."""
    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout) if timeout else await reader.readline()
        except asyncio.TimeoutError:
            return {}
        except ValueError:  # line longer than the limit
            continue
        if not line:
            return None
        event = dablib.parse_event(line)
        if event:
            return event


def slides_dir():
    """Directory for openhu-dab's slideshow pictures (it keeps the last two, removes them when it ends)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    path = os.path.join(base, "openhu-radio-slides-%d" % os.getuid())
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError:
        return None
    return path


class DabMixin:
    """DAB part of RadioPlugin (radio.py): uses its config, processes, tasks, rds, error and publish_* methods,
    tool() and tool_problem()."""

    def dab_problem(self):
        """"" if DAB can play, else what is missing (openhu-dab, a library of it, pacat)."""
        return self.tool_problem("openhu-dab") or ("" if self.which("pacat") else "pacat (pulseaudio-utils)")

    def dab_available(self):
        return not self.dab_problem()

    def dab_service(self, key=None):
        return self.config.get("dabServices", {}).get(key or self.config["frequency"].get(radiolib.DAB))

    def dab_error(self, event, stderr=()):
        """Text for an error event of openhu-dab, or for its end without one (stderr: its last lines)."""
        if event and event.get("code") in STICK_ERRORS:
            if event.get("code") == "device-busy":
                return self.texts.text("org.openhu.radio.error.stick_busy")
            return self.texts.text("org.openhu.radio.error.no_stick")
        if event and event.get("message"):
            return str(event["message"])
        library = dablib.missing_library("\n".join(stderr))
        if library:
            return self.texts.text("org.openhu.radio.error.library_missing", "openhu-dab", library,
                                   dablib.library_package(library) or "?")
        return next((line for line in reversed(list(stderr)) if line),
                    self.texts.text("org.openhu.radio.error.dab_ended"))

    async def start_openhu_dab(self, args, stdout):
        """openhu-dab with its events on a pipe -> (process, events reader, stderr lines, stderr task)."""
        read_fd, write_fd = os.pipe()
        os.set_inheritable(write_fd, True)
        args = [str(write_fd) if arg == "{events}" else arg for arg in args]
        log.info("%s%s", " ".join(args), " (simulated stick)" if self.simulated() else "")
        try:
            process = await radiolib.spawn(*args, stdin=asyncio.subprocess.DEVNULL, stdout=stdout,
                                           stderr=asyncio.subprocess.PIPE, pass_fds=(write_fd,),
                                           env=self.environment())
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(write_fd)
        reader = await open_events(read_fd)
        lines = collections.deque(maxlen=20)
        return process, reader, lines, asyncio.create_task(drain(process.stderr, lines))

    # --- playback -------------------------------------------------------------------------

    async def start_dab(self):
        key = self.config["frequency"].get(radiolib.DAB)
        service = self.dab_service(key)
        problem = self.dab_problem()
        if not service:
            self.error = self.texts.text("org.openhu.radio.error.no_dab_station")
        elif problem:
            self.error = self.texts.text("org.openhu.radio.error.dab_missing", problem)
        if self.error:
            self.playing = False
            await self.publish_state()
            return

        self.rds = {"ps": service.get("label", "")}
        self.dab_ensemble = {}
        await self.set_slide("")
        read_fd, write_fd = os.pipe()
        try:
            args = dablib.play_command(self.tool("openhu-dab"), service["channel"], key, self.config, "{events}",
                                       slides_dir())
            dab, events, lines, stderr_task = await self.start_openhu_dab(args, write_fd)
            pacat = await radiolib.spawn(*radiolib.pacat_command(dablib.PCM_RATE, 2), stdin=read_fd)
        finally:
            os.close(read_fd)
            os.close(write_fd)
        self.processes = [dab, pacat]
        self.tasks = [stderr_task,
                      asyncio.create_task(self.dab_events(key, service, dab, events, lines, stderr_task))]
        self.playing = True
        await self.publish_state()

    async def dab_failed(self, error):
        """Stops the DAB processes with an error (from one of their tasks: the rest runs in a new task, the stop
        cancels the calling one)."""
        async def stop():
            self.error = error
            log.error("DAB: %s", error)
            await self.stop_processes()
            self.playing = False
            await self.publish_state()
        asyncio.create_task(stop())

    async def dab_events(self, key, service, dab, events, lines, stderr_task):
        """Ensemble, station name, DLS (as radiotext) and slideshow of openhu-dab; "no reception" while the station
        does not play; an error when openhu-dab ends."""
        started = time.monotonic()
        playing = reported = False
        error = None
        while True:
            event = await next_event(events, timeout=1)
            if event is None:
                break
            kind = event.get("event")
            if kind == "error":
                error = event
                log.warning("openhu-dab: %s", event)
            elif kind == "ensemble":
                ensemble = dablib.ensemble_info(event)
                if ensemble != self.dab_ensemble:
                    self.dab_ensemble = ensemble
                    await self.publish_state()
            elif kind == "playing" and event.get("sid") == key:
                playing = True
                if reported:
                    self.error = ""
                    await self.publish_state()
            elif kind == "dls" and event.get("sid") == key:
                text = str(event.get("text") or "").strip()
                if text and text != self.rds.get("rt"):
                    self.rds = dict(self.rds, rt=text)
                    await self.publish_state()
            elif kind == "service" and event.get("sid") == key and event.get("label"):
                if event["label"] != self.rds.get("ps"):
                    self.rds = dict(self.rds, ps=event["label"])
                    await self.publish_state()
            elif kind == "slide" and event.get("sid") == key:
                await self.show_slide(event)
            if not playing and not reported and time.monotonic() - started > SYNC_SECONDS:
                reported = True
                self.error = self.texts.text("org.openhu.radio.error.dab_no_reception",
                                             dablib.station_label(service, key), service.get("channel"))
                log.warning("%s", self.error)
                await self.publish_state()
        await dab.wait()
        await asyncio.wait([stderr_task], timeout=1)  # the rest of stderr (a loader error)
        if self.playing and dab in self.processes:
            await self.dab_failed(self.dab_error(error, lines))

    async def show_slide(self, event):
        """A slideshow picture of the station: a file (--slides) or base64 in the event."""
        data = None
        if event.get("path"):
            try:
                if os.path.getsize(event["path"]) <= MAX_SLIDE_BYTES:
                    with open(event["path"], "rb") as file:
                        data = file.read()
            except OSError as error:
                log.info("DAB slide: %s", error)
        elif event.get("data") and len(event["data"]) <= MAX_SLIDE_BYTES * 4 // 3 + 4:
            try:
                data = base64.b64decode(event["data"])
            except ValueError:
                data = None
        image = radiolib.data_url(data) if data else None
        if image:
            await self.set_slide(image)
        elif data:
            log.info("DAB slide %s: neither PNG nor JPEG", event.get("mime"))

    # --- scan -----------------------------------------------------------------------------

    async def scan_dab(self):
        """All Band III channels one after the other, takes minutes; progress in radio.state.scan."""
        problem = self.tool_problem("openhu-dab")
        if problem:
            self.error = self.texts.text("org.openhu.radio.error.dab_missing", problem)
            self.scanning = False
            await self.publish_state()
            return
        was_playing = self.playing
        await self.stop_processes()
        self.scanning, self.scan_abort, self.error = True, False, ""
        # all of Band III, or the channels in the config (dabChannels, e.g. only the ones used nearby)
        channels = [channel for channel in (dablib.normalize_channel(value) for value in
                                            self.config.get("dabChannels") or dablib.DAB_CHANNELS) if channel]
        result = dablib.ScanResult()
        args = dablib.scan_command(self.tool("openhu-dab"), channels, self.config, "{events}")
        process, events, lines, stderr_task = await self.start_openhu_dab(args, asyncio.subprocess.DEVNULL)
        error = None
        complete = False
        try:
            while True:
                if self.scan_abort:
                    break
                event = await next_event(events, timeout=0.5)
                if event is None:
                    break
                kind = event.get("event")
                if kind == "scan":
                    self.scan_progress = {"channel": event.get("channel"), "done": int(event.get("index") or 0),
                                          "total": int(event.get("total") or len(channels)), "found": result.count()}
                    await self.publish_state()
                elif kind in ("ensemble", "service"):
                    result.add(event)
                elif kind == "channel" and event.get("services"):
                    found = result.found().get(dablib.normalize_channel(event.get("channel")), {})
                    log.info("DAB scan %s: %s", event.get("channel"),
                             ", ".join(service["label"] for service in found.values()))
                elif kind == "error":
                    error = event
                elif kind == "done":
                    complete = bool(event.get("complete", True))
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            await stderr_task

        if self.scan_abort:
            pass  # cancelled: the old station list stays
        elif error or not complete:
            # openhu-dab ended during the scan: keep the old station list
            message = self.dab_error(error, lines)
            self.error = message if error and error.get("code") in STICK_ERRORS else \
                self.texts.text("org.openhu.radio.error.dab_scan_failed", message)
            log.error("DAB scan: %s", self.error)
        else:
            services = dablib.merge_scan(result.found())
            self.config["dabServices"] = services
            self.config["stations"][radiolib.DAB] = dablib.station_order(services)
            self.config.setdefault("names", {})[radiolib.DAB] = {
                key: service["label"] for key, service in services.items()}
            save_config(self.config)
            log.info("DAB scan: %d stations", len(services))
        self.scanning, self.scan_progress = False, None
        if was_playing and not self.scan_abort:
            await self.start()
        else:
            self.playing = False
            await self.publish_state()
