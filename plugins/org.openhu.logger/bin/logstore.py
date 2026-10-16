"""SQLite storage of the logger: sample blocks, events, trips, recordings, the size limits and the queries.

Times are ms since 1970. Tables:
    keys        (id, name)                                logged keys, e.g. "vehicle.speed.kmh"
    blocks      (key, t0, t1, n, vmin, vmax, vsum, data)   the continuous log: the samples of one key from t0 to t1,
                                                          compressed (codec.py), with a summary for long-range queries
    events      (id, t, topic, data JSON)                 discrete changes (gear, Android Auto, call state, trips)
    trips       (id, started, ended, open, raw, summary JSON)
    recordings  (id, started, ended, open, reason, label, bytes)  high-rate recordings, their own quota
    rblocks     (rec, key, t0, t1, n, vmin, vmax, vsum, data)  their samples
    meta        (name, value)                             schema version

A block holds at most MAX_BLOCK_VALUES samples and MAX_BLOCK_MS of time (the process closes its blocks at every
batched write, so they are usually shorter). One row per block and key instead of one per value keeps the size at a
few bytes per value even at 10-100 Hz.

WAL with synchronous=NORMAL: a power cut loses at most the last transactions, never the database. The writer
(Store) belongs to the process's event loop; queries use their own read connection (Store.reader()), which may run
in another thread.
"""

import json
import math
import os
import sqlite3
import time

import codec

SCHEMA_VERSION = 1
MAX_BLOCK_VALUES = 4096
MAX_BLOCK_MS = 120_000
# trip summaries are kept after their samples are gone (a few hundred bytes each), up to this many
MAX_TRIPS = 100_000
# limits of one query, so an answer stays a reasonable bus message
MAX_POINTS = 2000
MAX_VALUES = 50_000
MAX_LIST = 1000
MAX_EVENTS = 5000
# downsampled queries with buckets at least this long use the block summaries instead of decoding the blocks
SUMMARY_BUCKET_MS = 4 * MAX_BLOCK_MS

BLOCK_COLUMNS = "key INTEGER NOT NULL, t0 INTEGER NOT NULL, t1 INTEGER NOT NULL, n INTEGER NOT NULL, " \
                "vmin REAL, vmax REAL, vsum REAL, data BLOB NOT NULL"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS keys(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS blocks(%(block)s);
CREATE INDEX IF NOT EXISTS blocks_key_t0 ON blocks(key, t0);
CREATE INDEX IF NOT EXISTS blocks_t0 ON blocks(t0);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, t INTEGER NOT NULL, topic TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_t ON events(t);
CREATE TABLE IF NOT EXISTS trips(id INTEGER PRIMARY KEY, started INTEGER NOT NULL, ended INTEGER NOT NULL,
    open INTEGER NOT NULL DEFAULT 1, raw INTEGER NOT NULL DEFAULT 1, summary TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS trips_started ON trips(started);
CREATE TABLE IF NOT EXISTS recordings(id INTEGER PRIMARY KEY, started INTEGER NOT NULL, ended INTEGER NOT NULL,
    open INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', bytes INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS rblocks(rec INTEGER NOT NULL, %(block)s);
CREATE INDEX IF NOT EXISTS rblocks_rec_key_t0 ON rblocks(rec, key, t0);
""" % {"block": BLOCK_COLUMNS}

INTERNAL = ("speedDistance", "last", "odometerStart", "odometerEnd", "fuelStart", "fuelEnd")


class QueryError(Exception):
    pass


def connect(path):
    db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def public_trip(trip):
    if trip is None:
        return None
    return {key: value for key, value in trip.items() if key not in INTERNAL}


def trip_row(row):
    trip_id, started, ended, is_open, raw, summary = row
    trip = public_trip(json.loads(summary))
    trip.update(id=trip_id, start=started, end=ended, open=bool(is_open), raw=bool(raw))
    return trip


def recording_row(row):
    rec_id, started, ended, is_open, reason, label, size = row
    return {"id": rec_id, "start": started, "end": ended, "open": bool(is_open), "reason": reason, "label": label,
            "bytes": size}


def block_values(times, values):
    """Splits samples into block rows (t0, t1, n, vmin, vmax, vsum, data) of at most MAX_BLOCK_VALUES/MAX_BLOCK_MS."""
    rows, first = [], 0
    for index in range(1, len(times) + 1):
        if index == len(times) or index - first >= MAX_BLOCK_VALUES or times[index] - times[first] > MAX_BLOCK_MS:
            ts, vs = times[first:index], values[first:index]
            rows.append((ts[0], max(ts), len(ts), min(vs), max(vs), math.fsum(vs), codec.encode(ts, vs)))
            first = index
    return rows


class Store:
    def __init__(self, path):
        self.path = path
        self.keys = {}
        self.recovered = None  # name of a damaged database that was put aside
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        try:
            self._open()
        except sqlite3.OperationalError:
            raise  # cannot open or write (permissions, disk full): not the file's fault
        except sqlite3.DatabaseError:
            # not a database or damaged beyond use: keep it for inspection (one copy), start a new one
            self.close()
            self.recovered = path + ".damaged"
            self._remove_files(self.recovered)
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(path + suffix):
                    os.replace(path + suffix, self.recovered + suffix)
            self._open()

    def _open(self):
        self.db = None
        new = not os.path.exists(self.path)
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=10)
        if new:
            # only possible before the first table (and before WAL); lets a lowered limit shrink the file
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        self.keys = {name: key_id for key_id, name in self.db.execute("SELECT id, name FROM keys")}

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

    # --- writing --------------------------------------------------------------------

    def key_id(self, name):
        key_id = self.keys.get(name)
        if key_id is None:
            self.db.execute("INSERT OR IGNORE INTO keys(name) VALUES (?)", (name,))
            key_id = self.db.execute("SELECT id FROM keys WHERE name = ?", (name,)).fetchone()[0]
            self.keys[name] = key_id
        return key_id

    def write(self, series=None, events=(), trips=(), recordings=(), rseries=None):
        """One transaction.
        series      {key name: (times, values)} for the continuous log
        events      [(t, topic, data dict)]
        trips       summaries; a trip without id gets one (written into the dict)
        recordings  [{id?, start, end, open, reason, label}]; one without id gets one
        rseries     {(recording id, key name): (times, values)}"""
        db = self.db
        db.execute("BEGIN")
        try:
            rows = []
            for key, (times, values) in (series or {}).items():
                if times:
                    key_id = self.key_id(key)
                    rows += [(key_id,) + row for row in block_values(times, values)]
            db.executemany("INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            db.executemany("INSERT INTO events(t, topic, data) VALUES (?, ?, ?)",
                           [(t, topic, json.dumps(data, separators=(",", ":"))) for t, topic, data in events])
            for trip in trips:
                self._write_trip(trip)
            for recording in recordings:
                self._write_recording(recording)
            sizes = {}
            for (rec_id, key), (times, values) in (rseries or {}).items():
                if times:
                    key_id = self.key_id(key)
                    for row in block_values(times, values):
                        db.execute("INSERT INTO rblocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (rec_id, key_id) + row)
                        sizes[rec_id] = sizes.get(rec_id, 0) + len(row[-1]) + 64
            for rec_id, size in sizes.items():
                db.execute("UPDATE recordings SET bytes = bytes + ? WHERE id = ?", (size, rec_id))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            # the keys and ids added in this transaction are gone again
            self.keys = {name: key_id for key_id, name in db.execute("SELECT id, name FROM keys")}
            raise

    def _write_trip(self, trip):
        summary = json.dumps({key: value for key, value in trip.items()
                              if key not in ("id", "start", "end", "open", "raw")}, separators=(",", ":"))
        values = (trip["start"], trip["end"], int(bool(trip["open"])), summary)
        if trip.get("id") is None:
            trip["id"] = self.db.execute("INSERT INTO trips(started, ended, open, summary) VALUES (?, ?, ?, ?)",
                                         values).lastrowid
        else:
            self.db.execute("UPDATE trips SET started = ?, ended = ?, open = ?, summary = ? WHERE id = ?",
                            values + (trip["id"],))

    def _write_recording(self, recording):
        values = (recording["start"], recording["end"], int(bool(recording["open"])), recording["reason"],
                  recording.get("label") or "")
        if recording.get("id") is None:
            recording["id"] = self.db.execute("INSERT INTO recordings(started, ended, open, reason, label) "
                                              "VALUES (?, ?, ?, ?, ?)", values).lastrowid
        else:
            self.db.execute("UPDATE recordings SET started = ?, ended = ?, open = ?, reason = ?, label = ? "
                            "WHERE id = ?",
                            values + (recording["id"],))

    def open_trips(self):
        """Trips left open (process ended while driving or power cut), with their internal fields."""
        trips = []
        for trip_id, started, ended, summary in self.db.execute(
                "SELECT id, started, ended, summary FROM trips WHERE open = 1 ORDER BY started"):
            trip = json.loads(summary)
            trip.update(id=trip_id, start=started, end=ended, open=True)
            trips.append(trip)
        return trips

    def close_recordings(self):
        """Recordings left open by the last run end at their last sample."""
        self.db.execute("UPDATE recordings SET open = 0, ended = max(started, coalesce("
                        "(SELECT max(t1) FROM rblocks WHERE rec = recordings.id), ended)) WHERE open = 1")

    def recording_bytes(self, rec_id=None):
        if rec_id is None:
            return self.db.execute("SELECT coalesce(sum(bytes), 0) FROM recordings").fetchone()[0]
        row = self.db.execute("SELECT bytes FROM recordings WHERE id = ?", (rec_id,)).fetchone()
        return row[0] if row else 0

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

    def log_bytes(self):
        """What counts towards the log's limit: everything but the recordings."""
        return max(0, self.used_bytes() - self.recording_bytes())

    def enforce(self, limit_bytes, max_age_ms=0, now=None, recording_limit_bytes=None):
        """Applies the limits: recordings beyond their quota go first (oldest whole recordings, not the open one);
        then the log: the blocks and events of the oldest trips (their summaries stay), and the oldest trip summaries
        above MAX_TRIPS. Returns the number of dropped log blocks."""
        if recording_limit_bytes is not None:
            while self.recording_bytes() > recording_limit_bytes:
                row = self.db.execute("SELECT id FROM recordings WHERE open = 0 ORDER BY started LIMIT 1").fetchone()
                if row is None:
                    break
                self.delete_recording(row[0])
        dropped = 0
        if max_age_ms:
            now = now if now is not None else int(time.time() * 1000)
            dropped += self._drop_before(now - max_age_ms)
        # the pages in the WAL count once they are in the database
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        while self.log_bytes() > limit_bytes:
            cutoff = self._next_cutoff()
            if cutoff is None:
                break
            dropped += self._drop_before(cutoff)
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        excess = self.db.execute("SELECT count(*) FROM trips").fetchone()[0] - MAX_TRIPS
        if excess > 0:
            self.db.execute("DELETE FROM trips WHERE id IN (SELECT id FROM trips WHERE open = 0 "
                            "ORDER BY started LIMIT ?)", (excess,))
        total = limit_bytes + (recording_limit_bytes or 0)
        if self.file_bytes() > total * 1.25:
            # a limit was lowered: give the free pages back (writes, so only then)
            self.db.execute("PRAGMA incremental_vacuum").fetchall()  # one row per freed page: step them all
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return dropped

    def delete_recording(self, rec_id):
        self.db.execute("BEGIN")
        try:
            self.db.execute("DELETE FROM rblocks WHERE rec = ?", (rec_id,))
            self.db.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _next_cutoff(self):
        """End of the oldest closed trip that still has samples, else the oldest tenth of the logged time."""
        first, last, first_end = self.db.execute("SELECT min(t0), max(t1), min(t1) FROM blocks").fetchone()
        if first is None:
            first, last = self.db.execute("SELECT min(t), max(t) FROM events").fetchone()
            if first is None:
                return None
        row = self.db.execute("SELECT ended FROM trips WHERE open = 0 AND raw = 1 AND ended >= ? "
                              "ORDER BY started LIMIT 1", (first,)).fetchone()
        if row is not None and row[0] < last:
            cutoff = row[0] + 1
        else:
            cutoff = first + max(1, (last - first) // 10) + 1
        # at least one whole block
        return max(cutoff, first_end + 1) if first_end is not None else cutoff

    def _drop_before(self, cutoff):
        """Drops the blocks that end and the events before cutoff; trips that started before it lose their raw
        data."""
        self.db.execute("BEGIN")
        try:
            dropped = self.db.execute("DELETE FROM blocks WHERE t0 < ? AND t1 < ?", (cutoff, cutoff)).rowcount
            self.db.execute("DELETE FROM events WHERE t < ?", (cutoff,))
            self.db.execute("UPDATE trips SET raw = 0 WHERE raw = 1 AND open = 0 AND started < ?", (cutoff,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return dropped

    def clear(self):
        """Deletes everything (the files too) and starts an empty database."""
        self.close()
        self._remove_files(self.path)
        self._remove_files(self.path + ".damaged")
        self.recovered = None
        self._open()

    def stats(self):
        trips = self.db.execute("SELECT count(*) FROM trips").fetchone()[0]
        recordings = self.db.execute("SELECT count(*) FROM recordings").fetchone()[0]
        oldest = self.db.execute("SELECT min(t0) FROM blocks").fetchone()[0]
        recording_bytes = self.recording_bytes()
        return {"usedBytes": max(0, self.used_bytes() - recording_bytes), "fileBytes": self.file_bytes(),
                "recordingBytes": recording_bytes, "trips": trips, "recordings": recordings,
                "keys": len(self.keys), "oldestSample": oldest}


class Queries:
    """Read side, the logger.query commands. Every method returns a JSON-serializable dict."""

    def __init__(self, db):
        self.db = db

    def close(self):
        self.db.close()

    def _key_ids(self, names=None):
        rows = self.db.execute("SELECT id, name FROM keys ORDER BY name").fetchall()
        if names is None:
            return rows
        wanted = set(names)
        return [(key_id, name) for key_id, name in rows if name in wanted]

    # --- trips and recordings -------------------------------------------------------

    def trips(self, start=None, end=None, before=None, limit=50):
        """Trips overlapping [start, end), newest first; before = id for paging (only older ones)."""
        rows, more = self._list("SELECT id, started, ended, open, raw, summary FROM trips", start, end, before, limit)
        return {"trips": [trip_row(row) for row in rows], "more": more}

    def recordings(self, start=None, end=None, before=None, limit=50):
        rows, more = self._list("SELECT id, started, ended, open, reason, label, bytes FROM recordings",
                                start, end, before, limit)
        return {"recordings": [recording_row(row) for row in rows], "more": more}

    def _list(self, sql, start, end, before, limit):
        limit = max(1, min(int(limit), MAX_LIST))
        where, params = [], []
        if start is not None:
            where.append("ended >= ?")
            params.append(int(start))
        if end is not None:
            where.append("started < ?")
            params.append(int(end))
        if before is not None:
            where.append("id < ?")
            params.append(int(before))
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.db.execute(sql + " ORDER BY started DESC, id DESC LIMIT ?", params + [limit + 1]).fetchall()
        return rows[:limit], len(rows) > limit

    def trip(self, trip_id):
        row = self.db.execute("SELECT id, started, ended, open, raw, summary FROM trips WHERE id = ?",
                              (int(trip_id),)).fetchone()
        if row is None:
            raise QueryError("no trip %s" % trip_id)
        return {"trip": trip_row(row)}

    def recording(self, rec_id):
        row = self.db.execute("SELECT id, started, ended, open, reason, label, bytes FROM recordings WHERE id = ?",
                              (int(rec_id),)).fetchone()
        if row is None:
            raise QueryError("no recording %s" % rec_id)
        return recording_row(row)

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

    # --- samples --------------------------------------------------------------------

    def _blocks(self, key_id, start, end, recording):
        """Decoded (times, values) of the blocks of a key overlapping [start, end), in order."""
        if recording is None:
            sql, params = "SELECT t0, data FROM blocks WHERE key = ?", [key_id]
        else:
            sql, params = "SELECT t0, data FROM rblocks WHERE rec = ? AND key = ?", [int(recording), key_id]
        sql += " AND t0 >= ? AND t0 < ? AND t1 >= ? ORDER BY t0"
        for t0, data in self.db.execute(sql, params + [start - MAX_BLOCK_MS, end, start]):
            yield codec.decode(t0, data)

    def _before(self, key_id, start, recording):
        """The value held at start: the last sample before it."""
        if recording is None:
            sql, params = "SELECT t0, data FROM blocks WHERE key = ?", [key_id]
        else:
            sql, params = "SELECT t0, data FROM rblocks WHERE rec = ? AND key = ?", [int(recording), key_id]
        rows = self.db.execute(sql + " AND t0 < ? ORDER BY t0 DESC LIMIT 2", params + [start]).fetchall()
        best = None
        for t0, data in rows:
            times, values = codec.decode(t0, data)
            for t, value in zip(times, values):
                if t < start and (best is None or t >= best[0]):
                    best = (t, value)
        return best[1] if best else None

    def keys(self, recording=None):
        result = []
        table, extra = ("blocks", "") if recording is None else ("rblocks", " AND rec = %d" % int(recording))
        for key_id, name in self._key_ids():
            first = self.db.execute("SELECT min(t0) FROM %s WHERE key = ?%s" % (table, extra), (key_id,)).fetchone()[0]
            if first is None:
                continue
            t0, data = self.db.execute("SELECT t0, data FROM %s WHERE key = ?%s ORDER BY t0 DESC LIMIT 1"
                                       % (table, extra), (key_id,)).fetchone()
            times, values = codec.decode(t0, data)
            last = max(range(len(times)), key=lambda i: times[i])
            result.append({"key": name, "first": first, "last": times[last], "value": values[last]})
        return {"keys": result}

    def samples(self, start, end, keys=None, points=300, limit=5000, recording=None):
        """Series per key in [start, end) of the log or of a recording.
        points > 0: downsampled into that many equal time buckets: t = bucket start, v = average, min, max of the
        samples in it; empty buckets are left out. Buckets of SUMMARY_BUCKET_MS or more come from the block
        summaries (a block counts in the bucket of its first sample).
        points = 0: the raw samples, up to limit values in all (more = true if cut).
        before = the value held at start (last sample before it). Keys without data there are left out."""
        points = int(points)
        if points < 0 or points > MAX_POINTS:
            raise QueryError("points must be 0..%d" % MAX_POINTS)
        key_ids = self._key_ids(keys)
        series, more = {}, False
        if points:
            if points * len(key_ids) > MAX_VALUES:
                raise QueryError("too many values (keys x points > %d), ask for fewer keys or points" % MAX_VALUES)
            bucket = max(1, math.ceil((end - start) / points))
            for key_id, name in key_ids:
                if bucket >= SUMMARY_BUCKET_MS:
                    buckets = self._summary_buckets(key_id, start, end, bucket, recording)
                else:
                    buckets = {}
                    for times, values in self._blocks(key_id, start, end, recording):
                        for t, value in zip(times, values):
                            if start <= t < end:
                                entry = buckets.get((t - start) // bucket)
                                if entry is None:
                                    buckets[(t - start) // bucket] = [value, 1, value, value]
                                else:
                                    entry[0] += value
                                    entry[1] += 1
                                    entry[2] = min(entry[2], value)
                                    entry[3] = max(entry[3], value)
                order = sorted(buckets)
                before = self._before(key_id, start, recording)
                if not order and before is None:
                    continue  # no data of this key here
                series[name] = {"t": [start + b * bucket for b in order],
                                "v": [round(buckets[b][0] / buckets[b][1], 4) for b in order],
                                "min": [buckets[b][2] for b in order],
                                "max": [buckets[b][3] for b in order],
                                "before": before}
            return {"start": start, "end": end, "points": points, "bucket": bucket, "series": series}
        budget = max(1, min(int(limit), MAX_VALUES))
        for key_id, name in key_ids:
            times_out, values_out = [], []
            for times, values in self._blocks(key_id, start, end, recording):
                for t, value in zip(times, values):
                    if start <= t < end:
                        if len(times_out) >= budget:
                            more = True
                            break
                        times_out.append(t)
                        values_out.append(value)
                if more:
                    break
            before = self._before(key_id, start, recording)
            if times_out or before is not None:
                series[name] = {"t": times_out, "v": values_out, "before": before}
            budget -= len(times_out)
            if budget <= 0:
                more = more or key_id != key_ids[-1][0]
                break
        return {"start": start, "end": end, "points": 0, "series": series, "more": more}

    def _summary_buckets(self, key_id, start, end, bucket, recording):
        if recording is None:
            sql, params = "FROM blocks WHERE key = ?", [key_id]
        else:
            sql, params = "FROM rblocks WHERE rec = ? AND key = ?", [int(recording), key_id]
        rows = self.db.execute("SELECT (max(t0, ?) - ?) / ?, sum(vsum), sum(n), min(vmin), max(vmax) " + sql
                               + " AND t0 >= ? AND t0 < ? AND t1 >= ? GROUP BY 1",
                               [start, start, bucket] + params + [start - MAX_BLOCK_MS, end, start]).fetchall()
        return {b: [total, count, low, high] for b, total, count, low, high in rows if count}

    def events(self, start, end, topic=None, limit=1000):
        """Events in [start, end), oldest first; topic = exact topic or prefix ending in ".*"."""
        limit = max(1, min(int(limit), MAX_EVENTS))
        sql, params = "SELECT t, topic, data FROM events WHERE t >= ? AND t < ?", [start, end]
        if topic:
            if topic.endswith(".*"):
                sql += " AND substr(topic, 1, ?) = ?"
                params += [len(topic) - 1, topic[:-1]]
            else:
                sql += " AND topic = ?"
                params.append(topic)
        rows = self.db.execute(sql + " ORDER BY t, id LIMIT ?", params + [limit + 1]).fetchall()
        return {"start": start, "end": end, "events": [{"t": t, "topic": tp, "data": json.loads(data)}
                                                       for t, tp, data in rows[:limit]],
                "more": len(rows) > limit}
