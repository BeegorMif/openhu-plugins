#!/usr/bin/env python3
"""FM/AM radio with an RTL-SDR stick: rtl_fm -> pacat, optional RDS via redsea, station scan via rtl_power.

State: "radio.state" {band, frequency, unit, playing, scanning, rds: {ps, rt}, presets, stations, error, rdsAvailable,
          simulated, bands: {fm|am: {min, max, step, unit, stations, presets, names: {"96.2": "NDR 2"}}}}
          (presets/stations: current band; bands: both, with the RDS names remembered per frequency)
Commands: bus.emit "radio.command" {cmd: "play"|"stop"|"toggle"|"tune"|"step"|"band"|"preset"|"savePreset"|
          "removePreset"|"scan"|"fakeSdr", value}
Actions: radio.toggle, radio.next, radio.previous (e.g. for steering wheel buttons); media.next/previous (seek),
          media.play_pause/play/pause while the radio is the current media source
Logos: "radio.logos" {fm: {"96.2": data URL}, am: {...}} – station logos from logos/ in the plugin data dir (PNG/JPEG
          named after the frequency, "96.2.png", or the station name, "NDR 2.png"; at most 512 KB each), sent only when
          they change (a separate topic keeps radio.state small). With the simulated stick also its "logo" files.
Media: while playing also media.metadata / media.status with source "radio" (home page, Bluetooth car radio), the
          station logo as cover; "stopped" only if the radio was the last media source (not when Android Auto music
          took over)
Config (plugin data dir): gain ("auto" or dB), ppm, amOptions (rtl_fm arguments for AM, default direct sampling),
          rds, pauseForAndroidAuto, fakeSdr (simulated stick, tools/fake-sdr; also OPENHU_FAKE_SDR=1)
"""

import asyncio
import logging
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import radiolib  # noqa: E402
from openhu import DATA_DIR, OpenHU, load_config, save_config, setup_logging  # noqa: E402

log = logging.getLogger("radio")

# Simulated stick for tests without hardware: rtl_fm/rtl_power/redsea stand-ins, first in PATH when switched on
FAKE_SDR_DIR = os.path.normpath(os.path.join(HERE, "..", "tools", "fake-sdr"))
LOGO_POLL_SECONDS = 10

DEFAULTS = {
    "band": "fm",
    "frequency": {"fm": 101.3, "am": 1008},
    "presets": {"fm": [], "am": []},
    "stations": {"fm": [], "am": []},
    "names": {"fm": {}, "am": {}},
    "gain": "auto",
    "ppm": 0,
    "amOptions": ["-E", "direct2"],
    "rds": True,
    "pauseForAndroidAuto": True,
    "fakeSdr": False,
}
CHUNK = 4096


class RadioPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.api = OpenHU()
        self.processes = []
        self.tasks = []
        self.playing = False
        self.scanning = False
        self.rds = {}
        self.error = ""
        # Source that started last (radio, androidauto, ...): it owns the media keys, also while paused. Only starts
        # count: after the radio started, the phone still reports "playing" until OpenHU's focus loss arrives (#79).
        self.media_owner = None
        self.android_auto_playing = False
        self.media_sent = None
        self.logos = {}  # {band: {frequency key: data URL}}
        self.logos_sent = False
        self.logo_cache = {}  # path -> ((mtime, size), data URL or None)
        self.logo_task = None
        # Every event runs as its own task: commands that come quickly one after the other (Android Auto sends
        # band, tune and play together) would overtake each other while processes start and stop.
        self.lock = asyncio.Lock()
        self.api.on("radio.command", self.on_command)
        self.api.on("input.action", self.on_action)
        self.api.on("media.status", self.on_media_status)

    @property
    def band(self):
        return self.config["band"]

    @property
    def frequency(self):
        return self.config["frequency"][self.band]

    def simulated(self):
        return bool(self.config.get("fakeSdr")) or os.environ.get("OPENHU_FAKE_SDR") == "1"

    def environment(self):
        """Environment for the tools: with the simulated stick its directory comes first in PATH."""
        env = dict(os.environ)
        if self.simulated():
            env["PATH"] = FAKE_SDR_DIR + os.pathsep + env.get("PATH", "")
            own = os.path.join(DATA_DIR, "fake-sdr-stations.json")
            env.setdefault("OPENHU_FAKE_SDR_STATIONS",
                           own if os.path.isfile(own) else os.path.join(FAKE_SDR_DIR, "stations.json"))
        return env

    def which(self, name):
        return shutil.which(name, path=self.environment()["PATH"])

    def rds_available(self):
        return self.band == "fm" and self.config["rds"] and self.which("redsea") and self.which("sox")

    # --- playback ---------------------------------------------------------------

    async def start(self):
        if self.processes:
            # another station or band: show it right away, stopping the old processes takes a moment
            self.rds = {}
            await self.publish_state()
        await self.stop_processes()
        if self.which("rtl_fm") is None or self.which("pacat") is None:
            self.error = "rtl_fm oder pacat fehlt (Pakete rtl-sdr, pulseaudio-utils)"
            self.playing = False
            await self.publish_state()
            return

        self.rds = {}
        self.error = ""
        rds = bool(self.rds_available())
        args, rate = radiolib.rtl_fm_command(self.band, self.frequency, self.config, rds)
        env = self.environment()
        log.info("%s%s", " ".join(args), " (simulated stick)" if self.simulated() else "")

        if rds:
            # rtl_fm (multiplex) -> this process -> redsea (RDS) and sox (audio) -> pacat
            rtl = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE, env=env)
            redsea = await asyncio.create_subprocess_exec("redsea", "-r", "171k", stdin=asyncio.subprocess.PIPE,
                                                          stdout=asyncio.subprocess.PIPE,
                                                          stderr=asyncio.subprocess.DEVNULL, env=env)
            read_fd, write_fd = os.pipe()
            sox = await asyncio.create_subprocess_exec(*radiolib.sox_mpx_to_audio(), stdin=asyncio.subprocess.PIPE,
                                                       stdout=write_fd, stderr=asyncio.subprocess.DEVNULL)
            pacat = await asyncio.create_subprocess_exec(*radiolib.pacat_command(44100), stdin=read_fd)
            os.close(read_fd)
            os.close(write_fd)
            self.processes = [rtl, redsea, sox, pacat]
            self.tasks = [asyncio.create_task(self.split(rtl, [redsea, sox]), name="split"),
                          asyncio.create_task(self.read_rds(redsea)),
                          asyncio.create_task(self.watch(rtl))]
        else:
            read_fd, write_fd = os.pipe()
            rtl = await asyncio.create_subprocess_exec(*args, stdout=write_fd, stderr=asyncio.subprocess.PIPE, env=env)
            pacat = await asyncio.create_subprocess_exec(*radiolib.pacat_command(rate), stdin=read_fd)
            os.close(read_fd)
            os.close(write_fd)
            self.processes = [rtl, pacat]
            self.tasks = [asyncio.create_task(self.watch(rtl))]

        self.playing = True
        await self.publish_state()

    async def split(self, source, targets):
        while True:
            data = await source.stdout.read(CHUNK)
            if not data:
                break
            for target in targets:
                try:
                    target.stdin.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            await asyncio.gather(*(target.stdin.drain() for target in targets), return_exceptions=True)

    async def read_rds(self, redsea):
        while True:
            line = await redsea.stdout.readline()
            if not line:
                break
            update = radiolib.parse_redsea(line.decode(errors="replace"))
            if update and any(self.rds.get(key) != value for key, value in update.items()):
                self.rds.update(update)
                if self.playing and radiolib.remember_name(self.config.setdefault("names", {}), self.band,
                                                           self.frequency, update.get("ps")):
                    save_config(self.config)
                await self.publish_state()

    async def watch(self, rtl):
        """rtl_fm ends on its own only on errors (no stick, stick busy)."""
        stderr = await rtl.stderr.read()
        await rtl.wait()
        if self.playing and rtl in self.processes:
            message = stderr.decode(errors="replace").strip().splitlines()
            self.error = next((line for line in reversed(message) if line), "rtl_fm beendet")
            if "No supported devices" in stderr.decode(errors="replace"):
                self.error = "Kein RTL-SDR-Stick gefunden"
            log.error("rtl_fm: %s", self.error)
            await self.stop_processes()
            self.playing = False
            await self.publish_state()

    async def stop_processes(self):
        processes, self.processes = self.processes, []
        tasks, self.tasks = self.tasks, []
        # RDS reader and watcher first: no RDS line of the old station after the new one is shown. The split task
        # keeps draining rtl_fm until it ended (a full pipe could block it).
        for task in tasks:
            if task.get_name() != "split":
                task.cancel()
        for process in processes:
            if process.returncode is None:
                process.terminate()
        for process in processes:
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
        for task in tasks:
            task.cancel()

    async def stop(self):
        await self.stop_processes()
        self.playing = False
        await self.publish_state()

    async def tune(self, frequency):
        self.config["frequency"][self.band] = radiolib.clamp_frequency(self.band, frequency)
        save_config(self.config)
        if self.playing:
            await self.start()
        else:
            await self.publish_state()

    # --- station scan (FM) ----------------------------------------------------------

    async def scan(self):
        if self.band != "fm" or self.which("rtl_power") is None:
            self.error = "Sendersuche nur für FM, braucht rtl_power"
            await self.publish_state()
            return
        was_playing = self.playing
        await self.stop_processes()
        self.scanning = True
        self.error = ""
        await self.publish_state()

        process = await asyncio.create_subprocess_exec(
            "rtl_power", "-f", "87.5M:108M:100k", "-i", "2", "-1", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=self.environment())
        stdout, stderr = await process.communicate()
        stations = radiolib.parse_rtl_power(stdout.decode(errors="replace").splitlines())
        if process.returncode != 0 and not stations:
            self.error = "Sendersuche fehlgeschlagen: " + (stderr.decode(errors="replace").strip().splitlines() or ["?"])[-1]
        self.config["stations"]["fm"] = stations
        save_config(self.config)
        self.scanning = False
        log.info("scan: %d stations", len(stations))

        if was_playing:
            await self.start()
        else:
            self.playing = False
            await self.publish_state()

    def neighbour_station(self, direction):
        """Next station of the scan list (or preset) in the given direction, wrapping around."""
        stations = sorted(set(self.config["stations"].get(self.band, []) + self.config["presets"].get(self.band, [])))
        if not stations:
            return radiolib.step_frequency(self.band, self.frequency, direction)
        if direction > 0:
            return next((s for s in stations if s > self.frequency + 1e-6), stations[0])
        return next((s for s in reversed(stations) if s < self.frequency - 1e-6), stations[-1])

    # --- station logos ---------------------------------------------------------------

    @staticmethod
    def logo_dir():
        """Station logos the user puts there (none are bundled)"""
        return os.path.join(DATA_DIR, "logos")

    def fake_logos(self):
        """"logo" files of the simulated stick's station list."""
        try:
            if FAKE_SDR_DIR not in sys.path:
                sys.path.append(FAKE_SDR_DIR)
            import fakesdr
            path = self.environment()["OPENHU_FAKE_SDR_STATIONS"]
            return fakesdr.station_logos(fakesdr.load_stations(path), path)
        except (ImportError, OSError, ValueError, KeyError):
            return {}

    def logo_paths(self):
        """Logo file of every known station: {band: {frequency key: path}}. A file in logos/ named after the frequency,
        else after the remembered RDS name, else (simulated stick) the station list's logo."""
        try:
            files = os.listdir(self.logo_dir())
        except OSError:
            files = []
        index = radiolib.logo_index(files)
        fake = self.fake_logos() if self.simulated() else {}
        result = {}
        for band in radiolib.BANDS:
            names = self.config.get("names", {}).get(band, {})
            for key in radiolib.logo_keys(self.config, band, self.config["frequency"].get(band)):
                file = radiolib.find_logo(index, band, key, names.get(key, ""))
                path = os.path.join(self.logo_dir(), file) if file else fake.get(band, {}).get(key)
                if path:
                    result.setdefault(band, {})[key] = path
        return result

    def read_logo(self, path):
        """Data URL of a logo file, read again only when it changed; None if it is missing, too big or no PNG/JPEG."""
        try:
            stat = os.stat(path)
        except OSError:
            return None
        version = (stat.st_mtime, stat.st_size)
        cached = self.logo_cache.get(path)
        if cached and cached[0] == version:
            return cached[1]
        url = None
        if stat.st_size > radiolib.MAX_LOGO_BYTES:
            log.warning("logo %s: %d KB, at most %d KB", path, -(-stat.st_size // 1024),
                        radiolib.MAX_LOGO_BYTES // 1024)
        else:
            try:
                with open(path, "rb") as file:
                    url = radiolib.data_url(file.read())
            except OSError as error:
                log.warning("logo %s: %s", path, error)
            else:
                if url is None:
                    log.warning("logo %s: neither PNG nor JPEG", path)
        self.logo_cache[path] = (version, url)
        return url

    async def publish_logos(self):
        """radio.logos, only when a logo changed (or after a new connection); True if it was sent."""
        logos = {}
        for band, paths in self.logo_paths().items():
            for key, path in paths.items():
                url = self.read_logo(path)
                if url:
                    logos.setdefault(band, {})[key] = url
        if self.logos_sent and logos == self.logos:
            return False
        self.logos = logos
        self.logos_sent = True
        log.info("logos: %d", sum(len(band) for band in logos.values()))
        await self.api.safe(self.api.publish("radio.logos", **{band: logos.get(band, {}) for band in radiolib.BANDS}))
        return True

    async def watch_logos(self):
        """Picks up logo files the user adds or changes while the plugin runs."""
        while True:
            await asyncio.sleep(LOGO_POLL_SECONDS)
            try:
                if await self.publish_logos():
                    await self.publish_media()
            except Exception:
                log.exception("logos")

    def current_logo(self):
        return self.logos.get(self.band, {}).get(radiolib.frequency_key(self.band, self.frequency), "")

    async def on_connect(self):
        # OpenHU may have restarted: send the logos again
        self.logos_sent = False
        if self.logo_task is None:
            try:
                # the folder for the user's logo files
                os.makedirs(self.logo_dir(), exist_ok=True)
            except OSError:
                pass
            self.logo_task = asyncio.create_task(self.watch_logos())
        await self.publish_state()

    # --- commands -------------------------------------------------------------------

    async def on_command(self, topic, data):
        async with self.lock:
            await self.handle_command(data)

    async def handle_command(self, data):
        command, value = data.get("cmd"), data.get("value")
        if self.scanning and command != "stop":
            return
        if command == "play":
            if radiolib.start_needed(self.playing, bool(self.processes)):
                await self.start()
            else:
                await self.publish_state()
        elif command == "stop":
            await self.stop()
        elif command == "toggle":
            await (self.stop() if self.playing else self.start())
        elif command == "tune" and value is not None:
            await self.tune(value)
        elif command == "step":
            await self.tune(radiolib.step_frequency(self.band, self.frequency, value or 1))
        elif command == "seek":
            await self.tune(self.neighbour_station(value or 1))
        elif command == "band" and value in radiolib.BANDS:
            self.config["band"] = value
            save_config(self.config)
            await (self.start() if self.playing else self.publish_state())
        elif command == "savePreset":
            presets = self.config["presets"].setdefault(self.band, [])
            if self.frequency not in presets:
                presets.append(self.frequency)
                presets.sort()
            save_config(self.config)
            await self.publish_state()
        elif command == "removePreset":
            presets = self.config["presets"].get(self.band, [])
            if value in presets:
                presets.remove(value)
            save_config(self.config)
            await self.publish_state()
        elif command == "scan":
            await self.scan()
        elif command == "fakeSdr":
            self.config["fakeSdr"] = bool(value)
            save_config(self.config)
            log.info("simulated stick %s", "on" if value else "off")
            await (self.start() if self.playing else self.publish_state())
        else:
            log.warning("unknown command %s", data)

    async def on_action(self, topic, data):
        if data.get("phase") == "release":
            return
        # media keys only while the radio is the current media source (also after it was stopped: play resumes)
        command = radiolib.action_command(data.get("action"), self.media_owner == "radio")
        if command:
            await self.on_command(topic, command)

    async def on_media_status(self, topic, data):
        source, playing = data.get("source"), data.get("state") == "playing"
        if source == "radio":
            return
        if source == "androidauto":
            started = playing and not self.android_auto_playing
            self.android_auto_playing = playing
        else:
            # another local source
            started = playing and self.media_owner != source
        if not started:
            return
        self.media_owner = source
        # Android Auto (or another source) starts playing music: radio off
        if self.config["pauseForAndroidAuto"] and self.playing:
            log.info("%s started playing, radio stopped", source)
            async with self.lock:
                await self.stop()

    async def publish_media(self):
        """The radio as the current media source, sent only when something changed."""
        if self.playing:
            metadata = radiolib.media_metadata(self.band, self.frequency, self.rds, self.config.get("names", {}),
                                               self.current_logo())
            if metadata == self.media_sent:
                return
            self.media_sent = metadata
            self.media_owner = "radio"
            await self.api.safe(self.api.publish("media.metadata", **metadata))
            await self.api.safe(self.api.publish("media.status", state="playing", app="Radio", position=0,
                                                 shuffle=False, repeat=False, repeatOne=False, source="radio"))
        elif self.media_sent is not None:
            self.media_sent = None
            # do not overwrite Android Auto's status when its music stopped the radio
            if self.media_owner == "radio":
                await self.api.safe(self.api.publish("media.status", state="stopped", app="Radio", source="radio"))

    async def publish_state(self):
        await self.publish_logos()
        await self.publish_media()
        spec = radiolib.BANDS[self.band]
        await self.api.safe(self.api.publish(
            "radio.state",
            band=self.band,
            frequency=self.frequency,
            unit=spec["unit"],
            min=spec["min"],
            max=spec["max"],
            playing=self.playing,
            scanning=self.scanning,
            rds=self.rds,
            rdsAvailable=bool(self.rds_available()),
            presets=self.config["presets"].get(self.band, []),
            stations=self.config["stations"].get(self.band, []),
            error=self.error,
            simulated=self.simulated(),
            bands=radiolib.band_summary(self.config),
        ))


if __name__ == "__main__":
    setup_logging()
    plugin = RadioPlugin()
    asyncio.run(plugin.api.run(plugin.on_connect))
