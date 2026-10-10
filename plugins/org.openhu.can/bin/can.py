#!/usr/bin/env python3
"""CAN bus plugin: SocketCAN -> vehicle.* topics, steering wheel buttons -> actions.

Config (plugin data dir, editable on the plugin page):
    interface   SocketCAN interface, e.g. can0 or vcan0
    profile     vehicle profile, profiles/<name>.json (plugin) or <data dir>/profiles/<name>.json (own)
    monitor     publish all received frames as "can.monitor" (to find the ids of a car)
Commands: bus.emit "can.command" {cmd: "interface"|"profile"|"monitor"|"reload", value}
"""

import asyncio
import json
import logging
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import canbus  # noqa: E402
from openhu import DATA_DIR, PLUGIN_DIR, OpenHU, load_config, save_config, setup_logging  # noqa: E402

log = logging.getLogger("can")

DEFAULTS = {"interface": "can0", "profile": "example", "monitor": False}
PUBLISH_INTERVAL = 0.1


def profile_dirs():
    return [os.path.join(DATA_DIR, "profiles"), os.path.join(PLUGIN_DIR, "profiles")]


def list_profiles():
    names = set()
    for directory in profile_dirs():
        if os.path.isdir(directory):
            names.update(name[:-5] for name in os.listdir(directory) if name.endswith(".json"))
    return sorted(names)


def load_profile(name):
    for directory in profile_dirs():
        path = os.path.join(directory, name + ".json")
        if os.path.isfile(path):
            with open(path) as file:
                return canbus.Profile(json.load(file))
    raise FileNotFoundError("profile %s not found" % name)


class CanPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.api = OpenHU()
        self.profile = None
        self.profile_error = ""
        self.sock = None
        self.error = ""
        self.frames = 0
        self.frames_per_second = 0
        self.monitor = {}        # id -> [data, count, time]
        self.pending = {}        # topic -> fields, published in batches
        self.reopen = asyncio.Event()
        self.api.on("can.command", self.on_command)
        self.load_profile()

    def load_profile(self):
        try:
            self.profile = load_profile(self.config["profile"])
            self.profile_error = ""
            log.info("profile %s: %s", self.config["profile"], self.profile.name)
        except (OSError, ValueError, KeyError) as error:
            self.profile = None
            self.profile_error = str(error)
            log.error("profile: %s", error)

    # --- CAN socket -------------------------------------------------------------

    async def can_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            self.reopen.clear()
            interface = self.config["interface"]
            try:
                self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
                self.sock.bind((interface,))
                self.sock.setblocking(False)
                loop.add_reader(self.sock.fileno(), self.on_readable)
                self.error = ""
                log.info("listening on %s", interface)
                await self.reopen.wait()
            except OSError as error:
                self.error = "%s: %s" % (interface, error.strerror or error)
                log.warning("%s, retrying in 5 s", self.error)
            finally:
                if self.sock is not None:
                    try:
                        loop.remove_reader(self.sock.fileno())
                    except ValueError:
                        pass
                    self.sock.close()
                    self.sock = None
            if self.error:
                await asyncio.sleep(5)

    def on_readable(self):
        try:
            while True:
                frame = canbus.parse_frame(self.sock.recv(canbus.FRAME.size))
                if frame is not None:
                    self.handle(*frame)
        except BlockingIOError:
            pass
        except OSError as error:  # interface went down
            self.error = "%s: %s" % (self.config["interface"], error.strerror or error)
            self.reopen.set()

    def handle(self, can_id, data):
        self.frames += 1
        if self.config["monitor"]:
            entry = self.monitor.setdefault(can_id, [b"", 0, 0.0])
            entry[0], entry[1], entry[2] = data, entry[1] + 1, time.monotonic()
        if self.profile is None:
            return

        changed, actions, commands = self.profile.feed(can_id, data)
        self.pending.update(changed)
        for action, phase in actions:
            asyncio.create_task(self.api.safe(self.api.action(action, phase)))
        for command in commands:
            asyncio.create_task(self.run_command(command))

    async def run_command(self, command):
        if "action" in command:
            await self.api.safe(self.api.action(command["action"]))
        elif "method" in command:
            await self.api.safe(self.api.request(command["method"], **command.get("params", {})))

    # --- publishing -------------------------------------------------------------

    async def publish_loop(self):
        while True:
            await asyncio.sleep(PUBLISH_INTERVAL)
            if self.api.connected and self.pending:
                pending, self.pending = self.pending, {}
                for topic, fields in pending.items():
                    await self.api.safe(self.api.publish(topic, **fields))

    async def state_loop(self):
        while True:
            await asyncio.sleep(1)
            self.frames_per_second, self.frames = self.frames, 0
            if not self.api.connected:
                continue
            await self.publish_state()
            if self.config["monitor"]:
                now = time.monotonic()
                frames = [{"id": "0x%03X" % can_id, "data": data.hex(" ").upper(), "count": count,
                           "age": round(now - seen, 1)}
                          for can_id, (data, count, seen) in sorted(self.monitor.items())]
                await self.api.safe(self.api.publish("can.monitor", frames=frames))

    async def publish_state(self):
        await self.api.safe(self.api.publish(
            "can.state",
            interface=self.config["interface"],
            connected=self.sock is not None,
            error=self.error or self.profile_error,
            profile=self.config["profile"],
            profileName=self.profile.name if self.profile else "",
            profiles=list_profiles(),
            monitor=self.config["monitor"],
            framesPerSecond=self.frames_per_second,
        ))

    # --- commands from the plugin page --------------------------------------------

    async def on_command(self, topic, data):
        command, value = data.get("cmd"), data.get("value")
        if command == "interface" and value:
            self.config["interface"] = str(value)
            self.reopen.set()
        elif command == "profile" and value:
            self.config["profile"] = str(value)
            self.load_profile()
        elif command == "monitor":
            self.config["monitor"] = bool(value)
            self.monitor.clear()
        elif command == "reload":
            self.load_profile()
        else:
            log.warning("unknown command %s", data)
            return
        save_config(self.config)
        await self.publish_state()

    async def main(self):
        await asyncio.gather(self.api.run(self.publish_state), self.can_loop(), self.publish_loop(), self.state_loop())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(CanPlugin().main())
