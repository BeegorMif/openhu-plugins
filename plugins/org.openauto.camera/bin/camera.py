#!/usr/bin/env python3
"""Reverse camera: shows the camera overlay on camera.show/hide/toggle actions and in reverse gear.

Config (plugin data dir, editable on the plugin page), published as "camera.config":
    device        camera device id ("" = default camera)
    mirror        mirror the picture horizontally
    guides        draw parking guide lines
    autoReverse   show the camera while vehicle.gear.reverse is true (CAN plugin)
    display       "page" (default): camera page inside the shell, "overlay": full screen above everything;
                  with "page" OpenAuto returns to the previous page when the camera is hidden
Commands: bus.emit "camera.command" {cmd: "show"|"hide"|"toggle"|"set", key, value}
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from oa import PLUGIN_ID, OpenAuto, load_config, save_config, setup_logging  # noqa: E402

log = logging.getLogger("camera")

DEFAULTS = {"device": "", "mirror": False, "guides": True, "autoReverse": True, "display": "page"}
PAGE = "plugin:" + PLUGIN_ID


class CameraPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.oa = OpenAuto()
        self.visible = False
        self.reverse = None
        self.page = "home"           # shell page, to return to after showing the camera page
        self.previous_page = "home"
        self.oa.on("ui.page", self.on_page)
        self.oa.on("input.action", self.on_action)
        self.oa.on("vehicle.gear", self.on_gear)
        self.oa.on("camera.command", self.on_command)

    async def show(self, visible):
        changed = visible != self.visible
        if changed:
            log.info("camera %s", "on" if visible else "off")
        self.visible = visible

        if self.config["display"] == "page":
            await self.oa.safe(self.oa.request("ui.overlay.hide", id=PLUGIN_ID))
            if visible and changed:
                # already on the camera page (opened by hand): stay there when hidden again
                self.previous_page = self.page
                if self.page != PAGE:
                    await self.oa.safe(self.oa.request("ui.navigate", page=PAGE))
            elif not visible and changed and self.page == PAGE and self.previous_page != PAGE:
                await self.oa.safe(self.oa.request("ui.navigate", page=self.previous_page))
        else:
            await self.oa.safe(self.oa.request("ui.overlay.show" if visible else "ui.overlay.hide", id=PLUGIN_ID))

    async def on_page(self, topic, data):
        self.page = data.get("page", "home")
        # left the camera page by hand: camera counts as hidden
        if self.config["display"] == "page" and self.page != PAGE:
            self.visible = False

    async def on_action(self, topic, data):
        if data.get("phase") == "release":
            return
        action = data.get("action")
        if action == "camera.show":
            await self.show(True)
        elif action == "camera.hide":
            await self.show(False)
        elif action == "camera.toggle":
            await self.show(not self.visible)

    async def on_gear(self, topic, data):
        reverse = bool(data.get("reverse"))
        if self.config["autoReverse"] and reverse != self.reverse:
            await self.show(reverse)
        self.reverse = reverse

    async def on_command(self, topic, data):
        command = data.get("cmd")
        if command in ("show", "hide", "toggle"):
            await self.show(command == "show" or (command == "toggle" and not self.visible))
        elif command == "set" and data.get("key") in DEFAULTS:
            self.config[data["key"]] = data.get("value")
            save_config(self.config)
            await self.publish_config()
            if data["key"] == "display" and self.visible:
                await self.show(True)
        else:
            log.warning("unknown command %s", data)

    async def publish_config(self):
        await self.oa.safe(self.oa.publish("camera.config", **self.config))

    async def on_connect(self):
        await self.publish_config()
        # Overlay state after a restart of OpenAuto or this process
        if self.config["display"] != "page":
            await self.show(self.visible)


if __name__ == "__main__":
    setup_logging()
    plugin = CameraPlugin()
    asyncio.run(plugin.oa.run(plugin.on_connect))
