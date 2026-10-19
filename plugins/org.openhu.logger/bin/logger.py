#!/usr/bin/env python3
"""Vehicle data logger: records vehicle.* and some OpenHU and head unit values into SQLite (OPENHU_DATA_DIR/logger.db),
detects trips and answers queries of other plugins. It only logs: charts, export, forwarding are other plugins that
use the interface below (README.md).

Config (plugin data dir, config.json; the page and "set" change it):
    enabled           logging on (default off: nothing is recorded until the user switches it on)
    groups            {"vehicle": true, "openhu": true, "health": true, "position": false, "can": false}
    interval          seconds between readings of the head unit values (1-60, default 5)
    rates             {"<signal or pattern>": seconds (0.1-3600) or "update"}, default {"vehicle.*": 5}, e.g.
                      {"vehicle.engine.*": "update", "vehicle.speed.kmh": 1}; the most specific pattern wins;
                      "update" = every change as it arrives (also for signals without a rate)
    limitMB           size limit of the database (default 1024); the oldest raw samples go first
    maxAgeDays        raw samples older than this are dropped (0 = no limit)
    stopMinutes       a trip ends after standing still this long (default 10)
    engineOffSeconds  ... or when the engine stays off this long (default 60)
    flushSeconds      rows are written in batches this often (default 30)
    recording         high-rate recordings: {"keys": ["vehicle.*"], "triggers": [{"key": "vehicle.engine.rpm",
                      "above": 3000}], "preSeconds": 5, "postSeconds": 10, "maxSeconds": 600, "limitMB": 256}

Bus (details in README.md):
    logger.query   {id, cmd: trips|trip|recordings|signals|samples|events|live|status, ...}
                                                       -> logger.result {id, cmd, ok, ...}
    logger.command {id, cmd: set|record|deleteRecording|clear, ...}  -> logger.result if id is given
    logger.state   (published) settings, storage use, open trip - for the page
    logger.live    (published every second) current values and the open trip
    logger.trip    (one-shot) {event: start|end, trip}
    logger.recording (one-shot) {event: start|end, recording}
"""

import asyncio
import glob
import json
import logging
import os
import shutil
import signal
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import openhu  # noqa: E402
from logstore import QueryError, Store  # noqa: E402
from recorder import METADATA_TOPIC, OPENHU_TOPICS, Recorder, valid_rate  # noqa: E402

log = logging.getLogger("logger")

DEFAULTS = {
    "enabled": False,
    "groups": {"vehicle": True, "openhu": True, "health": True, "position": False, "can": False},
    "interval": 5,
    "rates": {"vehicle.*": 5},
    "limitMB": 1024,
    "maxAgeDays": 0,
    "stopMinutes": 10,
    "engineOffSeconds": 60,
    "flushSeconds": 30,
    "recording": {"keys": ["vehicle.*"], "triggers": [], "preSeconds": 5, "postSeconds": 10, "maxSeconds": 600,
                  "limitMB": 256},
}
# settable with {cmd: "set", key, value}: (minimum, maximum) or bool
SETTABLE = {
    "enabled": bool, "interval": (1, 60), "limitMB": (50, 1_048_576), "maxAgeDays": (0, 36_500),
    "stopMinutes": (1, 240), "engineOffSeconds": (0, 3600), "flushSeconds": (5, 600),
    "groups.vehicle": bool, "groups.openhu": bool, "groups.health": bool, "groups.position": bool, "groups.can": bool,
    "recording.limitMB": (10, 1_048_576), "recording.preSeconds": (0, 60), "recording.postSeconds": (0, 3600),
    "recording.maxSeconds": (1, 86_400),
}
STATE_SECONDS = 30
ENFORCE_SECONDS = 60


def now_ms():
    return int(time.time() * 1000)


def load_config(path):
    config = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path) as file:
            saved = json.load(file)
        groups = saved.pop("groups", {})
        recording = saved.pop("recording", {})
        config.update({key: value for key, value in saved.items() if key in DEFAULTS})
        config["groups"].update({key: bool(value) for key, value in groups.items() if key in DEFAULTS["groups"]})
        config["recording"].update({key: value for key, value in recording.items()
                                    if key in DEFAULTS["recording"]})
    except (OSError, ValueError, AttributeError):
        pass
    return config


def save_config(path, config):
    with open(path + ".tmp", "w") as file:
        json.dump(config, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(path + ".tmp", path)


def read_health(data_dir):
    """headunit.* values (recorder.HEADUNIT_SIGNALS), from local files, rounded so they change less often."""
    values = {}
    temps = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(path) as file:
                temps.append(int(file.read().strip()) / 1000.0)
        except (OSError, ValueError):
            pass
    if temps:
        values["headunit.cpu_temp_c"] = round(max(temps))
    try:
        values["headunit.cpu_load"] = round(os.getloadavg()[0], 1)
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as file:
            for line in file:
                if line.startswith("MemAvailable:"):
                    values["headunit.memory_free_mb"] = int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        values["headunit.disk_free_mb"] = shutil.disk_usage(data_dir).free // (1024 * 1024)
    except OSError:
        pass
    return values


def system_info():
    info = {}
    try:
        with open("/etc/os-release") as file:
            release = dict(line.rstrip("\n").split("=", 1) for line in file if "=" in line)
        info["os"] = ("%s %s" % (release.get("NAME", ""), release.get("VERSION", release.get("VERSION_ID", ""))))\
            .replace('"', "").strip()
    except OSError:
        pass
    try:
        with open(os.path.join(HERE, "..", "manifest.json")) as file:
            info["loggerVersion"] = json.load(file).get("version")
    except (OSError, ValueError):
        pass
    return info


class LoggerPlugin:
    def __init__(self, data_dir=None, api=None, overrides=None, health=read_health):
        self.data_dir = data_dir or openhu.DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.config_path = os.path.join(self.data_dir, "config.json")
        self.config = load_config(self.config_path)
        self.config.update(overrides or {})
        self.api = api or openhu.OpenHU()
        self.health = health
        info = system_info()
        self.store = Store(os.path.join(self.data_dir, "logger.db"), info.get("loggerVersion"))
        if self.store.old_schema:
            log.info("database of an older version moved to %s", self.store.old_schema)
        self.reader = self.store.reader()
        self.read_lock = asyncio.Lock()
        self.recorder = Recorder(self.store, self.config, info)
        self.recorder.restore(now_ms())
        self.error = ""
        self.stopping = asyncio.Event()

        self.api.on("vehicle.*", self.on_topic)
        self.api.on("can.*", self.on_topic)
        for topic in OPENHU_TOPICS:
            self.api.on(topic, self.on_topic)
        self.api.on(METADATA_TOPIC, self.on_signals_info)
        self.api.on("logger.query", self.on_query)
        self.api.on("logger.command", self.on_command)

    # --- recording ------------------------------------------------------------------

    async def on_topic(self, topic, data):
        self.recorder.on_topic(topic, data, now_ms())
        await self.announce()

    async def on_signals_info(self, topic, data):
        try:
            self.recorder.on_signals_info(data)
        except sqlite3.Error as error:
            log.warning("signal info: %s", error)

    async def announce(self):
        while self.recorder.announcements:
            topic, data = self.recorder.announcements.pop(0)
            await self.api.safe(self.api.emit(topic, **data))
            await self.publish_state()

    def flush(self):
        try:
            self.recorder.flush()
        except (sqlite3.Error, OSError) as error:
            log.warning("writing failed: %s", error)

    def enforce(self):
        try:
            dropped = self.store.enforce(int(self.config["limitMB"]) * 1024 * 1024,
                                         int(self.config["maxAgeDays"]) * 86_400_000, now_ms(),
                                         int(self.config["recording"]["limitMB"]) * 1024 * 1024)
            if dropped:
                log.info("size limit: dropped %d old samples", dropped)
        except sqlite3.Error as error:
            log.warning("size limit: %s", error)

    async def tick_loop(self):
        last_flush = last_enforce = last_state = last_interval = last_live = time.monotonic()
        self.enforce()
        while not self.stopping.is_set():
            try:
                await asyncio.wait_for(self.stopping.wait(), max(0.05, self.recorder.fastest_rate()))
                break
            except asyncio.TimeoutError:
                pass
            t = now_ms()
            current = time.monotonic()
            # head unit values at the interval; samples at the fastest rate; trips and logger.live every second
            interval = current - last_interval >= float(self.config["interval"]) - 0.02
            if interval:
                last_interval = current
            second = current - last_live >= 0.98
            if second:
                last_live = current
            if self.config["enabled"]:
                health = self.health(self.data_dir) if interval and self.config["groups"].get("health") else None
                self.recorder.tick(t, health)
            await self.announce()
            if second and self.api.connected:
                await self.api.safe(self.api.publish("logger.live", **self.recorder.live(t)))
            if current - last_flush >= float(self.config["flushSeconds"]):
                last_flush = current
                self.flush()
            if current - last_enforce >= ENFORCE_SECONDS:
                last_enforce = current
                self.enforce()
            if current - last_state >= STATE_SECONDS:
                last_state = current
                await self.publish_state()

    # --- state and commands ---------------------------------------------------------

    def state(self):
        try:
            usage = self.store.stats()
        except sqlite3.Error as error:
            usage = {}
            log.warning("stats: %s", error)
        usage["limitBytes"] = int(self.config["limitMB"]) * 1024 * 1024
        config = {key: value for key, value in self.config.items() if key in DEFAULTS}
        usage["recordingLimitBytes"] = int(self.config["recording"]["limitMB"]) * 1024 * 1024
        return dict(config, usage=usage, trip=self.recorder.trip, recording=self.recorder.public_recording(),
                    vehicleData=self.recorder.vehicle_data,
                    error=self.recorder.error or self.error,
                    recovered=os.path.basename(self.store.recovered) if self.store.recovered else "",
                    oldSchema=os.path.basename(self.store.old_schema) if self.store.old_schema else "")

    async def publish_state(self):
        if self.api.connected:
            await self.api.safe(self.api.publish("logger.state", **self.state()))

    async def reply(self, data, result=None, error=None):
        if data.get("id") is None:
            return
        message = {"id": data.get("id"), "cmd": data.get("cmd"), "ok": error is None}
        if error is not None:
            message["error"] = error
        else:
            message.update(result or {})
        await self.api.safe(self.api.emit("logger.result", **message))

    def set_value(self, key, value):
        if key == "rates" or key.startswith("rates."):
            rates = dict(self.config.get("rates") or {})
            if key == "rates":
                if not isinstance(value, dict):
                    raise QueryError("rates must be an object")
                rates = value
            elif value is None:
                rates.pop(key[6:], None)
            else:
                rates[key[6:]] = value
            for pattern, rate in rates.items():
                if not isinstance(pattern, str) or not pattern or not valid_rate(rate):
                    raise QueryError("rate of %s must be 0.1..3600 (seconds) or \"update\"" % pattern)
            self.config["rates"] = rates
        elif key in ("recording.keys", "recording.triggers"):
            self.config["recording"][key[10:]] = self.check_list(key, value)
        else:
            self.set_simple(key, value)
        self.recorder.apply_config()
        save_config(self.config_path, self.config)

    @staticmethod
    def check_list(key, value):
        if not isinstance(value, list):
            raise QueryError("%s must be a list" % key)
        for item in value:
            if key == "recording.keys" and not (isinstance(item, str) and item):
                raise QueryError("recording.keys: keys or patterns such as \"vehicle.*\"")
            if key == "recording.triggers" and not (
                    isinstance(item, dict) and isinstance(item.get("key"), str)
                    and any(condition in item for condition in ("above", "below", "equals"))
                    and all(isinstance(item[c], (int, float)) for c in ("above", "below") if c in item)):
                raise QueryError("recording.triggers: [{\"key\": ..., \"above\"|\"below\"|\"equals\": ...}]")
        return value

    def set_simple(self, key, value):
        kind = SETTABLE.get(key)
        if kind is None:
            raise QueryError("unknown setting %s" % key)
        if kind is bool:
            if not isinstance(value, bool):
                raise QueryError("%s must be true or false" % key)
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not kind[0] <= value <= kind[1]:
                raise QueryError("%s must be a number %s..%s" % (key, kind[0], kind[1]))
            value = int(value) if float(value).is_integer() else value
        if key.startswith("groups."):
            self.config["groups"][key[7:]] = value
        elif key.startswith("recording."):
            self.config["recording"][key[10:]] = value
        else:
            was = self.config["enabled"]
            self.config[key] = value
            if key == "enabled" and was and not value:
                self.recorder.disable(now_ms())

    async def on_command(self, topic, data):
        command = data.get("cmd")
        try:
            if command == "set":
                self.set_value(str(data.get("key")), data.get("value"))
                if data.get("key") in ("limitMB", "maxAgeDays", "recording.limitMB"):
                    self.enforce()
            elif command == "record":
                result = self.record(data)
                await self.announce()
                await self.publish_state()
                await self.reply(data, result)
                return
            elif command == "deleteRecording":
                if self.recorder.recording is not None and self.recorder.recording["id"] == data.get("recording"):
                    raise QueryError("the recording is running")
                async with self.read_lock:
                    self.store.delete_recording(int(data.get("recording")))
            elif command == "clear":
                await self.clear()
            else:
                raise QueryError("unknown command %s" % command)
        except (QueryError, ValueError, TypeError) as error:
            await self.reply(data, error=str(error))
            return
        except sqlite3.Error as error:
            await self.reply(data, error="database: %s" % error)
            return
        await self.announce()
        await self.publish_state()
        await self.reply(data, {})

    def record(self, data):
        action = data.get("action")
        t = now_ms()
        if action == "start":
            if not self.config["enabled"]:
                raise QueryError("logging is off")
            seconds = data.get("seconds")
            if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                                        or seconds <= 0):
                raise QueryError("seconds must be a positive number")
            if self.recorder.recording is not None:
                raise QueryError("a recording is running")
            recording = self.recorder.start_recording(t, "manual", str(data.get("label") or ""), seconds)
            if recording is None:
                raise QueryError("could not start: %s" % self.recorder.error)
            return {"recording": self.recorder.public_recording()}
        if action == "stop":
            recording = self.recorder.stop_recording(t, "manual")
            if recording is None:
                raise QueryError("no recording is running")
            return {"recording": self.recorder.public_recording(recording)}
        raise QueryError("action must be start or stop")

    async def clear(self):
        async with self.read_lock:
            self.reader.close()
            self.store.clear()
            self.reader = self.store.reader()
        self.recorder.reset()
        log.info("all data deleted")

    async def on_query(self, topic, data):
        command = data.get("cmd")
        try:
            if command == "live":
                result = self.recorder.live(now_ms())
            elif command == "status":
                result = self.state()
            else:
                async with self.read_lock:
                    result = await asyncio.to_thread(self.query, self.reader, command, data, now_ms())
        except (QueryError, ValueError, TypeError) as error:
            await self.reply(data, error=str(error))
            return
        except sqlite3.Error as error:
            log.warning("query %s: %s", command, error)
            await self.reply(data, error="database: %s" % error)
            return
        await self.reply(data, result)

    @staticmethod
    def query(reader, command, data, now):
        if command == "trips":
            return reader.trips(data.get("start"), data.get("end"), data.get("before"), data.get("limit", 50))
        if command == "trip":
            return reader.trip(data.get("trip"))
        if command == "recordings":
            return reader.recordings(data.get("start"), data.get("end"), data.get("before"), data.get("limit", 50))
        if command in ("signals", "keys"):
            return reader.signals()
        if command == "samples":
            start, end = reader.range_of(data, now)
            keys = data.get("keys", data.get("signals"))
            if keys is not None and not isinstance(keys, list):
                raise QueryError("keys must be a list")
            return reader.samples(start, end, keys, data.get("points", 300), data.get("limit", 5000))
        if command == "events":
            start, end = reader.range_of(data, now)
            return reader.events(start, end, data.get("key") or data.get("topic"), data.get("limit", 1000))
        raise QueryError("unknown query %s" % command)

    # --- main -----------------------------------------------------------------------

    def stop(self):
        self.stopping.set()

    async def main(self):
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(signum, self.stop)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        api_task = asyncio.create_task(self.api.run(self.publish_state))
        try:
            await self.tick_loop()
        finally:
            api_task.cancel()
            try:
                await api_task  # closes the connection
            except BaseException:
                pass
            # a trip stays open: it goes on after a restart or is closed at the next start (Trips.restore)
            self.flush()
            self.reader.close()
            self.store.close()
            log.info("stopped")


if __name__ == "__main__":
    openhu.setup_logging()
    asyncio.run(LoggerPlugin().main())
