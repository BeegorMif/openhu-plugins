#!/usr/bin/env python3
"""Set monitor brightness from a raw CAN dimmer byte; status bar controls a black page."""

import asyncio
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from openhu import PLUGIN_ID, OpenHU, load_config, save_config, setup_logging  # noqa: E402

DEFAULTS = {"topic": "can.display", "field": "dimByte", "display": "", "enabled": True,
            "extraDim": False}


class DisplayPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.api = OpenHU()
        self.last_signal = None
        self.error = ""
        self.api.on("can.*", self.on_can)
        self.api.on("display.command", self.on_command)

    def display_args(self):
        value = str(self.config.get("display", "")).strip()
        if not value:
            return []
        if not value.isdigit():
            raise ValueError("Display must be a numeric ddcutil display number")
        return ["--display", value]

    async def ddc(self, *args):
        command = ["ddcutil", *self.display_args(), *map(str, args)]
        try:
            result = await asyncio.wait_for(asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE), timeout=12)
        except FileNotFoundError:
            raise RuntimeError("ddcutil is not installed")
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=12)
        if result.returncode:
            detail = (stderr or stdout).decode(errors="replace").strip()
            raise RuntimeError(detail or "ddcutil exited with status %d" % result.returncode)
        return stdout.decode(errors="replace")

    async def publish(self):
        await self.api.publish("display.state", topic=self.config["topic"], field=self.config["field"],
                               enabled=self.config["enabled"], display=self.config["display"],
                               lastSignal=self.last_signal, extraDim=self.config["extraDim"], error=self.error)
        await self.api.publish("ui.extraDim", enabled=self.config["extraDim"], source=PLUGIN_ID)

    async def set_brightness(self, value):
        value = max(0, min(100, round(float(value))))
        if self.last_signal == value:
            return
        await self.ddc("setvcp", "10", str(value))
        self.last_signal = value
        self.error = ""
        await self.publish()

    async def on_can(self, topic, data):
        if not self.config.get("enabled") or topic != self.config.get("topic"):
            return
        value = data.get(self.config.get("field")) if isinstance(data, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        try:
            dim_byte = max(0, min(255, value))
            brightness = round((dim_byte / 255) * 100)
            await self.set_brightness(brightness)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.error = str(error)
            await self.publish()

    async def on_command(self, topic, data):
        command = data.get("cmd")
        try:
            if command == "configure":
                can_topic = str(data.get("topic", "")).strip()
                field = str(data.get("field", "")).strip()
                display = str(data.get("display", "")).strip()
                if not re.fullmatch(r"can\.[A-Za-z0-9_.-]+", can_topic):
                    raise ValueError("Topic must be a CAN topic, for example can.display")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", field):
                    raise ValueError("Signal field is required")
                if display and not display.isdigit():
                    raise ValueError("Display must be a numeric ddcutil display number")
                self.config.update(topic=can_topic, field=field, display=display,
                                   enabled=bool(data.get("enabled", True)))
                save_config(self.config)
                current = await self.api.request("bus.get", topic=can_topic)
                await self.on_can(can_topic, current)
            elif command == "extraDim":
                self.config["extraDim"] = bool(data.get("enabled", False))
                save_config(self.config)
            elif command == "manual":
                await self.set_brightness(data.get("value", 0))
            else:
                return
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.error = str(error)
        await self.publish()

    async def run(self):
        await self.api.run(self.on_connect)

    async def on_connect(self):
        """Apply the current CAN value too, if it was published before this plugin connected."""
        try:
            await self.publish()
            data = await self.api.request("bus.get", topic=self.config["topic"])
            await self.on_can(self.config["topic"], data)
        except Exception as error:
            self.error = str(error)
            await self.publish()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(DisplayPlugin().run())
