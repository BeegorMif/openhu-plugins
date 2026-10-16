#!/usr/bin/env python3
"""Simulated drive for testing the logger without a car: publishes vehicle.* like the CAN plugin would (speed,
engine, gear, temperatures), for development only.

    python3 tools/fake-drive.py [--hz 10] [--minutes 3] [--stop 0]

On the head unit (plugin folder ~/.openhu/plugins/org.openhu.logger):
    PYTHONPATH=lib python3 tools/fake-drive.py
From another computer: OPENHU_API_URL=ws://<head unit>:5520 OPENHU_API_TOKEN=<token> PYTHONPATH=<repo>/common ...
The drive: engine on, accelerate and cruise for --minutes, brake to 0, then stand still with the engine running for
--stop minutes (with the default 10 minutes standing still, a trip ends), engine off.
"""

import argparse
import asyncio
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from openhu import OpenHU  # noqa: E402


async def drive(api, hz, minutes, stop):
    rng = random.Random()
    # units, like a CAN profile could provide them (the logger keeps them in its signal table)
    await api.publish("signals.info", source="fake-drive", signals={
        "vehicle.speed.kmh": {"unit": "km/h"},
        "vehicle.engine.rpm": {"unit": "rpm"},
        "vehicle.engine.throttle": {"unit": "%"},
        "vehicle.climate.outsideTemp": {"unit": "°C"},
    })
    await api.publish("vehicle.engine", running=True, rpm=800)
    await api.publish("vehicle.gear", gear="drive", reverse=False)
    dt = 1.0 / hz
    speed, t = 0.0, 0.0
    total = minutes * 60
    while t < total:
        target = 0 if t > total - 15 else 50 + 30 * math.sin(t / 40)
        speed = max(0.0, speed + max(-8.0, min(5.0, target - speed)) * dt)
        rpm = 800 + speed * 30 + rng.gauss(0, 10)
        await api.publish("vehicle.speed", kmh=round(speed + rng.gauss(0, 0.05), 2))
        # pedal: 0-100 %, more while accelerating, ~15-25 % to hold the speed, 0 while braking or coasting
        throttle = 0.0 if target < speed - 0.5 else min(100.0, 15.0 + speed * 0.12 + max(0.0, target - speed) * 6)
        await api.publish("vehicle.engine", running=True, rpm=round(rpm),
                          throttle=round(max(0.0, throttle + rng.gauss(0, 0.5)), 1))
        await api.publish("vehicle.climate", outsideTemp=round(18 + rng.gauss(0, 0.2), 1))
        await asyncio.sleep(dt)
        t += dt
    await api.publish("vehicle.speed", kmh=0)
    await api.publish("vehicle.gear", gear="park", reverse=False)
    print("stopped, standing for %s min" % stop, flush=True)
    await asyncio.sleep(stop * 60)
    await api.publish("vehicle.engine", running=False, rpm=0, throttle=0)
    print("engine off", flush=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hz", type=float, default=10)
    parser.add_argument("--minutes", type=float, default=3)
    parser.add_argument("--stop", type=float, default=0)
    args = parser.parse_args()
    api = OpenHU()
    runner = asyncio.create_task(api.run())
    while not api.connected:
        await asyncio.sleep(0.1)
    await drive(api, args.hz, args.minutes, args.stop)
    runner.cancel()


if __name__ == "__main__":
    asyncio.run(main())
