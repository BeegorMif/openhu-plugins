"""Recorder: groups and privacy, rates (sample-and-hold, "update"), events, trips into the store, recordings."""

import copy
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from logstore import Store  # noqa: E402
from recorder import Recorder, best_match, flatten  # noqa: E402

S = 1000
MIN = 60 * S
CONFIG = {
    "enabled": True,
    "groups": {"vehicle": True, "openhu": True, "health": True, "position": False},
    "interval": 5, "rates": {}, "stopMinutes": 10, "engineOffSeconds": 60,
    "recording": {"keys": ["vehicle.*"], "triggers": [], "preSeconds": 5, "postSeconds": 10, "maxSeconds": 600,
                  "limitMB": 256},
}


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "logger.db"))
        self.reader = self.store.reader()
        self.config = copy.deepcopy(CONFIG)
        self.recorder = Recorder(self.store, self.config, {"loggerVersion": "1.0.0"})

    def tearDown(self):
        self.reader.close()
        self.store.close()
        self.dir.cleanup()

    def raw(self, key, recording=None):
        self.recorder.flush()
        result = self.reader.samples(0, 10 ** 13, [key], points=0, limit=50000, recording=recording)["series"]
        return list(zip(result[key]["t"], result[key]["v"])) if key in result else []

    def test_flatten(self):
        self.assertEqual(flatten("vehicle.climate", {"inside": 21.5, "ac": True, "mode": "auto", "zones": {"left": 20},
                                                     "list": [1], "nan": float("nan"), "none": None}),
                         [("vehicle.climate.inside", 21.5), ("vehicle.climate.ac", True),
                          ("vehicle.climate.mode", "auto"), ("vehicle.climate.zones.left", 20)])
        # only the call state, no numbers or names
        self.assertEqual(flatten("phone.status", {"callState": "in_call", "signal": 3,
                                                  "calls": [{"number": "+49123", "name": "Bob"}]}),
                         [("phone.status.callState", "in_call")])

    def test_best_match(self):
        patterns = ["*", "vehicle.*", "vehicle.engine.*", "vehicle.engine.rpm"]
        self.assertEqual(best_match(patterns, "vehicle.engine.rpm"), "vehicle.engine.rpm")
        self.assertEqual(best_match(patterns, "vehicle.engine.load"), "vehicle.engine.*")
        self.assertEqual(best_match(patterns, "vehicle.speed.kmh"), "vehicle.*")
        self.assertEqual(best_match(patterns, "hu.load"), "*")
        self.assertIsNone(best_match(["vehicle.*"], "hu.load"))

    def test_sample_and_hold_at_interval(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 10}, 0)
        r.on_topic("vehicle.speed", {"kmh": 20}, 1 * S)  # replaced before the tick
        r.tick(5 * S)
        r.tick(10 * S)  # unchanged: nothing
        r.on_topic("vehicle.speed", {"kmh": 30}, 11 * S)
        r.tick(12 * S)  # not due yet
        r.tick(15 * S)
        # one sample per period at most, with the time the value arrived
        self.assertEqual(self.raw("vehicle.speed.kmh"), [(1 * S, 20), (11 * S, 30)])

    def test_rates_per_key(self):
        self.config["rates"] = {"vehicle.engine.*": "update", "vehicle.speed.kmh": 0.1}
        r = self.recorder
        r.apply_config()
        self.assertEqual(r.fastest_rate(), 0.1)
        for i in range(10):
            r.on_topic("vehicle.engine", {"rpm": 800}, i * 10)  # the same value 10 times: all written
            r.on_topic("vehicle.speed", {"kmh": i}, i * 10)
            r.tick(i * 100)
        self.assertEqual(len(self.raw("vehicle.engine.rpm")), 10)
        self.assertEqual(len(self.raw("vehicle.speed.kmh")), 10)
        self.config["rates"] = {}
        r.apply_config()
        self.assertEqual(r.fastest_rate(), 5)

    def test_booleans_and_texts(self):
        r = self.recorder
        r.on_topic("vehicle.gear", {"reverse": True, "gear": "reverse"}, 1 * S)
        r.on_topic("vehicle.gear", {"reverse": True, "gear": "reverse"}, 2 * S)  # unchanged
        r.on_topic("vehicle.gear", {"reverse": False, "gear": "drive"}, 3 * S)
        self.assertEqual(self.raw("vehicle.gear.reverse"), [(1 * S, 1), (3 * S, 0)])
        events = self.reader.events(0, 10 * S, "vehicle.gear")["events"]
        self.assertEqual([(e["t"], e["data"]) for e in events],
                         [(1 * S, {"reverse": True, "gear": "reverse"}), (3 * S, {"reverse": False, "gear": "drive"})])

    def test_groups_and_switch(self):
        r = self.recorder
        r.on_topic("vehicle.position", {"lat": 52.1, "lon": 9.7}, 0)  # off by default
        r.on_topic("media.metadata", {"title": "Song"}, 0)  # never logged
        self.config["groups"]["health"] = False
        r.tick(5 * S, {"hu.cpuTemp": 50})
        self.config["enabled"] = False
        r.on_topic("vehicle.speed", {"kmh": 10}, 6 * S)
        r.tick(10 * S)
        r.flush()
        self.assertEqual(self.reader.keys()["keys"], [])
        self.assertTrue(r.vehicle_data)
        self.config["enabled"] = True
        self.config["groups"]["health"] = True
        r.tick(15 * S, {"hu.cpuTemp": 50})
        self.assertEqual(self.raw("hu.cpuTemp"), [(15 * S, 50)])

    def test_trip_written_and_announced(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 50}, 0)
        self.assertEqual(r.announcements[0][0], "logger.trip")
        self.assertEqual(r.announcements[0][1]["event"], "start")
        trip_id = r.trip["id"]
        self.assertIsNotNone(trip_id)
        for t in range(5 * S, 5 * MIN, 5 * S):
            r.tick(t)
        r.flush()
        self.assertTrue(self.reader.trip(trip_id)["trip"]["open"])
        self.assertEqual(self.reader.trip(trip_id)["trip"]["loggerVersion"], "1.0.0")
        r.disable(5 * MIN)
        trip = self.reader.trip(trip_id)["trip"]
        self.assertEqual((trip["open"], trip["endReason"]), (False, "off"))
        self.assertAlmostEqual(trip["distance"], 50 * 5 / 60, places=2)

    def test_open_trip_after_power_cut(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 50}, 0)
        r.tick(MIN)
        r.flush()  # then the power goes
        restarted = Recorder(self.store, self.config)
        restarted.restore(3 * 60 * MIN)
        trip = self.reader.trips()["trips"][0]
        self.assertEqual((trip["open"], trip["endReason"], trip["end"]), (False, "power", MIN))

    def test_manual_recording(self):
        r = self.recorder
        recording = r.start_recording(0, "manual", "test", seconds=2)
        for i in range(100):  # 100 Hz for 1 s
            r.on_topic("vehicle.engine", {"rpm": 800 + i}, i * 10)
        r.on_topic("hu.load", {"x": 1}, 500)  # not a recorded key
        r.tick(1 * S)
        self.assertIsNotNone(r.recording)
        r.tick(2 * S)
        self.assertIsNone(r.recording)
        self.assertEqual(len(self.raw("vehicle.engine.rpm", recording["id"])), 100)
        saved = self.reader.recording(recording["id"])
        self.assertEqual((saved["reason"], saved["label"], saved["open"]), ("manual", "test", False))
        self.assertEqual([data["event"] for topic, data in r.announcements if topic == "logger.recording"],
                         ["start", "end"])
        # the log itself has the engine at its own rate only
        self.assertLessEqual(len(self.raw("vehicle.engine.rpm")), 1)

    def test_triggered_recording_with_pre_and_post(self):
        self.config["recording"]["triggers"] = [{"key": "vehicle.engine.rpm", "above": 3000}]
        r = self.recorder
        t = 0
        for rpm in [1000] * 1000 + [3500] * 200 + [2000] * 2000:  # 10 Hz: 100 s low, 20 s high, 200 s low
            r.on_topic("vehicle.engine", {"rpm": rpm}, t)
            if t % 1000 == 0:
                r.tick(t)
            t += 100
        recordings = self.reader.recordings()["recordings"]
        self.assertEqual(len(recordings), 1)
        recording = recordings[0]
        self.assertEqual((recording["reason"], recording["label"]), ("trigger", "vehicle.engine.rpm above 3000"))
        samples = self.raw("vehicle.engine.rpm", recording["id"])
        # 5 s before the trigger, the 20 s above it, about 10 s after
        self.assertEqual(samples[0][0], 95 * S)
        self.assertEqual(samples[50][1], 3500)
        self.assertAlmostEqual(len(samples), 50 + 200 + 100, delta=12)
        self.assertFalse(recording["open"])

    def test_recording_quota_stops_it(self):
        self.config["recording"]["limitMB"] = 0.001  # about 1 kB
        r = self.recorder
        r.start_recording(0, "manual")
        for i in range(5000):
            r.on_topic("vehicle.engine", {"rpm": (i * 7919) % 6007}, i * 10)
            if i % 100 == 0:
                r.tick(i * 10)
                r.flush()
        self.assertIsNone(r.recording)
        self.assertEqual(self.reader.recordings()["recordings"][0]["open"], False)

    def test_failed_write_keeps_rows(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 5}, 0)
        r.tick(5 * S)
        real = self.store.write

        def full(*args, **kwargs):
            raise OSError("disk full")
        self.store.write = full
        with self.assertRaises(OSError):
            r.flush()
        self.assertEqual(r.error, "disk full")
        self.store.write = real
        r.flush()
        self.assertEqual(r.error, "")
        self.assertEqual(self.raw("vehicle.speed.kmh"), [(0, 5)])


if __name__ == "__main__":
    unittest.main()
