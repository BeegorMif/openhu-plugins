#!/usr/bin/env python3
"""Vehicle plugin: the CAN plugin's can.* values -> the vehicle.* topics (openhu-plugins#29).

Only plugins that declare it in their manifest ("androidAuto") feed Android Auto (openhu#123). The CAN plugin only
decodes; this plugin declares the sensors and passes the values on 1:1 (can.speed -> vehicle.speed, same fields,
the CAN profile uses the field names of the vehicle.* topics). Other can.* values stay with the CAN plugin.

The values become {"available": false} when the CAN plugin reports its bus as gone (can.state connected: false) or
stops reporting (no can.state for STATE_TIMEOUT seconds, e.g. the plugin ended).

Car controls for Android Auto's climate rail (openhu#121, OpenHU docs/api.md "Car controls"): vehicle.controls comes
from the CAN plugin's can.controls (its profile), the phone's changes (vehicle.control.set) go to the CAN plugin as
can.control.set and its can.control.result back as vehicle.control.result. Without a car: config "demoControls"
(bus.emit "vehicle.command" {cmd: "demoControls", value: true}) publishes a demo climate that takes every change.
"""

import asyncio
import logging
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from openhu import OpenHU, load_config, save_config, setup_logging  # noqa: E402

log = logging.getLogger("vehicle")

# the vehicle.* topics of OpenHU (docs/api.md) that come from the CAN plugin; lights is not an Android Auto sensor
TOPICS = ("speed", "parkingBrake", "gear", "fuel", "odometer", "engine", "climate", "compass", "drivingStatus",
          "info", "lights")
STATE_TIMEOUT = 5
DEFAULTS = {"demoControls": False}

# default area per control (OpenHU docs/api.md)
GLOBAL_CONTROLS = ("steeringWheelHeating", "ignition")
WINDOW_CONTROLS = ("defrost",)


def demo_controls():
    def control(name, area, value, **limits):
        entry = {"name": name, "value": value, **limits}
        if area:
            entry["area"] = area
        return entry
    return {"driverSide": "left", "units": "celsius", "properties": [
        control("temperature", "driver", 21.5, min=16, max=28, step=0.5),
        control("temperature", "passenger", 22.0, min=16, max=28, step=0.5),
        control("seatHeating", "driver", 0, min=0, max=3),
        control("seatHeating", "passenger", 0, min=0, max=3),
        control("steeringWheelHeating", None, 0, min=0, max=3),
        control("ac", "front", True),
        control("fanSpeed", "front", 3, min=0, max=7),
        control("recirculation", "front", False),
        control("defrost", "windshield", False),
        control("ignition", None, True),
    ]}


def area_of(entry):
    if entry.get("area"):
        return entry["area"]
    name = entry.get("name")
    return "global" if name in GLOBAL_CONTROLS else "windshield" if name in WINDOW_CONTROLS else "front"


def apply_set(controls, request):
    """A change of the phone on vehicle.controls data (the demo): True if the control exists"""
    for entry in controls.get("properties", []):
        if entry.get("name") == request.get("name") and area_of(entry) == request.get("area"):
            entry["value"] = request.get("value")
            return True
    return False


def vehicle_topic(can_topic):
    """can.speed -> vehicle.speed; None for the CAN plugin's other topics."""
    if not can_topic.startswith("can."):
        return None
    name = can_topic[4:]
    return "vehicle." + name if name in TOPICS else None


class Forwarder:
    """What to publish for the CAN plugin's topics (no I/O, see tests/test_vehicle.py)."""

    def __init__(self):
        self.forwarded = set()   # vehicle.* topics that got a value
        self.unavailable = True  # set until the CAN plugin reports
        self.last_state = None   # time of the last can.state

    def on_can(self, topic, data, now):
        """[(topic, data)] to publish"""
        if topic == "can.state":
            self.last_state = now
            if not data.get("connected"):
                return self.mark_unavailable()
            return []
        target = vehicle_topic(topic)
        if target is None:
            return []
        self.unavailable = False
        self.forwarded.add(target)
        return [(target, dict(data))]

    def check(self, now):
        """[(topic, data)] when the CAN plugin stopped reporting"""
        if self.last_state is not None and now - self.last_state > STATE_TIMEOUT:
            return self.mark_unavailable()
        return []

    def mark_unavailable(self):
        if self.unavailable:
            return []
        self.unavailable = True
        return [(topic, {"available": False}) for topic in sorted(self.forwarded)]


class VehiclePlugin:
    def __init__(self):
        self.api = OpenHU()
        self.config = load_config(DEFAULTS)
        self.forwarder = Forwarder()
        self.demo = demo_controls()
        self.can_controls = None  # last can.controls
        self.api.on("can.*", self.on_can)
        self.api.on("vehicle.control.set", self.on_control_set)
        self.api.on("vehicle.command", self.on_command)

    async def publish(self, messages):
        for topic, data in messages:
            await self.api.safe(self.api.publish(topic, **data))

    async def on_can(self, topic, data):
        if topic == "can.controls":
            self.can_controls = data
            if not self.config["demoControls"]:
                await self.api.safe(self.api.publish("vehicle.controls", **data))
            return
        if topic == "can.control.result":
            await self.api.safe(self.api.emit("vehicle.control.result", **data))
            return
        await self.publish(self.forwarder.on_can(topic, data, time.monotonic()))

    async def on_control_set(self, topic, data):
        if not self.config["demoControls"]:
            await self.api.safe(self.api.emit("can.control.set", **data))
            return
        ok = apply_set(self.demo, data)
        log.info("demo %s %s = %s", data.get("name"), data.get("area"), data.get("value"))
        if ok:
            await self.api.safe(self.api.publish("vehicle.controls", **self.demo))
        await self.api.safe(self.api.emit("vehicle.control.result", requestId=data.get("requestId"), ok=ok,
                                          **({} if ok else {"error": "unknown control"})))

    async def on_command(self, topic, data):
        if data.get("cmd") == "demoControls":
            self.config["demoControls"] = bool(data.get("value"))
            save_config(self.config)
            await self.publish_controls()

    async def publish_controls(self):
        """the demo, or the CAN plugin's controls (none before it publishes them); applies at the next connection"""
        if self.config["demoControls"]:
            await self.api.safe(self.api.publish("vehicle.controls", **self.demo))
        else:
            await self.api.safe(self.api.publish("vehicle.controls", **(self.can_controls or {"properties": []})))

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            if self.api.connected:
                await self.publish(self.forwarder.check(time.monotonic()))

    async def main(self):
        await asyncio.gather(self.api.run(self.publish_controls), self.watch())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(VehiclePlugin().main())
