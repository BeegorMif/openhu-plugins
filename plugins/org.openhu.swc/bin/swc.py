#!/usr/bin/env python3
"""Steering wheel controls: keys of input devices -> OpenHU actions.

Config (plugin data dir, editable on the plugin page):
    devices   names of the input devices to use (default none, so the PC keyboard is not taken over)
    grab      use the devices exclusively
    keys      {"<code>": "<action>"} overrides the defaults, "" disables a key
Commands: bus.emit "swc.command" {cmd: "devices"|"grab"|"learn"|"map"|"reset", value, code, action}
In learn mode every key press is sent as "swc.key" {code, name, device}.
"""

import asyncio
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

import inputdev  # noqa: E402
from openhu import OpenHU, load_config, save_config, setup_logging  # noqa: E402

log = logging.getLogger("swc")

DEFAULTS = {"devices": [], "grab": True, "keys": {}}


class SwcPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.api = OpenHU()
        self.open = {}  # event -> InputDevice
        self.learn = False
        self.error = ""
        self.api.on("swc.command", self.on_command)

    def keymap(self):
        keys = {str(code): action for code, action in inputdev.DEFAULT_KEYS.items()}
        keys.update(self.config["keys"])
        return {int(code): action for code, action in keys.items() if action}

    # --- devices ----------------------------------------------------------------

    def sync_devices(self):
        """Open selected devices that appeared, close the ones that are gone or deselected."""
        loop = asyncio.get_running_loop()
        wanted = {device["event"]: device["name"] for device in inputdev.list_devices()
                  if device["name"] in self.config["devices"]}

        for event in list(self.open):
            if event not in wanted:
                loop.remove_reader(self.open[event].fd)
                self.open.pop(event).close()
                log.info("closed %s", event)

        for event, name in wanted.items():
            if event in self.open:
                continue
            try:
                device = inputdev.InputDevice(name, event, self.config["grab"])
            except OSError as error:
                self.error = "%s: %s" % (name, error.strerror or error)
                log.warning(self.error)
                continue
            self.open[event] = device
            loop.add_reader(device.fd, self.on_readable, device)
            self.error = ""
            log.info("using %s (%s)", name, event)

    def reopen_all(self):
        loop = asyncio.get_running_loop()
        for device in self.open.values():
            loop.remove_reader(device.fd)
            device.close()
        self.open.clear()
        self.sync_devices()

    def on_readable(self, device):
        try:
            keys = device.read_keys()
        except OSError:  # unplugged
            asyncio.get_running_loop().remove_reader(device.fd)
            self.open.pop(device.event, None)
            device.close()
            return

        keymap = self.keymap()
        for code, value in keys:
            if value == 2:  # auto repeat
                continue
            if self.learn and value == 1:
                asyncio.create_task(self.api.safe(self.api.emit(
                    "swc.key", code=code, name=inputdev.key_name(code), device=device.name)))
                continue
            action = keymap.get(code)
            if action and not self.learn:
                asyncio.create_task(self.api.safe(self.api.action(action, "press" if value == 1 else "release")))

    async def device_loop(self):
        while True:
            self.sync_devices()
            await asyncio.sleep(3)

    # --- state and commands --------------------------------------------------------

    async def publish_state(self):
        open_events = set(self.open)
        await self.api.safe(self.api.publish(
            "swc.state",
            devices=[dict(device, active=device["event"] in open_events) for device in inputdev.list_devices()],
            selected=self.config["devices"],
            grab=self.config["grab"],
            learn=self.learn,
            keys=[{"code": code, "name": inputdev.key_name(code), "action": action}
                  for code, action in sorted(self.keymap().items())],
            error=self.error,
        ))

    async def on_command(self, topic, data):
        command = data.get("cmd")
        if command == "devices":
            self.config["devices"] = [str(name) for name in data.get("value") or []]
            self.sync_devices()
        elif command == "grab":
            self.config["grab"] = bool(data.get("value"))
            self.reopen_all()
        elif command == "learn":
            self.learn = bool(data.get("value"))
        elif command == "map":
            self.config["keys"][str(int(data["code"]))] = data.get("action") or ""
        elif command == "reset":
            self.config["keys"] = {}
        else:
            log.warning("unknown command %s", data)
            return
        save_config(self.config)
        await self.publish_state()

    async def state_loop(self):
        while True:
            await asyncio.sleep(3)
            if self.api.connected:
                await self.publish_state()

    async def main(self):
        await asyncio.gather(self.api.run(self.publish_state), self.device_loop(), self.state_loop())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(SwcPlugin().main())
