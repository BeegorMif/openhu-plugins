"""SQLite storage of the logger: signals, samples, trips, recordings, the size limits and the queries.

Plain tables, readable with any SQLite tool (times in ms since 1970):
    meta       (key, value)                     schema version, logger version
    signal     (id, name, unit, description, source, first_seen)
               one row per logged signal, created when it first appears; unit/description/source if known
    sample     (signal_id, timestamp, value)    WITHOUT ROWID, primary key (signal_id, timestamp); value without a
               type: integers take 1-6 bytes (0 and 1, e.g. booleans, none), decimals 8, texts ("drive") as text
    trip       (id, start_time, end_time, open, raw, start_reason, end_reason, distance_km, duration_s,
                max_speed_kmh, avg_speed_kmh, aa_time_s, fuel_l, consumption_l_100km, summary JSON for the rest)
    recording  (id, start_time, end_time, open, trigger, label, samples)
               a high-rate recording is a time window; its samples are in sample

Example: SELECT s.name, datetime(x.timestamp / 1000, 'unixepoch'), x.value
         FROM sample x JOIN signal s ON s.id = x.signal_id WHERE s.name = 'vehicle.speed.kmh';

WAL with synchronous=NORMAL: a power cut loses at most the last transactions, never the database. The writer
(Store) belongs to the process's event loop; queries use their own read connection (Store.reader()), which may run
in another thread.
"""

import json
import math
import os
import sqlite3
import time

SCHEMA_VERSION = 2
# trip summaries are kept after their samples are gone (a few hundred bytes each), up to this many
MAX_TRIPS = 100_000
# limits of one query, so an answer stays a reasonable bus message
MAX_POINTS = 2000
MAX_VALUES = 50_000
MAX_LIST = 1000
MAX_EVENTS = 5000
# bytes of one sample row before there are enough samples to measure it
DEFAULT_SAMPLE_BYTES = 20
# tables of the first version (compressed blocks), which is moved aside
OLD_TABLES = {"keys", "blocks", "events", "trips", "recordings", "rblocks"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS signal(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, unit TEXT, description TEXT,
    source TEXT, first_seen INTEGER);
CREATE TABLE IF NOT EXISTS sample(signal_id INTEGER NOT NULL, timestamp INTEGER NOT NULL, value,
    PRIMARY KEY (signal_id, timestamp)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS trip(id INTEGER PRIMARY KEY, start_time INTEGER NOT NULL, end_time INTEGER NOT NULL,
    open INTEGER NOT NULL DEFAULT 1, raw INTEGER NOT NULL DEFAULT 1, start_reason TEXT, end_reason TEXT,
    distance_km REAL, duration_s REAL, max_speed_kmh REAL, avg_speed_kmh REAL, aa_time_s REAL, fuel_l REAL,
    consumption_l_100km REAL, summary TEXT);
CREATE INDEX IF NOT EXISTS trip_start_time ON trip(start_time);
CREATE TABLE IF NOT EXISTS recording(id INTEGER PRIMARY KEY, start_time INTEGER NOT NULL, end_time INTEGER NOT NULL,
    open INTEGER NOT NULL DEFAULT 1, trigger TEXT NOT NULL, label TEXT, samples INTEGER NOT NULL DEFAULT 0);
"""

# trip dict (the interface) <-> columns; the rest goes into summary
TRIP_COLUMNS = {
    "startReason": "start_reason", "endReason": "end_reason", "distance": "distance_km",
    "maxSpeed": "max_speed_kmh", "avgSpeed": "avg_speed_kmh", "fuel": "fuel_l", "consumption": "consumption_l_100km",
}
TRIP_SELECT = ("SELECT id, start_time, end_time, open, raw, start_reason, end_reason, distance_km, duration_s, "
               "max_speed_kmh, avg_speed_kmh, aa_time_s, fuel_l, consumption_l_100km, summary FROM trip")
RECORDING_SELECT = "SELECT id, start_time, end_time, open, trigger, label, samples FROM recording"
# internal fields of a trip (trips.py), not shown in queries
INTERNAL = ("speedDistance", "last", "odometerStart", "odometerEnd", "fuelStart", "fuelEnd", "lastDuration",
            "lastAa", "atStop", "atEngineOff")


class QueryError(Exception):
    pass


def connect(path):
    db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def normalize(value):
    """The value as stored: booleans and whole numbers as integers, other numbers rounded to 12 significant digits
    (raw * 0.01 in floating point, 50.370000000000005, becomes 50.37), texts as they are."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return float("%.12g" % value)
    return value


def public_trip(trip):
    if trip is None:
        return None
    return {key: value for key, value in trip.items() if key not in INTERNAL}


def trip_row(row):
    (trip_id, start, end, is_open, raw, start_reason, end_reason, distance, duration, max_speed, avg_speed, aa_time,
     fuel, consumption, summary) = row
    trip = public_trip(json.loads(summary or "{}"))
    trip.update(id=trip_id, start=start, end=end, open=bool(is_open), raw=bool(raw), startReason=start_reason,
                endReason=end_reason, distance=distance, maxSpeed=max_speed, avgSpeed=avg_speed)
    trip["duration"] = int(round(duration * 1000)) if duration is not None else None
    trip["aaTime"] = int(round(aa_time * 1000)) if aa_time is not None else None
    if fuel is not None:
        trip.update(fuel=fuel, consumption=consumption)
    return trip


def recording_row(row, sample_bytes=DEFAULT_SAMPLE_BYTES):
    rec_id, start, end, is_open, trigger, label, samples = row
    return {"id": rec_id, "start": start, "end": end, "open": bool(is_open), "trigger": trigger,
            "reason": "manual" if trigger == "manual" else "trigger", "label": label or "", "samples": samples,
            "bytes": int(samples * sample_bytes)}


class Store:
    def __init__(self, path, version=None):
        self.path = path
        self.version = version or ""
        self.signals = {}        # name -> id
        self.signal_info = {}    # name -> {unit, description, source} known so far (from the sources)
        self.recovered = None    # name of a damaged database that was put aside
        self.old_schema = None   # name of a database of the first version that was put aside
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            self._open()
        except sqlite3.OperationalError:
            raise  # cannot open or write (permissions, disk full): not the file's fault
        except sqlite3.DatabaseError:
            # not a database or damaged beyond use: keep it for inspection (one copy), start a new one
            self.close()
            self.recovered = self._put_aside(".damaged")
            self._open()

    def _put_aside(self, suffix):
        target = self.path + suffix
        self._remove_files(target)
        for extra in ("", "-wal", "-shm"):
            if os.path.exists(self.path + extra):
                os.replace(self.path + extra, target + extra)
        return target

    def _open(self):
        self.db = None
        new = not os.path.exists(self.path)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=10)
        tables = {name for (name,) in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if tables & OLD_TABLES:
            # the first version (compressed blocks): kept as it is, a new database starts
            self.close()
            self.old_schema = self._put_aside(".old-schema")
            new = True
            self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=10)
        if new:
            # only possible before the first table (and before WAL); lets a lowered limit shrink the file
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('samples', '0')")
        if self.version:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('logger_version', ?)", (self.version,))
        self.signals = {name: signal_id for signal_id, name in self.db.execute("SELECT id, name FROM signal")}

    def close(self):
        if getattr(self, "db", None) is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                pass
            self.db = None

    @staticmethod
    def _remove_files(path):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass

    def reader(self):
        """A second connection for queries (Queries), usable from another thread."""
        return Queries(connect(self.path))

    # --- signals --------------------------------------------------------------------

    def describe(self, name, unit=None, description=None, source=None):
        """Unit, description, source of a signal, from its source; written at once for a signal that exists."""
        info = self.signal_info.setdefault(name, {})
        changed = False
        for key, value in (("unit", unit), ("description", description), ("source", source)):
            if value and info.get(key) != value:
                info[key] = value
                changed = True
        if changed and name in self.signals:
            self.db.execute("UPDATE signal SET unit = coalesce(?, unit), description = coalesce(?, description), "
                            "source = coalesce(?, source) WHERE id = ?",
                            (info.get("unit"), info.get("description"), info.get("source"), self.signals[name]))

    def signal_id(self, name, t):
        signal_id = self.signals.get(name)
        if signal_id is None:
            info = self.signal_info.get(name, {})
            self.db.execute("INSERT OR IGNORE INTO signal(name, unit, description, source, first_seen) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (name, info.get("unit"), info.get("description"), info.get("source"), t))
            signal_id = self.db.execute("SELECT id FROM signal WHERE name = ?", (name,)).fetchone()[0]
            self.signals[name] = signal_id
        return signal_id

    # --- writing --------------------------------------------------------------------

    def write(self, samples=(), trips=(), recordings=()):
        """One transaction.
        samples     [(t, signal name, value)]; a second sample of a signal with the same time replaces the first
        trips       summaries; a trip without id gets one (written into the dict)
        recordings  [{id?, start, end, open, trigger, label}]; one without id gets one"""
        db = self.db
        db.execute("BEGIN")
        try:
            rows = []
            for t, name, value in samples:
                value = normalize(value)
                if value is not None:
                    rows.append((self.signal_id(name, t), int(t), value))
            if rows:
                cursor = db.executemany("INSERT OR REPLACE INTO sample VALUES (?, ?, ?)", rows)
                db.execute("UPDATE meta SET value = CAST(value AS INTEGER) + ? WHERE key = 'samples'",
                           (max(0, cursor.rowcount),))
            for trip in trips:
                self._write_trip(trip)
            for recording in recordings:
                self._write_recording(recording)
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            # the signals added in this transaction are gone again
            self.signals = {name: signal_id for signal_id, name in db.execute("SELECT id, name FROM signal")}
            raise

    def _write_trip(self, trip):
        summary = json.dumps({key: value for key, value in trip.items()
                              if key not in ("id", "start", "end", "open", "raw", "duration", "aaTime")
                              and key not in TRIP_COLUMNS}, separators=(",", ":"))
        values = (trip["start"], trip["end"], int(bool(trip["open"])), trip.get("startReason"), trip.get("endReason"),
                  trip.get("distance"), trip.get("duration", 0) / 1000.0, trip.get("maxSpeed"), trip.get("avgSpeed"),
                  trip.get("aaTime", 0) / 1000.0, trip.get("fuel"), trip.get("consumption"), summary)
        if trip.get("id") is None:
            trip["id"] = self.db.execute(
                "INSERT INTO trip(start_time, end_time, open, start_reason, end_reason, distance_km, duration_s, "
                "max_speed_kmh, avg_speed_kmh, aa_time_s, fuel_l, consumption_l_100km, summary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values).lastrowid
        else:
            self.db.execute(
                "UPDATE trip SET start_time = ?, end_time = ?, open = ?, start_reason = ?, end_reason = ?, "
                "distance_km = ?, duration_s = ?, max_speed_kmh = ?, avg_speed_kmh = ?, aa_time_s = ?, fuel_l = ?, "
                "consumption_l_100km = ?, summary = ? WHERE id = ?", values + (trip["id"],))

    def _write_recording(self, recording):
        values = (recording["start"], recording["end"], int(bool(recording["open"])), recording["trigger"],
                  recording.get("label") or "")
        if recording.get("id") is None:
            recording["id"] = self.db.execute("INSERT INTO recording(start_time, end_time, open, trigger, label) "
                                              "VALUES (?, ?, ?, ?, ?)", values).lastrowid
        else:
            self.db.execute("UPDATE recording SET start_time = ?, end_time = ?, open = ?, trigger = ?, label = ? "
                            "WHERE id = ?", values + (recording["id"],))
        self.db.execute("UPDATE recording SET samples = ? WHERE id = ?",
                        (self._count_window(recording["start"], recording["end"]), recording["id"]))

    def _count_window(self, start, end):
        return sum(self.db.execute("SELECT count(*) FROM sample WHERE signal_id = ? AND timestamp BETWEEN ? AND ?",
                                   (signal_id, start, end)).fetchone()[0] for signal_id in self.signals.values())

    def open_trips(self):
        """Trips left open (process ended while driving or power cut), with their internal fields."""
        return [dict(json.loads(row[-1] or "{}"), **{k: v for k, v in trip_row(row).items()})
                for row in self.db.execute(TRIP_SELECT + " WHERE open = 1 ORDER BY start_time")]

    def close_recordings(self):
        """Recordings left open by the last run end at their last sample."""
        for rec_id, start, end in self.db.execute("SELECT id, start_time, end_time FROM recording WHERE open = 1")\
                .fetchall():
            self.db.execute("UPDATE recording SET open = 0, samples = ? WHERE id = ?",
                            (self._count_window(start, end), rec_id))

    # --- size -----------------------------------------------------------------------

    def file_bytes(self):
        total = 0
        for suffix in ("", "-wal"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total

    def used_bytes(self):
        """Bytes in use, without free pages (SQLite reuses them) and without the WAL (a few MB at most, reused after
        each checkpoint)."""
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        free = self.db.execute("PRAGMA freelist_count").fetchone()[0]
        return (pages - free) * page_size

    def sample_count(self):
        return int(self.db.execute("SELECT value FROM meta WHERE key = 'samples'").fetchone()[0])

    def sample_bytes(self):
        """Average bytes of a sample row (the database divided by the samples it holds)."""
        count = self.sample_count()
        return self.used_bytes() / count if count >= 1000 else DEFAULT_SAMPLE_BYTES

    def recording_bytes(self, rec_id=None):
        if rec_id is None:
            samples = self.db.execute("SELECT coalesce(sum(samples), 0) FROM recording").fetchone()[0]
        else:
            row = self.db.execute("SELECT samples FROM recording WHERE id = ?", (rec_id,)).fetchone()
            samples = row[0] if row else 0
        return int(samples * self.sample_bytes())

    def log_bytes(self):
        """What counts towards the log's limit: everything but the samples in recording windows."""
        return max(0, self.used_bytes() - self.recording_bytes())

    def enforce(self, limit_bytes, max_age_ms=0, now=None, recording_limit_bytes=None):
        """Applies the limits: recordings beyond their quota go first (oldest whole recordings with their samples,
        not the open one); then the log: the oldest samples outside recording windows, trip by trip (their summaries
        stay), and the oldest trip summaries above MAX_TRIPS. Returns the number of dropped samples."""
        dropped = 0
        if recording_limit_bytes is not None:
            while self.recording_bytes() > recording_limit_bytes:
                row = self.db.execute("SELECT id FROM recording WHERE open = 0 ORDER BY start_time LIMIT 1").fetchone()
                if row is None:
                    break
                dropped += self.delete_recording(row[0])
        if max_age_ms:
            now = now if now is not None else int(time.time() * 1000)
            dropped += self._drop_before(now - max_age_ms)
        # the pages in the WAL count once they are in the database
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        while self.log_bytes() > limit_bytes:
            cutoff = self._next_cutoff()
            if cutoff is None:
                break
            removed = self._drop_before(cutoff)
            dropped += removed
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
            if not removed and self._next_cutoff() == cutoff:
                break  # only recordings left
        excess = self.db.execute("SELECT count(*) FROM trip").fetchone()[0] - MAX_TRIPS
        if excess > 0:
            self.db.execute("DELETE FROM trip WHERE id IN (SELECT id FROM trip WHERE open = 0 "
                            "ORDER BY start_time LIMIT ?)", (excess,))
        total = limit_bytes + (recording_limit_bytes or 0)
        if self.file_bytes() > total * 1.25:
            # a limit was lowered: give the free pages back (writes, so only then)
            self.db.execute("PRAGMA incremental_vacuum").fetchall()  # one row per freed page: step them all
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return dropped

    def delete_recording(self, rec_id):
        """Deletes a recording and the samples in its window. Returns their number."""
        row = self.db.execute("SELECT start_time, end_time FROM recording WHERE id = ?", (rec_id,)).fetchone()
        if row is None:
            return 0
        self.db.execute("BEGIN")
        try:
            dropped = 0
            for signal_id in self.signals.values():
                dropped += self.db.execute("DELETE FROM sample WHERE signal_id = ? AND timestamp BETWEEN ? AND ?",
                                           (signal_id,) + tuple(row)).rowcount
            self.db.execute("DELETE FROM recording WHERE id = ?", (rec_id,))
            self._count_down(dropped)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return dropped

    def _first_sample(self):
        firsts = [self.db.execute("SELECT min(timestamp) FROM sample WHERE signal_id = ?", (signal_id,)).fetchone()[0]
                  for signal_id in self.signals.values()]
        return min([t for t in firsts if t is not None], default=None)

    def _next_cutoff(self):
        """End of the oldest closed trip that still has samples, else the oldest tenth of the logged time; samples
        in recording windows do not count (they are kept)."""
        firsts = [self.db.execute(
            "SELECT min(timestamp) FROM sample x WHERE signal_id = ? AND NOT EXISTS (SELECT 1 FROM recording r "
            "WHERE x.timestamp BETWEEN r.start_time AND r.end_time)", (signal_id,)).fetchone()[0]
            for signal_id in self.signals.values()]
        first = min([t for t in firsts if t is not None], default=None)
        if first is None:
            return None
        last = max(self.db.execute("SELECT max(timestamp) FROM sample WHERE signal_id = ?", (signal_id,)).fetchone()[0]
                   or 0 for signal_id in self.signals.values())
        row = self.db.execute("SELECT end_time FROM trip WHERE open = 0 AND raw = 1 AND end_time >= ? "
                              "ORDER BY start_time LIMIT 1", (first,)).fetchone()
        if row is not None and row[0] < last:
            return row[0] + 1
        return first + max(1, (last - first) // 10) + 1

    def _drop_before(self, cutoff):
        """Drops the samples before cutoff that are not in a recording window; trips that started before it lose
        their raw data."""
        self.db.execute("BEGIN")
        try:
            dropped = 0
            for signal_id in self.signals.values():
                dropped += self.db.execute(
                    "DELETE FROM sample WHERE signal_id = ? AND timestamp < ? AND NOT EXISTS (SELECT 1 FROM recording r "
                    "WHERE sample.timestamp BETWEEN r.start_time AND r.end_time)", (signal_id, cutoff)).rowcount
            self.db.execute("UPDATE trip SET raw = 0 WHERE raw = 1 AND open = 0 AND start_time < ?", (cutoff,))
            self._count_down(dropped)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return dropped

    def _count_down(self, dropped):
        if dropped:
            self.db.execute("UPDATE meta SET value = max(0, CAST(value AS INTEGER) - ?) WHERE key = 'samples'",
                            (dropped,))

    def clear(self):
        """Deletes everything (the files too) and starts an empty database."""
        self.close()
        self._remove_files(self.path)
        self._remove_files(self.path + ".damaged")
        self._remove_files(self.path + ".old-schema")
        self.recovered = self.old_schema = None
        self._open()

    def stats(self):
        trips = self.db.execute("SELECT count(*) FROM trip").fetchone()[0]
        recordings = self.db.execute("SELECT count(*) FROM recording").fetchone()[0]
        recording_bytes = self.recording_bytes()
        return {"usedBytes": max(0, self.used_bytes() - recording_bytes), "fileBytes": self.file_bytes(),
                "recordingBytes": recording_bytes, "trips": trips, "recordings": recordings,
                "signals": len(self.signals), "samples": self.sample_count(), "oldestSample": self._first_sample()}


class Queries:
    """Read side, the logger.query commands. Every method returns a JSON-serializable dict."""

    def __init__(self, db):
        self.db = db

    def close(self):
        self.db.close()

    def _signal_ids(self, names=None):
        rows = self.db.execute("SELECT id, name FROM signal ORDER BY name").fetchall()
        if names is None:
            return rows
        wanted = set(names)
        return [(signal_id, name) for signal_id, name in rows if name in wanted]

    # --- trips and recordings -------------------------------------------------------

    def trips(self, start=None, end=None, before=None, limit=50):
        """Trips overlapping [start, end), newest first; before = id for paging (only older ones)."""
        rows, more = self._list(TRIP_SELECT, start, end, before, limit)
        return {"trips": [trip_row(row) for row in rows], "more": more}

    def recordings(self, start=None, end=None, before=None, limit=50):
        rows, more = self._list(RECORDING_SELECT, start, end, before, limit)
        sample_bytes = self._sample_bytes()
        return {"recordings": [recording_row(row, sample_bytes) for row in rows], "more": more}

    def _sample_bytes(self):
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        pages = self.db.execute("PRAGMA page_count").fetchone()[0] - self.db.execute("PRAGMA freelist_count")\
            .fetchone()[0]
        count = int(self.db.execute("SELECT value FROM meta WHERE key = 'samples'").fetchone()[0])
        return pages * page_size / count if count >= 1000 else DEFAULT_SAMPLE_BYTES

    def _list(self, sql, start, end, before, limit):
        limit = max(1, min(int(limit), MAX_LIST))
        where, params = [], []
        if start is not None:
            where.append("end_time >= ?")
            params.append(int(start))
        if end is not None:
            where.append("start_time < ?")
            params.append(int(end))
        if before is not None:
            where.append("id < ?")
            params.append(int(before))
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.db.execute(sql + " ORDER BY start_time DESC, id DESC LIMIT ?", params + [limit + 1]).fetchall()
        return rows[:limit], len(rows) > limit

    def trip(self, trip_id):
        row = self.db.execute(TRIP_SELECT + " WHERE id = ?", (int(trip_id),)).fetchone()
        if row is None:
            raise QueryError("no trip %s" % trip_id)
        return {"trip": trip_row(row)}

    def recording(self, rec_id):
        row = self.db.execute(RECORDING_SELECT + " WHERE id = ?", (int(rec_id),)).fetchone()
        if row is None:
            raise QueryError("no recording %s" % rec_id)
        return recording_row(row, self._sample_bytes())

    def range_of(self, params, now):
        """[start, end) from start/end, a trip or a recording; start/end narrow a trip or recording."""
        bounds = None
        if params.get("trip") is not None:
            bounds = self.trip(params["trip"])["trip"]
        elif params.get("recording") is not None:
            bounds = self.recording(params["recording"])
        if bounds is not None:
            start = bounds["start"]
            end = (now if bounds["open"] else bounds["end"]) + 1
            if params.get("start") is not None:
                start = max(start, int(params["start"]))
            if params.get("end") is not None:
                end = min(end, int(params["end"]))
        else:
            if params.get("start") is None:
                raise QueryError("start, trip or recording missing")
            start = int(params["start"])
            end = int(params["end"]) if params.get("end") is not None else now + 1
        if end <= start:
            raise QueryError("end must be after start")
        return start, end

    # --- signals and samples --------------------------------------------------------

    def signals(self):
        result = []
        for signal_id, name, unit, description, source, first_seen in self.db.execute(
                "SELECT id, name, unit, description, source, first_seen FROM signal ORDER BY name").fetchall():
            first = self.db.execute("SELECT min(timestamp) FROM sample WHERE signal_id = ?", (signal_id,)).fetchone()[0]
            last = value = None
            if first is not None:
                last, value = self.db.execute("SELECT timestamp, value FROM sample WHERE signal_id = ? "
                                              "ORDER BY timestamp DESC LIMIT 1", (signal_id,)).fetchone()
            result.append({"name": name, "key": name, "unit": unit, "description": description, "source": source,
                           "firstSeen": first_seen, "first": first, "last": last, "value": value})
        return {"signals": result}

    def samples(self, start, end, keys=None, points=300, limit=5000):
        """Series per signal in [start, end).
        points > 0: downsampled into that many equal time buckets: t = bucket start, v = average, min, max of the
        samples in it (for texts: the last value, min/max null); empty buckets are left out.
        points = 0: the raw samples, up to limit values in all (more = true if cut).
        before = the value held at start (last sample before it). Signals without data there are left out."""
        points = int(points)
        if points < 0 or points > MAX_POINTS:
            raise QueryError("points must be 0..%d" % MAX_POINTS)
        signal_ids = self._signal_ids(keys)
        series, more = {}, False
        if points:
            if points * len(signal_ids) > MAX_VALUES:
                raise QueryError("too many values (signals x points > %d), ask for fewer signals or points"
                                 % MAX_VALUES)
            bucket = max(1, math.ceil((end - start) / points))
            for signal_id, name in signal_ids:
                rows = self.db.execute(
                    "SELECT (timestamp - ?) / ? AS b, avg(value), min(value), max(value), "
                    "sum(typeof(value) = 'text'), value, max(timestamp) FROM sample "
                    "WHERE signal_id = ? AND timestamp >= ? AND timestamp < ? GROUP BY b ORDER BY b",
                    (start, bucket, signal_id, start, end)).fetchall()
                before = self._before(signal_id, start)
                if not rows and before is None:
                    continue
                entry = {"t": [], "v": [], "min": [], "max": [], "before": before}
                for b, average, low, high, texts, last, _ in rows:
                    entry["t"].append(start + b * bucket)
                    if texts:
                        entry["v"].append(last)
                        entry["min"].append(None)
                        entry["max"].append(None)
                    else:
                        entry["v"].append(round(average, 4))
                        entry["min"].append(low)
                        entry["max"].append(high)
                series[name] = entry
            return {"start": start, "end": end, "points": points, "bucket": bucket, "series": series}
        budget = max(1, min(int(limit), MAX_VALUES))
        for index, (signal_id, name) in enumerate(signal_ids):
            rows = self.db.execute("SELECT timestamp, value FROM sample WHERE signal_id = ? AND timestamp >= ? "
                                   "AND timestamp < ? ORDER BY timestamp LIMIT ?",
                                   (signal_id, start, end, budget + 1)).fetchall()
            if len(rows) > budget:
                rows, more = rows[:budget], True
            before = self._before(signal_id, start)
            if rows or before is not None:
                series[name] = {"t": [t for t, _ in rows], "v": [v for _, v in rows], "before": before}
            budget -= len(rows)
            if budget <= 0:
                more = more or index < len(signal_ids) - 1
                break
        return {"start": start, "end": end, "points": 0, "series": series, "more": more}

    def _before(self, signal_id, start):
        row = self.db.execute("SELECT value FROM sample WHERE signal_id = ? AND timestamp < ? "
                              "ORDER BY timestamp DESC LIMIT 1", (signal_id, start)).fetchone()
        return row[0] if row else None

    def events(self, start, end, pattern=None, limit=1000):
        """Text samples (gear "drive", call state, ...) in [start, end), oldest first; pattern = a signal name or a
        prefix ending in ".*"."""
        limit = max(1, min(int(limit), MAX_EVENTS))
        names = [(signal_id, name) for signal_id, name in self._signal_ids()
                 if not pattern or name == pattern or (pattern.endswith(".*") and name.startswith(pattern[:-1]))]
        rows = []
        for signal_id, name in names:
            rows += [(t, name, value) for t, value in self.db.execute(
                "SELECT timestamp, value FROM sample WHERE signal_id = ? AND timestamp >= ? AND timestamp < ? "
                "AND typeof(value) = 'text' ORDER BY timestamp LIMIT ?", (signal_id, start, end, limit + 1))]
        rows.sort()
        return {"start": start, "end": end, "events": [{"t": t, "key": name, "value": value}
                                                       for t, name, value in rows[:limit]],
                "more": len(rows) > limit}
