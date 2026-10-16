"""Storage per hour with synthetic CAN data: 20 signals logged on every update at 10 Hz and 100 Hz, written in
30 s batches like the process does. Prints the numbers (README.md, "Storage") and checks the target of the issue
(1-2 MB per hour for 20 fields at 10 Hz).

    python3 -m unittest -v tests.test_storage_rate        # in the plugin folder
"""

import copy
import math
import os
import random
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from logstore import Store  # noqa: E402
from recorder import Recorder  # noqa: E402

CONFIG = {
    "enabled": True,
    "groups": {"vehicle": True, "openhu": True, "health": True, "position": False},
    "interval": 5, "rates": {"vehicle.*": "update"}, "stopMinutes": 10, "engineOffSeconds": 60,
    "recording": {"keys": [], "triggers": [], "preSeconds": 0, "postSeconds": 0, "maxSeconds": 600, "limitMB": 256},
}


def quantize(value, scale, offset=0.0):
    """Like a CAN signal: a raw integer times the scale plus the offset."""
    return round((value - offset) / scale) * scale + offset


class Car:
    """A drive in town and on the road: speed follows targets, the rest depends on it, with sensor noise of a few
    raw steps. 20 signals with the scales typical for CAN (0.01 km/h, 100/255 % for pedals, 0.0001 lambda, ...)."""

    def __init__(self, seed=1):
        self.random = random.Random(seed)
        self.speed = 0.0
        self.target = 50.0
        self.coolant = 20.0
        self.fuel = 40.0
        self.steering = 0.0

    def step(self, dt):
        r = self.random
        if r.random() < dt / 20:  # a new target speed every 20 s on average
            self.target = r.choice([0, 30, 50, 50, 70, 100, 130])
        accel = max(-3.0, min(2.0, (self.target - self.speed) / 5))
        self.speed = max(0.0, self.speed + accel * dt * 3.6)
        gear = 0 if self.speed < 1 else min(6, 1 + int(self.speed / 22))
        rpm = 800 if gear == 0 else 800 + self.speed / gear * 95
        throttle = max(0.0, min(100.0, 15 + accel * 25 + r.gauss(0, 1.5))) if accel > -0.5 else 0.0
        self.coolant = min(90.0, self.coolant + dt * 0.05)
        self.fuel -= dt * 0.0002
        self.steering = max(-500.0, min(500.0, self.steering + r.gauss(0, 20) * dt))
        load = throttle * 0.8 + 10
        maf = rpm * load / 4000
        noise = r.gauss
        return {
            "vehicle.speed.kmh": quantize(self.speed + noise(0, 0.05), 0.01),
            "vehicle.engine.rpm": quantize(rpm + noise(0, 8), 0.25),
            "vehicle.engine.throttle": quantize(throttle, 100 / 255),
            "vehicle.engine.load": quantize(load + noise(0, 0.5), 100 / 255),
            "vehicle.engine.maf": quantize(maf + noise(0, 0.05), 0.01),
            "vehicle.engine.lambda": quantize(1.0 + noise(0, 0.01), 0.0001),
            "vehicle.engine.injection": quantize(load * 0.4 + noise(0, 0.1), 0.01),
            "vehicle.engine.boost": quantize(100 + load * 0.8 + noise(0, 0.5), 1),
            "vehicle.engine.coolant": quantize(self.coolant, 1, -40),
            "vehicle.engine.oil": quantize(self.coolant * 1.05, 1, -40),
            "vehicle.engine.intake": quantize(25 + noise(0, 0.3), 1, -40),
            "vehicle.electric.voltage": quantize(14.1 + noise(0, 0.05), 0.1),
            "vehicle.fuel.liters": quantize(self.fuel, 0.5),
            "vehicle.steering.angle": quantize(self.steering, 0.1),
            "vehicle.brake.pressure": quantize(max(0.0, -accel * 20 + noise(0, 0.2)), 0.1),
            "vehicle.wheels.fl": quantize(self.speed + noise(0, 0.1), 0.01),
            "vehicle.wheels.fr": quantize(self.speed + noise(0, 0.1), 0.01),
            "vehicle.wheels.rl": quantize(self.speed + noise(0, 0.1), 0.01),
            "vehicle.wheels.rr": quantize(self.speed + noise(0, 0.1), 0.01),
            "vehicle.gear.gear": gear,
        }


def measure(hz, seconds, flush_seconds=30, rates=None):
    """Bytes per hour of the database for 20 signals updated at hz, written at rates (default: on every update)."""
    with tempfile.TemporaryDirectory() as directory:
        store = Store(os.path.join(directory, "logger.db"))
        config = copy.deepcopy(CONFIG)
        if rates is not None:
            config["rates"] = rates
        recorder = Recorder(store, config)
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        empty = store.used_bytes()
        car = Car()
        step = 1000 // hz
        start = 1_700_000_000_000
        began = time.process_time()
        values = 0
        for n in range(seconds * hz):
            t = start + n * step
            topics = {}
            for key, value in car.step(1 / hz).items():
                topic, field = key.rsplit(".", 1)
                topics.setdefault(topic, {})[field] = value
            for topic, data in topics.items():
                recorder.on_topic(topic, data, t)
                values += len(data)
            if n % hz == 0:
                recorder.tick(t)
            if n % (flush_seconds * hz) == 0:
                recorder.flush()
        recorder.flush()
        cpu = time.process_time() - began
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        used = store.used_bytes() - empty
        store.close()
    return {"bytesPerHour": used * 3600 / seconds, "bytesPerValue": used / values, "values": values,
            "cpuShare": cpu / seconds}


class StorageRateTest(unittest.TestCase):
    def report(self, what, result):
        gb_hours = 1024 ** 3 / result["bytesPerHour"]
        print("\n  20 signals %s: %.2f MB/h, %.2f bytes/value, 1 GB lasts %.0f h; "
              "CPU here %.1f %% of real time"
              % (what, result["bytesPerHour"] / 1024 ** 2, result["bytesPerValue"], gb_hours, result["cpuShare"] * 100),
              file=sys.stderr)

    def test_10_hz(self):
        result = measure(10, 600)
        self.report("at 10 Hz, every update", result)
        self.assertLess(result["bytesPerHour"], 2 * 1024 ** 2)

    def test_100_hz(self):
        result = measure(100, 120)
        self.report("at 100 Hz, every update", result)
        self.assertLess(result["bytesPerValue"], 3)

    def test_default_interval(self):
        result = measure(10, 3600, rates={})
        self.report("updated at 10 Hz, logged every 5 s (default)", result)
        self.assertLess(result["bytesPerHour"], 0.5 * 1024 ** 2)


if __name__ == "__main__":
    unittest.main()
