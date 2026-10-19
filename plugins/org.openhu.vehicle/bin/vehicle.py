#!/usr/bin/env python3
"""Vehicle plugin: the CAN plugin's can.* values -> the vehicle.* topics (openhu-plugins#29).

Only plugins that declare it in their manifest ("androidAuto") feed Android Auto (openhu#123). The CAN plugin only
decodes; this plugin declares the sensors and passes the values on 1:1 (can.speed -> vehicle.speed, same fields,
the CAN profile uses the field names of the vehicle.* topics). Other can.* values stay with the CAN plugin.

The values become {"available": false} when the CAN plugin reports its bus as gone (can.state connected: false) or
stops reporting (no can.state for STATE_TIMEOUT seconds, e.g. the plugin ended).
"""

import asyncio
import logging
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from openhu import OpenHU, setup_logging  # noqa: E402

log = logging.getLogger("vehicle")

# the vehicle.* topics of OpenHU (docs/api.md) that come from the CAN plugin; lights is not an Android Auto sensor
TOPICS = ("speed", "parkingBrake", "gear", "fuel", "odometer", "engine", "climate", "compass", "drivingStatus",
          "info", "lights")
STATE_TIMEOUT = 5


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
        self.forwarder = Forwarder()
        self.api.on("can.*", self.on_can)

    async def publish(self, messages):
        for topic, data in messages:
            await self.api.safe(self.api.publish(topic, **data))

    async def on_can(self, topic, data):
        await self.publish(self.forwarder.on_can(topic, data, time.monotonic()))

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            if self.api.connected:
                await self.publish(self.forwarder.check(time.monotonic()))

    async def main(self):
        await asyncio.gather(self.api.run(), self.watch())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(VehiclePlugin().main())
