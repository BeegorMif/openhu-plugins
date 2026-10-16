"""SQLite store: writing, queries (trips, samples raw and downsampled, events, keys, recordings), size limits,
damaged files; the block codec."""

import math
import os
import random
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

import codec  # noqa: E402
from logstore import MAX_BLOCK_MS, MAX_BLOCK_VALUES, MAX_POINTS, SUMMARY_BUCKET_MS, QueryError, Store  # noqa: E402

RANDOM = random.Random(1)  # noisy values that do not compress away
S = 1000
MIN = 60 * S
HOUR = 60 * MIN


def series(*samples):
    """[(t, key, value)] -> {key: (times, values)}"""
    result = {}
    for t, key, value in samples:
        times, values = result.setdefault(key, ([], []))
        times.append(t)
        values.append(value)
    return result


class CodecTest(unittest.TestCase):
    def roundtrip(self, times, values):
        decoded = codec.decode(times[0] if times else 0, codec.encode(times, values))
        self.assertEqual(decoded, (times, [float(v) for v in values]))

    def test_roundtrip(self):
        self.roundtrip([0, 100, 200, 190, 5000], [50.37, 50.41, -3.5, 0.0, 1e-7])  # decimals, time going back
        self.roundtrip([7], [123456.7])
        self.roundtrip([], [])
        self.roundtrip([1, 2, 3], [1 / 3, math.pi, 1e300])  # floats
        self.roundtrip([1, 2], [float("inf"), -1.0])

    def test_floating_point_noise(self):
        """raw * scale in floating point: stored as the decimal it means."""
        values = [raw * 0.01 for raw in (5037, 5041, 12345)] + [raw * 0.1 + 0.2 for raw in (3, 7)]
        times, decoded = codec.decode(0, codec.encode([0, 1, 2, 3, 4], values))
        self.assertEqual(decoded, [50.37, 50.41, 123.45, 0.5, 0.9])
        for value, back in zip(values, decoded):
            self.assertAlmostEqual(value, back, delta=abs(value) * 1e-12)

    def test_compact(self):
        times = list(range(0, 30_000, 100))
        values = [round(800 + 10 * math.sin(i / 20), 0) for i in range(len(times))]
        self.assertLess(len(codec.encode(times, values)), len(times))  # < 1 byte per sample (time and value)


def trip(trip_id, start, end, is_open=False, **summary):
    return dict({"id": trip_id, "start": start, "end": end, "open": is_open, "distance": 1.0, "last": end},
                **summary)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "logger.db")
        self.store = Store(self.path)
        self.reader = self.store.reader()

    def tearDown(self):
        self.reader.close()
        self.store.close()
        self.dir.cleanup()

    def test_settings(self):
        self.assertEqual(self.store.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.store.db.execute("PRAGMA auto_vacuum").fetchone()[0], 2)  # incremental

    def test_blocks_are_bounded(self):
        times = list(range(0, 10 * MAX_BLOCK_VALUES, 10))
        self.store.write(series(*[(t, "a.b", t % 7) for t in times]))
        rows = self.store.db.execute("SELECT t0, t1, n FROM blocks ORDER BY t0").fetchall()
        self.assertEqual(sum(n for _, _, n in rows), len(times))
        self.assertTrue(all(n <= MAX_BLOCK_VALUES and t1 - t0 <= MAX_BLOCK_MS for t0, t1, n in rows))

    def test_trips(self):
        trips = [trip(None, i * HOUR, i * HOUR + 30 * MIN) for i in range(5)]
        self.store.write(trips=trips)
        self.assertEqual([t["id"] for t in trips], [1, 2, 3, 4, 5])
        result = self.reader.trips(limit=2)
        self.assertEqual([t["id"] for t in result["trips"]], [5, 4])
        self.assertTrue(result["more"])
        self.assertEqual([t["id"] for t in self.reader.trips(before=4, limit=10)["trips"]], [3, 2, 1])
        # overlapping a time range
        self.assertEqual([t["id"] for t in self.reader.trips(start=HOUR + 40 * MIN, end=3 * HOUR + 1)["trips"]],
                         [4, 3])
        one = self.reader.trip(2)["trip"]
        self.assertEqual((one["start"], one["end"], one["open"], one["raw"], one["distance"]),
                         (HOUR, HOUR + 30 * MIN, False, True, 1.0))
        self.assertNotIn("last", one)  # internal fields stay inside
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
        self.store.write(series(*([(t * S, "vehicle.speed.kmh", t) for t in range(100)]
                                + [(t * S, "hu.cpuTemp", 50) for t in range(0, 100, 10)])))
        result = self.reader.samples(10 * S, 20 * S, ["vehicle.speed.kmh"], points=0)
        got = result["series"]["vehicle.speed.kmh"]
        self.assertEqual(got["t"], [t * S for t in range(10, 20)])
        self.assertEqual(got["v"], list(range(10, 20)))
        self.assertEqual(got["before"], 9)
        self.assertNotIn("hu.cpuTemp", result["series"])
        self.assertFalse(result["more"])
        # the limit counts all keys together
        result = self.reader.samples(0, 100 * S, None, points=0, limit=50)
        self.assertTrue(result["more"])
        self.assertEqual(sum(len(s["v"]) for s in result["series"].values()), 50)

    def test_samples_downsampled(self):
        self.store.write(series(*[(t * S, "vehicle.speed.kmh", t % 10) for t in range(1000)]))
        result = self.reader.samples(0, 1000 * S, ["vehicle.speed.kmh"], points=100)
        self.assertEqual(result["bucket"], 10 * S)
        got = result["series"]["vehicle.speed.kmh"]
        self.assertEqual(len(got["t"]), 100)
        self.assertEqual(got["t"][:2], [0, 10 * S])
        self.assertEqual(got["v"][0], 4.5)
        self.assertEqual((got["min"][0], got["max"][0]), (0, 9))
        self.assertIsNone(got["before"])
        with self.assertRaises(QueryError):
            self.reader.samples(0, S, None, points=MAX_POINTS + 1)

    def test_samples_across_blocks(self):
        """Written in several batches (blocks); before comes from an earlier block."""
        for batch in range(5):
            self.store.write(series(*[(t * S, "x.y", t) for t in range(batch * 30, batch * 30 + 30)]))
        result = self.reader.samples(45 * S, 100 * S, ["x.y"], points=0)
        self.assertEqual(result["series"]["x.y"]["v"], list(range(45, 100)))
        self.assertEqual(result["series"]["x.y"]["before"], 44)
        result = self.reader.samples(0, 150 * S, ["x.y"], points=0, limit=70)
        self.assertEqual((len(result["series"]["x.y"]["v"]), result["more"]), (70, True))

    def test_long_range_uses_block_summaries(self):
        day = 24 * HOUR
        self.store.write(series(*[(t * 10 * S, "x.y", t % 100) for t in range(day // (10 * S))]))
        result = self.reader.samples(0, day, ["x.y"], points=48)
        self.assertGreaterEqual(result["bucket"], SUMMARY_BUCKET_MS)
        values = result["series"]["x.y"]
        self.assertEqual(len(values["t"]), 48)
        self.assertEqual((min(values["min"]), max(values["max"])), (0, 99))
        self.assertAlmostEqual(sum(values["v"]) / 48, 49.5, delta=1)

    def test_range_of(self):
        self.store.write(trips=[trip(None, 10 * S, 20 * S), trip(None, 30 * S, 40 * S, True)])
        self.assertEqual(self.reader.range_of({"trip": 1}, 99 * S), (10 * S, 20 * S + 1))
        self.assertEqual(self.reader.range_of({"trip": 2}, 99 * S), (30 * S, 99 * S + 1))
        self.assertEqual(self.reader.range_of({"start": 5, "end": 9}, 0), (5, 9))
        with self.assertRaises(QueryError):
            self.reader.range_of({}, 0)
        with self.assertRaises(QueryError):
            self.reader.range_of({"start": 9, "end": 5}, 0)

    def test_keys_and_events(self):
        self.store.write(series((S, "a.x", 1), (5 * S, "a.x", 2), (3 * S, "b.y", 7)),
                         events=[(S, "vehicle.gear", {"gear": "drive"}), (2 * S, "phone.status", {"callState": "idle"}),
                                 (3 * S, "vehicle.gear", {"gear": "park"})])
        self.assertEqual(self.reader.keys()["keys"], [{"key": "a.x", "first": S, "last": 5 * S, "value": 2},
                                                      {"key": "b.y", "first": 3 * S, "last": 3 * S, "value": 7}])
        events = self.reader.events(0, 10 * S, "vehicle.*")["events"]
        self.assertEqual([e["data"]["gear"] for e in events], ["drive", "park"])
        self.assertEqual(len(self.reader.events(0, 10 * S, "phone.status")["events"]), 1)
        result = self.reader.events(0, 10 * S, limit=2)
        self.assertEqual((len(result["events"]), result["more"]), (2, True))

    def fill(self, trips=4, rows=20000, first=0):
        """trips of one hour each, rows samples per trip, a closed summary each."""
        for i in range(first, first + trips):
            start = i * 2 * HOUR
            self.store.write(series(*[(start + n * 100, "vehicle.speed.kmh", RANDOM.randrange(13001) / 100)
                                      for n in range(rows)]),
                             events=[(start, "logger.trip", {"event": "start"})],
                             trips=[trip(None, start, start + rows * 100)])

    def test_limit_drops_oldest_trips_first(self):
        self.fill(trips=3)
        self.store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        three = self.store.used_bytes()
        self.fill(trips=1, first=3)
        self.store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        used = self.store.used_bytes()
        limit = used - (used - three) // 2  # half a trip too much
        dropped = self.store.enforce(limit)
        self.assertGreater(dropped, 0)
        self.assertLessEqual(self.store.used_bytes(), limit)
        raw = {t["id"]: t["raw"] for t in self.reader.trips()["trips"]}
        self.assertEqual(raw, {1: False, 2: True, 3: True, 4: True})
        # summaries stay, the samples of trip 1 are gone, the others complete
        self.assertEqual(len(self.reader.trips()["trips"]), 4)
        self.assertEqual(self.reader.samples(0, 2 * HOUR, None, points=0)["series"], {})
        self.assertEqual(self.store.db.execute("SELECT sum(n) FROM blocks").fetchone()[0], 60000)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 3)
        # under the limit: nothing more
        self.assertEqual(self.store.enforce(limit), 0)

    def test_limit_without_trips(self):
        self.store.write(series(*[(n * 100, "hu.load", RANDOM.randrange(10007) / 10) for n in range(100000)]))
        used = self.store.used_bytes()
        self.store.enforce(used // 2)
        self.assertLessEqual(self.store.used_bytes(), used // 2)
        first = self.store.db.execute("SELECT min(t0) FROM blocks").fetchone()[0]
        self.assertGreater(first, 0)

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

    def test_clear(self):
        self.fill(trips=1, rows=10)
        self.reader.close()
        self.store.clear()
        self.reader = self.store.reader()
        self.assertEqual(self.reader.trips()["trips"], [])
        self.assertEqual(self.reader.keys()["keys"], [])
        self.store.write(series((0, "x.y", 1)))
        self.assertEqual(self.reader.keys()["keys"][0]["key"], "x.y")

    def test_damaged_file_is_put_aside(self):
        self.reader.close()
        self.store.close()
        with open(self.path, "wb") as file:
            file.write(b"this is not a database" * 100)
        store = Store(self.path)
        try:
            self.assertTrue(store.recovered.endswith("logger.db.damaged"))
            self.assertTrue(os.path.exists(store.recovered))
            store.write(series((0, "x.y", 1)))
        finally:
            store.close()
        self.store = Store(self.path)
        self.reader = self.store.reader()
        self.assertIsNone(self.store.recovered)

    def test_failed_write_rolls_back(self):
        with self.assertRaises(TypeError):
            self.store.write(series((0, "x.y", 1)), events=[(0, "t", {"bad": object()})])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM blocks").fetchone()[0], 0)
        self.assertEqual(self.store.keys, {})
        self.store.write(series((0, "x.y", 1)))

    def test_recordings_have_their_own_quota(self):
        self.fill(trips=2, rows=2000)
        log_rows = self.store.db.execute("SELECT sum(n) FROM blocks").fetchone()[0]
        for number in range(3):
            recording = {"start": number * HOUR, "end": number * HOUR + MIN, "open": False, "reason": "manual",
                         "label": "r%d" % number}
            self.store.write(recordings=[recording])
            self.store.write(rseries={(recording["id"], "vehicle.engine.rpm"): (
                [number * HOUR + i * 10 for i in range(6000)], [RANDOM.randrange(6007) for i in range(6000)])})
        each = max(self.store.recording_bytes(n) for n in (1, 2, 3))
        self.assertGreater(each, 1000)
        self.assertAlmostEqual(self.store.recording_bytes(), 3 * each, delta=each * 0.05)
        # the log limit is far away; the recording quota holds two of them: the oldest goes
        self.store.enforce(10 ** 12, recording_limit_bytes=int(each * 2.5))
        self.assertEqual([r["id"] for r in self.reader.recordings()["recordings"]], [3, 2])
        self.assertEqual(self.reader.recordings()["recordings"][0]["label"], "r2")
        self.assertEqual(self.store.db.execute("SELECT sum(n) FROM blocks").fetchone()[0], log_rows)
        result = self.reader.samples(*self.reader.range_of({"recording": 3}, 0), points=0, limit=10000, recording=3)
        self.assertEqual(len(result["series"]["vehicle.engine.rpm"]["v"]), 6000)
        self.assertNotIn("vehicle.speed.kmh", result["series"])
        self.assertEqual(self.reader.keys(recording=3)["keys"][0]["key"], "vehicle.engine.rpm")
        # recordings do not count towards the log limit
        self.assertEqual(self.store.log_bytes(), self.store.used_bytes() - self.store.recording_bytes())

    def test_open_recordings_are_closed(self):
        recording = {"start": 0, "end": 0, "open": True, "reason": "trigger"}
        self.store.write(recordings=[recording])
        self.store.write(rseries={(recording["id"], "a.b"): ([10, 20, 30], [1, 2, 3])})
        self.store.close_recordings()
        self.assertEqual(self.reader.recording(recording["id"])["end"], 30)
        self.assertFalse(self.reader.recording(recording["id"])["open"])

    def test_reader_sees_writes(self):
        self.store.write(series((0, "x.y", 1)))
        self.assertEqual(len(self.reader.keys()["keys"]), 1)
        self.assertIsInstance(self.reader.db, sqlite3.Connection)


if __name__ == "__main__":
    unittest.main()
