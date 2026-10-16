"""Recorder: signal names and units, groups and privacy, rates (sample-and-hold, every change), texts and
booleans, trips into the store, recordings (windows, pre/post, quota)."""

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
    "interval": 5, "rates": {"vehicle.*": 5}, "stopMinutes": 10, "engineOffSeconds": 60,
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

    def raw(self, key, start=0, end=10 ** 13):
        self.recorder.flush()
        result = self.reader.samples(start, end, [key], points=0, limit=50000)["series"]
        return list(zip(result[key]["t"], result[key]["v"])) if key in result else []

    def signal(self, name):
        return {s["name"]: s for s in self.reader.signals()["signals"]}.get(name)

    def test_flatten(self):
        self.assertEqual(flatten("vehicle.climate", {"inside": 21.5, "ac": True, "mode": "auto", "zones": {"left": 20},
                                                     "list": [1], "nan": float("nan"), "none": None}),
                         [("vehicle.climate.inside", 21.5), ("vehicle.climate.ac", True),
                          ("vehicle.climate.mode", "auto"), ("vehicle.climate.zones.left", 20)])
        # OpenHU values get clear names; only the call state, no numbers or names
        self.assertEqual(flatten("phone.status", {"callState": "in_call", "signal": 3,
                                                  "calls": [{"number": "+49123", "name": "Bob"}]}),
                         [("phone.call_state", "in_call")])
        self.assertEqual(flatten("projection.state", {"connected": True}), [("androidauto.connected", True)])
        self.assertEqual(flatten("media.metadata", {"title": "Song"}), [])

    def test_best_match(self):
        patterns = ["*", "vehicle.*", "vehicle.engine.*", "vehicle.engine.rpm"]
        self.assertEqual(best_match(patterns, "vehicle.engine.rpm"), "vehicle.engine.rpm")
        self.assertEqual(best_match(patterns, "vehicle.engine.load"), "vehicle.engine.*")
        self.assertEqual(best_match(patterns, "vehicle.speed.kmh"), "vehicle.*")
        self.assertEqual(best_match(patterns, "headunit.cpu_load"), "*")
        self.assertIsNone(best_match(["vehicle.*"], "headunit.cpu_load"))

    def test_sample_and_hold_at_rate(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 10}, 0)
        r.on_topic("vehicle.speed", {"kmh": 20}, 1 * S)  # replaced before the tick
        r.tick(1 * S)
        r.tick(5 * S)
        r.tick(6 * S)  # not due again before 6 s, and unchanged anyway
        r.on_topic("vehicle.speed", {"kmh": 30}, 7 * S)
        r.tick(7 * S)  # not due yet
        r.tick(10 * S)  # unchanged values are not written again
        r.tick(11 * S)
        # one sample per period at most, with the time the value arrived
        self.assertEqual(self.raw("vehicle.speed.kmh"), [(1 * S, 20), (7 * S, 30)])

    def test_every_change(self):
        self.config["rates"] = {"vehicle.*": 5, "vehicle.engine.*": "update", "vehicle.speed.kmh": 0.1}
        r = self.recorder
        r.apply_config()
        self.assertEqual(r.fastest_rate(), 0.1)
        for i in range(10):
            r.on_topic("vehicle.engine", {"rpm": 800 + i % 2 * 10, "temp": 90}, i * 100)  # temp never changes
            r.on_topic("vehicle.speed", {"kmh": i}, i * 100)
            r.tick(i * 100)
        self.assertEqual(len(self.raw("vehicle.engine.rpm")), 10)
        self.assertEqual(len(self.raw("vehicle.engine.temp")), 1)  # only changes are written
        self.assertEqual(len(self.raw("vehicle.speed.kmh")), 10)
        self.config["rates"] = {}
        r.apply_config()
        self.assertEqual(r.fastest_rate(), 1.0)  # trips and the live state every second

    def test_booleans_and_texts(self):
        r = self.recorder
        r.on_topic("vehicle.gear", {"reverse": True, "gear": "reverse"}, 1 * S)
        r.on_topic("vehicle.gear", {"reverse": True, "gear": "reverse"}, 2 * S)  # unchanged
        r.on_topic("vehicle.gear", {"reverse": False, "gear": "drive"}, 3 * S)
        self.assertEqual(self.raw("vehicle.gear.reverse"), [(1 * S, 1), (3 * S, 0)])
        self.assertEqual(self.raw("vehicle.gear.gear"), [(1 * S, "reverse"), (3 * S, "drive")])
        events = self.reader.events(0, 10 * S, "vehicle.gear.*")["events"]
        self.assertEqual([(e["t"], e["value"]) for e in events], [(1 * S, "reverse"), (3 * S, "drive")])

    def test_units_and_sources(self):
        r = self.recorder
        r.on_topic("projection.state", {"connected": True}, 0)
        r.tick(S, {"headunit.cpu_temp_c": 50})
        r.on_topic("vehicle.speed", {"kmh": 10}, 2 * S)
        r.on_signals_info({"source": "org.openhu.can", "signals": {
            "vehicle.speed.kmh": {"unit": "km/h", "description": "ignored"},
            "vehicle.engine.rpm": {"unit": "rpm"}}})
        r.on_topic("vehicle.engine", {"rpm": 900}, 3 * S)
        r.tick(3 * S)
        r.flush()
        aa = self.signal("androidauto.connected")
        self.assertEqual((aa["unit"], aa["source"]), (None, "openhu:projection.state"))
        self.assertEqual(self.signal("headunit.cpu_temp_c")["unit"], "°C")
        self.assertNotIn("description", aa)
        for name, unit in (("vehicle.speed.kmh", "km/h"), ("vehicle.engine.rpm", "rpm")):
            signal = self.signal(name)
            self.assertEqual((signal["unit"], signal["source"]), (unit, "org.openhu.can"))
        # without info: the topic as the source
        r.on_topic("vehicle.climate", {"outside": 12}, 4 * S)
        r.tick(5 * S)
        r.flush()
        self.assertEqual(self.signal("vehicle.climate.outside")["source"], "vehicle.climate")
        self.assertIsNone(self.signal("vehicle.climate.outside")["unit"])

    def test_groups_and_switch(self):
        r = self.recorder
        r.on_topic("vehicle.position", {"lat": 52.1, "lon": 9.7}, 0)  # off by default
        r.on_topic("media.metadata", {"title": "Song"}, 0)  # never logged
        self.config["groups"]["health"] = False
        r.tick(5 * S, {"headunit.cpu_temp_c": 50})
        self.config["enabled"] = False
        r.on_topic("vehicle.speed", {"kmh": 10}, 6 * S)
        r.tick(10 * S)
        r.flush()
        self.assertEqual(self.store.sample_count(), 0)
        self.assertTrue(r.vehicle_data)
        self.config["enabled"] = True
        self.config["groups"]["health"] = True
        r.tick(15 * S, {"headunit.cpu_temp_c": 50})
        self.assertEqual(self.raw("headunit.cpu_temp_c"), [(15 * S, 50)])

    def test_trip_written_and_announced(self):
        r = self.recorder
        r.on_topic("vehicle.speed", {"kmh": 50}, 0)
        self.assertEqual(r.announcements[0][0], "logger.trip")
        self.assertEqual(r.announcements[0][1]["event"], "start")
        trip_id = r.trip["id"]
        self.assertIsNotNone(trip_id)
        for t in range(1 * S, 5 * MIN, 1 * S):
            r.tick(t)
        r.flush()
        self.assertTrue(self.reader.trip(trip_id)["trip"]["open"])
        self.assertEqual(self.reader.trip(trip_id)["trip"]["loggerVersion"], "1.0.0")
        r.disable(5 * MIN)
        trip = self.reader.trip(trip_id)["trip"]
        self.assertEqual((trip["open"], trip["endReason"]), (False, "off"))
        self.assertAlmostEqual(trip["distance"], 50 * 5 / 60, places=2)

    def test_android_auto_time_in_trip(self):
        r = self.recorder
        r.on_topic("projection.state", {"connected": True}, 0)
        r.on_topic("vehicle.speed", {"kmh": 50}, 0)
        for t in range(S, 4 * MIN, S):
            r.tick(t)
        r.on_topic("vehicle.speed", {"kmh": 0}, 4 * MIN)
        for t in range(4 * MIN, 16 * MIN, S):
            r.tick(t)
        trip = self.reader.trips()["trips"][0]
        self.assertEqual((trip["endReason"], trip["duration"]), ("standstill", 4 * MIN))
        self.assertLessEqual(trip["aaTime"], trip["duration"])

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
        r.tick(1 * S, {"headunit.cpu_load": 1.0})  # not a recorded signal
        self.assertIsNotNone(r.recording)
        r.tick(2 * S)
        self.assertIsNone(r.recording)
        self.assertEqual(len(self.raw("vehicle.engine.rpm")), 100)
        saved = self.reader.recording(recording["id"])
        self.assertEqual((saved["trigger"], saved["label"], saved["open"], saved["samples"]),
                         ("manual", "test", False, 101))  # rpm plus the load at 1 s
        self.assertEqual([data["event"] for topic, data in r.announcements if topic == "logger.recording"],
                         ["start", "end"])
        # after the window: the rate of the log again
        for i in range(10):
            r.on_topic("vehicle.engine", {"rpm": 1000 + i}, 3 * S + i * 10)
        r.tick(4 * S)
        self.assertEqual(len(self.raw("vehicle.engine.rpm", 3 * S)), 1)

    def test_triggered_recording_with_pre_and_post(self):
        self.config["recording"]["triggers"] = [{"key": "vehicle.engine.rpm", "above": 3000}]
        r = self.recorder
        t = 0
        for rpm in [1000, 1001] * 500 + [3500, 3501] * 100 + [2000, 2001] * 1000:  # 10 Hz: 100 s, 20 s, 200 s
            r.on_topic("vehicle.engine", {"rpm": rpm}, t)
            if t % 1000 == 0:
                r.tick(t)
            t += 100
        recordings = self.reader.recordings()["recordings"]
        self.assertEqual(len(recordings), 1)
        recording = recordings[0]
        self.assertEqual((recording["reason"], recording["trigger"]), ("trigger", "vehicle.engine.rpm above 3000"))
        samples = self.raw("vehicle.engine.rpm", recording["start"], recording["end"] + 1)
        # 5 s before the trigger, the 20 s above it, about 10 s after
        self.assertEqual(samples[0][0], 95 * S)
        self.assertEqual(samples[50][1], 3500)
        self.assertAlmostEqual(len(samples), 50 + 200 + 100, delta=12)
        self.assertFalse(recording["open"])
        # outside the window: one sample per 5 s
        self.assertLessEqual(len(self.raw("vehicle.engine.rpm", 0, 95 * S)), 20)

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
