"""DAB/DAB+ for the radio plugin: playback, DLS, slideshow and the scan with welle-cli (see dablib.py).

welle-cli runs in its web server mode for the channel (ensemble) of the station; this module talks to it on
127.0.0.1 only: /mux.json for the services, DLS and slideshow changes, /mp3/<sid> for the sound (decoded by mpg123
or ffmpeg into pacat), /slide/<sid> for the picture, POST /channel to retune during the scan. One stick: the band
switch stops the FM/AM processes and vice versa (radio.py starts one or the other).
"""

import asyncio
import collections
import logging
import os
import time

import dablib
import radiolib
from openhu import save_config

log = logging.getLogger("radio")

CHUNK = 16384
METADATA_SECONDS = 2
# no ensemble with the station after this long: "no reception" (welle-cli keeps trying, the error goes away)
SYNC_SECONDS = 20
MAX_RESPONSE = 4 * 1024 * 1024
MAX_SLIDE_BYTES = 512 * 1024


class HttpError(Exception):
    pass


def parse_response(data):
    """Raw HTTP response -> (status, body)."""
    head, separator, body = data.partition(b"\r\n\r\n")
    if not separator:
        raise HttpError("incomplete response")
    try:
        status = int(head.split(b"\r\n", 1)[0].split()[1])
    except (IndexError, ValueError):
        raise HttpError("bad status line") from None
    return status, body


async def http_request(port, path, method="GET", body=b"", timeout=5.0):
    """Small HTTP/1.0 client for welle-cli on localhost -> (status, body); the server closes after the response."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout)
    try:
        request = "%s %s HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (
            method, path, len(body))
        writer.write(request.encode() + body)
        await writer.drain()
        data = b""
        deadline = time.monotonic() + timeout
        while len(data) <= MAX_RESPONSE:
            chunk = await asyncio.wait_for(reader.read(65536), max(0.1, deadline - time.monotonic()))
            if not chunk:
                break
            data += chunk
    finally:
        writer.close()
    return parse_response(data)


async def open_stream(port, path, timeout=10.0):
    """GET with a streamed body -> (reader, writer) after the headers; HttpError unless 200."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout)
    try:
        writer.write(("GET %s HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n" % path).encode())
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        status, _ = parse_response(head)
        if status != 200:
            raise HttpError("%s: HTTP %d" % (path, status))
    except BaseException:
        writer.close()
        raise
    return reader, writer


async def read_mux(port):
    status, body = await http_request(port, "/mux.json")
    if status != 200:
        raise HttpError("/mux.json: HTTP %d" % status)
    return dablib.parse_mux(body.decode("utf-8", "replace"))


async def drain(stream, lines):
    """Reads a chatty stderr (welle-cli logs a lot; a full pipe would block it), keeps the last lines."""
    while True:
        line = await stream.readline()
        if not line:
            return
        lines.append(line.decode(errors="replace").strip())


async def wait_for_server(port, process, seconds=15):
    """True once welle-cli's web server answers."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and process.returncode is None:
        try:
            await read_mux(port)
            return True
        except (OSError, asyncio.TimeoutError, HttpError):
            await asyncio.sleep(0.3)
    return False


class DabMixin:
    """DAB part of RadioPlugin (radio.py): uses its config, processes, tasks, rds, error and publish_* methods."""

    def dab_decoder(self):
        """MP3 decoder: mpg123 (small, for the OS image), else ffmpeg (dev image); None if neither is there."""
        return next((name for name in ("mpg123", "ffmpeg") if self.which(name)), None)

    def dab_available(self):
        return bool(self.which("welle-cli") and self.which("pacat") and self.dab_decoder())

    def dab_service(self, key=None):
        return self.config.get("dabServices", {}).get(key or self.config["frequency"].get(radiolib.DAB))

    def dab_port(self):
        return int(self.config.get("dabPort") or dablib.DEFAULT_PORT)

    async def start_welle(self, channel):
        args = dablib.welle_cli_command(channel, self.dab_port(), self.config)
        log.info("%s%s", " ".join(args), " (simulated stick)" if self.simulated() else "")
        return await radiolib.spawn(*args, stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE, env=self.environment())

    # --- playback -------------------------------------------------------------------------

    async def start_dab(self):
        key = self.config["frequency"].get(radiolib.DAB)
        service = self.dab_service(key)
        decoder = self.dab_decoder()
        if not service:
            self.error = self.texts.text("org.openhu.radio.error.no_dab_station")
        elif not (self.which("welle-cli") and self.which("pacat") and decoder):
            self.error = self.texts.text("org.openhu.radio.error.no_welle_cli")
        if self.error:
            self.playing = False
            await self.publish_state()
            return

        self.rds = {"ps": service.get("label", "")}
        self.dab_ensemble = {}
        await self.set_slide("")
        welle = await self.start_welle(service["channel"])
        read_fd, write_fd = os.pipe()
        mp3 = await radiolib.spawn(*dablib.mp3_decoder_command(decoder),
                                                   stdin=asyncio.subprocess.PIPE, stdout=write_fd,
                                                   stderr=asyncio.subprocess.DEVNULL)
        pacat = await radiolib.spawn(*radiolib.pacat_command(48000, 2), stdin=read_fd)
        os.close(read_fd)
        os.close(write_fd)
        self.processes = [welle, mp3, pacat]
        self.tasks = [asyncio.create_task(self.dab_audio(key, service, mp3)),
                      asyncio.create_task(self.dab_metadata(key)),
                      asyncio.create_task(self.watch_welle(welle))]
        self.playing = True
        await self.publish_state()

    async def wait_for_service(self, key, service):
        """Polls /mux.json until the ensemble carries the station; an error while it takes long, cleared after."""
        started = time.monotonic()
        reported = False
        while True:
            try:
                mux = await read_mux(self.dab_port())
                if mux["noDevice"]:
                    await self.dab_failed(self.texts.text("org.openhu.radio.error.no_stick"))
                    return False
                if key in mux["services"]:
                    if reported:
                        self.error = ""
                        await self.publish_state()
                    return True
            except (OSError, asyncio.TimeoutError, HttpError):
                pass  # welle-cli still starting
            if not reported and time.monotonic() - started > SYNC_SECONDS:
                reported = True
                self.error = self.texts.text("org.openhu.radio.error.dab_no_reception",
                                             dablib.station_label(service, key), service.get("channel"))
                log.warning("%s", self.error)
                await self.publish_state()
            await asyncio.sleep(1)

    async def dab_audio(self, key, service, mp3):
        """welle-cli's MP3 stream of the station -> decoder, again after interruptions."""
        while True:
            if not await self.wait_for_service(key, service):
                return
            try:
                reader, writer = await open_stream(self.dab_port(), "/mp3/" + dablib.welle_sid(key))
                try:
                    while True:
                        data = await reader.read(CHUNK)
                        if not data:
                            break
                        mp3.stdin.write(data)
                        await mp3.stdin.drain()
                finally:
                    writer.close()
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, HttpError) as error:
                log.info("DAB stream %s: %s", key, error)
            if mp3.returncode is not None:
                return
            await asyncio.sleep(1)

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

    async def dab_metadata(self, key):
        """Station name and DLS (as radiotext), ensemble, and the slideshow picture when it changed."""
        mot = None
        while True:
            await asyncio.sleep(METADATA_SECONDS)
            try:
                mux = await read_mux(self.dab_port())
            except (OSError, asyncio.TimeoutError, HttpError):
                continue
            service = mux["services"].get(key)
            if not service:
                continue
            rds = {"ps": service["label"] or self.rds.get("ps", "")}
            if service["dls"]:
                rds["rt"] = service["dls"]
            ensemble = mux["ensemble"] or {}
            if rds != self.rds or ensemble != self.dab_ensemble:
                self.rds, self.dab_ensemble = rds, ensemble
                await self.publish_state()
            if service["mot"] and service["mot"] != mot:
                mot = service["mot"]
                await self.fetch_slide(key)

    async def fetch_slide(self, key):
        try:
            status, body = await http_request(self.dab_port(), "/slide/" + dablib.welle_sid(key))
        except (OSError, asyncio.TimeoutError, HttpError) as error:
            log.info("DAB slide %s: %s", key, error)
            return
        if status != 200 or len(body) > MAX_SLIDE_BYTES:
            return
        image = radiolib.data_url(body)
        if image:
            await self.set_slide(image)

    async def watch_welle(self, welle):
        """welle-cli ends on its own only on errors (no stick, port in use); it writes a lot, only the end is kept."""
        lines = collections.deque(maxlen=20)
        await drain(welle.stderr, lines)
        await welle.wait()
        if self.playing and welle in self.processes:
            text = "\n".join(lines)
            self.error = next((line for line in reversed(lines) if line),
                              self.texts.text("org.openhu.radio.error.welle_cli_ended"))
            if "Could not start device" in text or "No supported devices" in text:
                self.error = self.texts.text("org.openhu.radio.error.no_stick")
            log.error("welle-cli: %s", self.error)
            await self.stop_processes()
            self.playing = False
            await self.publish_state()

    # --- scan -----------------------------------------------------------------------------

    def dab_scan_seconds(self):
        """How long a channel may take to show an ensemble (welle-cli syncs in about 1-3 s)."""
        return float(self.config.get("dabScanSeconds") or 5)

    async def scan_channel(self, channel):
        """Services of one channel: waits for the ensemble, then until its service list stops changing."""
        port = self.dab_port()
        deadline = time.monotonic() + self.dab_scan_seconds()
        services, stable = {}, 0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                mux = await read_mux(port)
            except (OSError, asyncio.TimeoutError, HttpError):
                continue
            current = dablib.scan_services(channel, mux)
            if mux["noDevice"]:
                self.scan_no_device = True
                return {}
            if mux["ensemble"] and current:
                # labels arrive one after the other: done once the list stayed the same twice
                stable = stable + 1 if current == services else 0
                services = current
                if stable >= 2:
                    break
                deadline = max(deadline, time.monotonic() + 1)
        return services

    async def scan_dab(self):
        """All Band III channels one after the other (POST /channel), takes minutes; progress in radio.state.scan."""
        if not self.which("welle-cli"):
            self.error = self.texts.text("org.openhu.radio.error.dab_scan_no_welle_cli")
            self.scanning = False
            await self.publish_state()
            return
        was_playing = self.playing
        await self.stop_processes()
        self.scanning, self.scan_abort, self.error = True, False, ""
        # all of Band III, or the channels in the config (dabChannels, e.g. only the ones used nearby)
        channels = [channel for channel in (dablib.normalize_channel(value) for value in
                                            self.config.get("dabChannels") or dablib.DAB_CHANNELS) if channel]
        found = {}
        welle = await self.start_welle(channels[0])
        lines = collections.deque(maxlen=20)
        reader = asyncio.create_task(drain(welle.stderr, lines))
        exited = None
        self.scan_no_device = False
        try:
            await wait_for_server(self.dab_port(), welle)
            for index, channel in enumerate(channels):
                if welle.returncode is not None:
                    exited = welle.returncode
                    break
                if self.scan_abort or self.scan_no_device:
                    break
                self.scan_progress = {"channel": channel, "done": index, "total": len(channels),
                                      "found": sum(len(services) for services in found.values())}
                await self.publish_state()
                if index > 0:
                    try:
                        await http_request(self.dab_port(), "/channel", method="POST", body=channel.encode())
                    except (OSError, asyncio.TimeoutError, HttpError) as error:
                        log.warning("DAB scan %s: %s", channel, error)
                        continue
                services = await self.scan_channel(channel)
                if services:
                    log.info("DAB scan %s: %s", channel, ", ".join(service["label"] for service in services.values()))
                    found[channel] = services
        finally:
            if welle.returncode is None:
                welle.terminate()
            try:
                await asyncio.wait_for(welle.wait(), 3)
            except asyncio.TimeoutError:
                welle.kill()
            await reader
            stderr = [line for line in lines if line]

        if self.scan_no_device:
            self.error = self.texts.text("org.openhu.radio.error.no_stick")
            log.error("DAB scan: %s", self.error)
        elif exited is not None:
            # welle-cli ended during the scan: keep the old station list
            self.error = self.texts.text("org.openhu.radio.error.dab_scan_failed",
                                         (stderr or [self.texts.tr("org.openhu.radio.error.welle_cli_ended")])[-1])
            if any("Could not start device" in line or "No supported devices" in line for line in stderr):
                self.error = self.texts.text("org.openhu.radio.error.no_stick")
            log.error("%s", self.error)
        elif not self.scan_abort:
            services = dablib.merge_scan(found)
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
