"""SQLite store: schema, writing, queries (trips, signals, samples raw and downsampled, text events, recordings),
size limits, old and damaged files."""

import os
import random
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from logstore import MAX_POINTS, QueryError, Store, normalize  # noqa: E402

RANDOM = random.Random(1)  # noisy values
S = 1000
MIN = 60 * S
HOUR = 60 * MIN


def trip(trip_id, start, end, is_open=False, **summary):
    return dict({"id": trip_id, "start": start, "end": end, "open": is_open, "distance": 1.0, "last": end,
                 "duration": end - start, "aaTime": 0, "startReason": "speed"}, **summary)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "logger.db")
        self.store = Store(self.path, "1.1.0")
        self.reader = self.store.reader()

    def tearDown(self):
        self.reader.close()
        self.store.close()
        self.dir.cleanup()

    def sql(self, query, *params):
        return self.store.db.execute(query, params).fetchall()

    def test_schema(self):
        self.assertEqual(self.sql("PRAGMA journal_mode")[0][0], "wal")
        self.assertEqual(self.sql("PRAGMA auto_vacuum")[0][0], 2)  # incremental
        tables = {name for (name,) in self.sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tables, {"meta", "signal", "sample", "trip", "recording"})
        meta = dict(self.sql("SELECT key, value FROM meta"))
        self.assertEqual((meta["schema_version"], meta["logger_version"]), ("2", "1.1.0"))

    def test_values_keep_their_type(self):
        """Readable with any SQLite tool: integers, decimals, texts as they are; float noise removed."""
        self.store.describe("vehicle.speed.kmh", "km/h", "Vehicle speed", "org.openhu.can")
        self.store.write([(1, "vehicle.speed.kmh", 50.370000000000005), (2, "vehicle.speed.kmh", 51.0),
                          (1, "vehicle.gear.gear", "drive"), (1, "vehicle.gear.reverse", True),
                          (2, "vehicle.gear.reverse", False)])
        rows = self.sql("SELECT s.name, x.timestamp, x.value, typeof(x.value) FROM sample x "
                        "JOIN signal s ON s.id = x.signal_id ORDER BY s.name, x.timestamp")
        self.assertEqual(rows, [("vehicle.gear.gear", 1, "drive", "text"), ("vehicle.gear.reverse", 1, 1, "integer"),
                                ("vehicle.gear.reverse", 2, 0, "integer"), ("vehicle.speed.kmh", 1, 50.37, "real"),
                                ("vehicle.speed.kmh", 2, 51, "integer")])
        signal = self.sql("SELECT name, unit, description, source, first_seen FROM signal WHERE name = ?",
                          "vehicle.speed.kmh")[0]
        self.assertEqual(signal, ("vehicle.speed.kmh", "km/h", "Vehicle speed", "org.openhu.can", 1))
        # metadata arriving later updates the row
        self.store.describe("vehicle.gear.gear", description="Gear")
        self.assertEqual(self.sql("SELECT description FROM signal WHERE name = 'vehicle.gear.gear'")[0][0], "Gear")
        self.assertEqual(self.store.sample_count(), 5)
        self.assertEqual([normalize(v) for v in (True, 3.0, float("nan"), 1 / 3)], [1, 3, None, 0.333333333333])

    def test_same_time_replaces(self):
        self.store.write([(5, "a.b", 1), (5, "a.b", 2)])
        self.assertEqual(self.sql("SELECT value FROM sample"), [(2,)])

    def test_trips(self):
        trips = [trip(None, i * HOUR, i * HOUR + 30 * MIN, aaTime=10 * MIN) for i in range(5)]
        self.store.write(trips=trips)
        self.assertEqual([t["id"] for t in trips], [1, 2, 3, 4, 5])
        result = self.reader.trips(limit=2)
        self.assertEqual([t["id"] for t in result["trips"]], [5, 4])
        self.assertTrue(result["more"])
        self.assertEqual([t["id"] for t in self.reader.trips(before=4, limit=10)["trips"]], [3, 2, 1])
        self.assertEqual([t["id"] for t in self.reader.trips(start=HOUR + 40 * MIN, end=3 * HOUR + 1)["trips"]],
                         [4, 3])
        one = self.reader.trip(2)["trip"]
        self.assertEqual((one["start"], one["end"], one["open"], one["raw"], one["distance"], one["duration"],
                          one["aaTime"], one["startReason"]),
                         (HOUR, HOUR + 30 * MIN, False, True, 1.0, 30 * MIN, 10 * MIN, "speed"))
        self.assertNotIn("last", one)  # internal fields stay inside
        # readable columns
        self.assertEqual(self.sql("SELECT distance_km, duration_s, aa_time_s FROM trip WHERE id = 2")[0],
                         (1.0, 1800.0, 600.0))
        with self.assertRaises(QueryError):
            self.reader.trip(99)

    def test_open_trip_updates(self):
        running = trip(None, 0, MIN, True)
        self.store.write(trips=[running])
        running.update(end=5 * MIN, distance=4.2)
        self.store.write(trips=[running])
        self.assertEqual(len(self.store.open_trips()), 1)
        self.assertEqual(self.store.open_trips()[0]["last"], MIN)
        self.assertEqual(self.reader.trip(running["id"])["trip"]["distance"], 4.2)

    def test_samples_raw(self):
        self.store.write([(t * S, "vehicle.speed.kmh", t) for t in range(100)]
                         + [(t * S, "headunit.cpu_temp_c", 50) for t in range(0, 100, 10)])
        result = self.reader.samples(10 * S, 20 * S, ["vehicle.speed.kmh"], points=0)
        got = result["series"]["vehicle.speed.kmh"]
        self.assertEqual(got["t"], [t * S for t in range(10, 20)])
        self.assertEqual(got["v"], list(range(10, 20)))
        self.assertEqual(got["before"], 9)
        self.assertNotIn("headunit.cpu_temp_c", result["series"])
        self.assertFalse(result["more"])
        result = self.reader.samples(0, 100 * S, None, points=0, limit=50)
        self.assertTrue(result["more"])
        self.assertEqual(sum(len(s["v"]) for s in result["series"].values()), 50)

    def test_samples_downsampled(self):
        self.store.write([(t * S, "vehicle.speed.kmh", t % 10) for t in range(1000)]
                         + [(t * S, "vehicle.gear.gear", "drive" if t % 20 < 10 else "park") for t in range(0, 1000, 5)])
        result = self.reader.samples(0, 1000 * S, ["vehicle.speed.kmh", "vehicle.gear.gear"], points=100)
        self.assertEqual(result["bucket"], 10 * S)
        got = result["series"]["vehicle.speed.kmh"]
        self.assertEqual(len(got["t"]), 100)
        self.assertEqual(got["t"][:2], [0, 10 * S])
        self.assertEqual(got["v"][0], 4.5)
        self.assertEqual((got["min"][0], got["max"][0]), (0, 9))
        self.assertIsNone(got["before"])
        gear = result["series"]["vehicle.gear.gear"]
        self.assertEqual(gear["v"][:2], ["drive", "park"])  # texts: the last value of the bucket
        self.assertIsNone(gear["min"][0])
        with self.assertRaises(QueryError):
            self.reader.samples(0, S, None, points=MAX_POINTS + 1)

    def test_range_of(self):
        self.store.write(trips=[trip(None, 10 * S, 20 * S), trip(None, 30 * S, 40 * S, True)])
        self.assertEqual(self.reader.range_of({"trip": 1}, 99 * S), (10 * S, 20 * S + 1))
        self.assertEqual(self.reader.range_of({"trip": 2}, 99 * S), (30 * S, 99 * S + 1))
        self.assertEqual(self.reader.range_of({"start": 5, "end": 9}, 0), (5, 9))
        with self.assertRaises(QueryError):
            self.reader.range_of({}, 0)
        with self.assertRaises(QueryError):
            self.reader.range_of({"start": 9, "end": 5}, 0)

    def test_signals_and_events(self):
        self.store.describe("a.x", "km/h", "Speed")
        self.store.write([(S, "a.x", 1), (5 * S, "a.x", 2), (3 * S, "b.y", 7), (S, "vehicle.gear.gear", "drive"),
                          (2 * S, "phone.call_state", "idle"), (3 * S, "vehicle.gear.gear", "park")])
        signals = {s["name"]: s for s in self.reader.signals()["signals"]}
        self.assertEqual(signals["a.x"]["unit"], "km/h")
        self.assertEqual((signals["a.x"]["first"], signals["a.x"]["last"], signals["a.x"]["value"]), (S, 5 * S, 2))
        events = self.reader.events(0, 10 * S, "vehicle.*")["events"]
        self.assertEqual([e["value"] for e in events], ["drive", "park"])
        self.assertEqual(len(self.reader.events(0, 10 * S, "phone.call_state")["events"]), 1)
        result = self.reader.events(0, 10 * S, limit=2)
        self.assertEqual((len(result["events"]), result["more"]), (2, True))

    def fill(self, trips=4, rows=5000, first=0):
        """trips of rows samples each (100 ms apart), a closed summary each."""
        for i in range(first, first + trips):
            start = i * 2 * HOUR
            self.store.write([(start + n * 100, "vehicle.speed.kmh", RANDOM.randrange(13001) / 100)
                              for n in range(rows)], trips=[trip(None, start, start + rows * 100)])

    def test_limit_drops_oldest_trips_first(self):
        self.fill(trips=3)
        self.store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        three = self.store.used_bytes()
        self.fill(trips=1, first=3)
        self.store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        used = self.store.used_bytes()
        limit = used - (used - three) // 2  # half a trip too much
        self.assertGreater(self.store.enforce(limit), 0)
        self.assertLessEqual(self.store.used_bytes(), limit)
        raw = {t["id"]: t["raw"] for t in self.reader.trips()["trips"]}
        self.assertEqual(raw, {1: False, 2: True, 3: True, 4: True})
        self.assertEqual(len(self.reader.trips()["trips"]), 4)
        self.assertEqual(self.reader.samples(0, 2 * HOUR, None, points=0)["series"], {})
        self.assertEqual(self.sql("SELECT count(*) FROM sample")[0][0], 15000)
        self.assertEqual(self.store.sample_count(), 15000)
        self.assertEqual(self.store.enforce(limit), 0)

    def test_limit_without_trips(self):
        self.store.write([(n * 100, "headunit.cpu_load", RANDOM.randrange(10007) / 10) for n in range(50000)])
        used = self.store.used_bytes()
        self.store.enforce(used // 2)
        self.assertLessEqual(self.store.used_bytes(), used // 2)
        self.assertGreater(self.sql("SELECT min(timestamp) FROM sample")[0][0], 0)

    def test_lowered_limit_shrinks_file(self):
        self.fill()
        self.store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = os.path.getsize(self.path)
        self.store.enforce(before // 4)
        self.assertLess(os.path.getsize(self.path), before // 2)

    def test_max_age(self):
        self.fill(trips=2, rows=100)
        self.store.enforce(10 ** 12, max_age_ms=HOUR, now=3 * HOUR)
        raw = {t["id"]: t["raw"] for t in self.reader.trips()["trips"]}
        self.assertEqual(raw, {1: False, 2: True})

    def test_recordings_keep_their_samples(self):
        """Samples in recording windows are not dropped for the log's limit; they count against the recording quota,
        oldest recording first."""
        self.fill(trips=4, rows=3000)
        windows = [(i * 2 * HOUR + 10 * S, i * 2 * HOUR + 20 * S) for i in range(4)]
        for number, (start, end) in enumerate(windows):
            self.store.write(recordings=[{"start": start, "end": end, "open": False, "trigger": "manual",
                                          "label": "r%d" % number}])
        recordings = self.reader.recordings()["recordings"]
        self.assertEqual([r["samples"] for r in recordings], [101] * 4)  # 10 s at 10 Hz, both ends
        self.assertEqual(recordings[0]["label"], "r3")
        # the log limit drops trip 1 and 2, not their recording windows
        self.store.enforce(int(self.store.used_bytes() * 0.6))
        kept = self.reader.samples(0, 2 * HOUR, ["vehicle.speed.kmh"], points=0)["series"]["vehicle.speed.kmh"]["t"]
        self.assertEqual((kept[0], kept[-1], len(kept)), (windows[0][0], windows[0][1], 101))
        # the recording quota: two fit
        each = self.store.recording_bytes(1)
        self.store.enforce(10 ** 12, recording_limit_bytes=int(each * 2.5))
        self.assertEqual([r["id"] for r in self.reader.recordings()["recordings"]], [4, 3])
        self.assertEqual(self.reader.samples(*windows[0], None, points=0)["series"], {})
        self.assertEqual(self.store.sample_count(), self.sql("SELECT count(*) FROM sample")[0][0])

    def test_open_recordings_are_closed(self):
        recording = {"start": 0, "end": 10, "open": True, "trigger": "vehicle.engine.rpm above 3000"}
        self.store.write([(5, "a.b", 1)], recordings=[recording])
        self.store.close_recordings()
        saved = self.reader.recording(recording["id"])
        self.assertEqual((saved["open"], saved["samples"], saved["reason"]), (False, 1, "trigger"))

    def test_clear(self):
        self.fill(trips=1, rows=10)
        self.reader.close()
        self.store.clear()
        self.reader = self.store.reader()
        self.assertEqual(self.reader.trips()["trips"], [])
        self.assertEqual(self.reader.signals()["signals"], [])
        self.store.write([(0, "x.y", 1)])
        self.assertEqual(self.reader.signals()["signals"][0]["name"], "x.y")

    def test_damaged_file_is_put_aside(self):
        self.reader.close()
        self.store.close()
        with open(self.path, "wb") as file:
            file.write(b"this is not a database" * 100)
        store = Store(self.path)
        try:
            self.assertTrue(store.recovered.endswith("logger.db.damaged"))
            self.assertTrue(os.path.exists(store.recovered))
            store.write([(0, "x.y", 1)])
        finally:
            store.close()
        self.store = Store(self.path)
        self.reader = self.store.reader()
        self.assertIsNone(self.store.recovered)

    def test_old_schema_is_put_aside(self):
        self.reader.close()
        self.store.close()
        os.remove(self.path)
        old = sqlite3.connect(self.path)
        old.executescript("CREATE TABLE keys(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE blocks(key, t0, data);"
                          "INSERT INTO keys VALUES (1, 'vehicle.speed.kmh');")
        old.close()
        self.store = Store(self.path)
        self.reader = self.store.reader()
        self.assertTrue(self.store.old_schema.endswith("logger.db.old-schema"))
        kept = sqlite3.connect(self.store.old_schema)
        self.assertEqual(kept.execute("SELECT name FROM keys").fetchall(), [("vehicle.speed.kmh",)])
        kept.close()
        self.assertEqual(self.sql("SELECT value FROM meta WHERE key = 'schema_version'"), [("2",)])

    def test_failed_write_rolls_back(self):
        with self.assertRaises(sqlite3.Error):
            self.store.write([(0, "x.y", 1), (1, "x.y", object())])
        self.assertEqual(self.sql("SELECT count(*) FROM sample")[0][0], 0)
        self.assertEqual(self.store.signals, {})
        self.store.write([(0, "x.y", 1)])


if __name__ == "__main__":
    unittest.main()
