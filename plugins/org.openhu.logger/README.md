# Vehicle data logger (`org.openhu.logger`)

Records vehicle data, some OpenHU state and values of the head unit on the device, detects trips and answers queries
of other plugins. It **only logs**: showing the data (trip lists, charts), exporting it or forwarding it (MQTT, Home
Assistant, …) is the job of other plugins, which use the interface below. Everything stays on the device, nothing
needs the internet. The database is plain SQLite, readable with any SQLite tool.

Logging is **off** after installing; the plugin page switches it on and shows the storage use.

## What is logged

Nothing is fixed per car: every field a source publishes becomes a **signal**, created when it first appears.

| Group (switch) | Source | Signals |
|---|---|---|
| Vehicle data (on) | every `vehicle.*` topic, e.g. from the CAN plugin (`org.openhu.can`) | `<topic>.<field>`: `vehicle.speed.kmh`, `vehicle.engine.rpm`, `vehicle.gear.gear`, … (numbers, booleans, short texts; one level of nested objects: `<topic>.<field>.<sub>`) |
| Android Auto and call state (on) | `projection.state`, `projection.transport`, `phone.status`, `media.status` | `androidauto.connected`, `androidauto.transport`, `phone.call_state`, `media.source`, `media.state` — no numbers, names, titles or destinations |
| Head unit (on) | read by the process every *n* seconds (page: "Head unit values every (seconds)", `interval`, default 5) | `headunit.cpu_temp_c` (°C, hottest thermal zone), `headunit.cpu_load` (1 min average), `headunit.memory_free_mb`, `headunit.disk_free_mb` (data partition) |
| Position (off) | `vehicle.position`, if a source publishes it (OpenHU has none today) | `vehicle.position.lat`, … |

The OpenHU and head unit signals have fixed units (`°C`, `MB`) in the `signal` table. Vehicle signals get their unit
from their source if it publishes it on the topic `signals.info` (retained; other fields are ignored):

```json
{"source": "org.openhu.can", "signals": {"vehicle.speed.kmh": {"unit": "km/h"}}}
```

The CAN plugin does not do that yet (its profiles have no units, follow-up in #22); until then the source of a
vehicle signal is its topic and its unit is empty. Without the CAN plugin only the OpenHU and
head unit values are logged and there are no trips; the page says so.

**Only changes are written.**
- Numbers at the rate of their signal (`rates`, default `{"vehicle.*": 5}`; the page sets the one of `vehicle.*`:
  every *n* seconds, every 0.*n* seconds or every change): at most one sample per period, only if the value
  changed, with the time the value arrived (sample-and-hold: a value holds until the next sample). `"update"` (on
  the page "every change") writes every change as it arrives. Signals without a rate are written on every change.
- Booleans (stored as 0/1) and texts (gear `drive`, call state) right away when they change.

The CAN plugin publishes a topic only when one of its fields changed, and at most every 0.1 s (`PUBLISH_INTERVAL`
in its `bin/can.py`): "every change" is at most 10 Hz per topic today, even if the CAN frame comes at 100 Hz (#22).

Internally the process checks the trip rules and publishes `logger.live` every second.

## Trips

- **Start**: the car moves (`vehicle.speed.kmh` > 0.5) or the engine is switched on (`vehicle.engine.running`,
  `vehicle.engine.on` or `vehicle.engine.rpm` > 0).
- **End**: the engine stays off for 60 s (`engineOffSeconds`; start-stop systems switch it off at traffic lights), at
  the time it was switched off; or the car stands still for 10 minutes (`stopMinutes`), at the time it stopped, also
  while the engine idles. Cars that report only the engine end their trips with the engine. Switching logging off
  ends a trip. Duration and Android Auto time are those at the end time, not at the moment the rule fired.
- **Power cut / restart**: the open trip is written every 30 s. At the next start a trip whose last activity is
  less than `stopMinutes` ago goes on (restart while driving), an older one is closed at its last activity
  (`endReason: "power"`).
- **Summary** (columns of `trip`, the rest in its `summary` JSON): `start`, `end`, `duration` (ms; column
  `duration_s`), `movingTime`, `distance` (km, from `vehicle.odometer.km` if the car reports it, otherwise speed over
  time; `distanceSource`: `odometer`/`speed`), `maxSpeed`, `avgSpeed`, `aaTime` (Android Auto connected; column
  `aa_time_s`), `fuel` (litres, drop of `vehicle.fuel.liters` from start to end) and `consumption` (l/100 km) if the
  car reports the tank content, `startReason`, `endReason` (`engine`, `standstill`, `power`, `off`), `os`,
  `loggerVersion`, `raw` (false once its samples were dropped for space).

## High-rate recordings

A recording is a **time window** in which its signals (`recording.keys`, default `vehicle.*`) are written on every
change, whatever their rate; the samples are in the `sample` table like all others. Samples inside recording windows
are never dropped for the log's limit; they count against the recordings' own quota (`recording.limitMB`, default
256 MB; when it is full the oldest recording goes, with its samples).

- by hand: `logger.command {cmd: "record", action: "start", seconds, label}` / `{action: "stop"}`, or the button on
  the page (ends after `recording.maxSeconds`, default 600)
- by a trigger: `recording.triggers`, e.g. `[{"key": "vehicle.engine.rpm", "above": 3000},
  {"key": "vehicle.engine.throttle", "above": 90}]` (`above`, `below`, `equals`). The window starts with the
  `preSeconds` (5) before the trigger and goes on `postSeconds` (10) after the last trigger let go.

## Storage

SQLite in `OPENHU_DATA_DIR/logger.db` (`~/.openhu/plugin-data/org.openhu.logger`, on OpenHU OS the data partition,
kept on plugin updates). WAL with `synchronous=NORMAL`; rows are written in batches every 30 s (`flushSeconds`), so a
power cut loses at most that much, never the database. Times are **ms since 1970**.

Every table and column is described by a comment in its `CREATE TABLE` statement (SQLite keeps it: `.schema` in
`sqlite3`, DB Browser for SQLite and other tools show it). The same descriptions:

**`meta`** — facts about this database, one row per key

| Column | |
|---|---|
| `key` | `schema_version` (3), `logger_version` (plugin version that last opened it), `samples` (rows in `sample`, for the size estimate) |
| `value` | the value as text |

**`signal`** — one row per logged signal, created when it first appears

| Column | |
|---|---|
| `id` | referenced by `sample.signal_id` |
| `name` | `<topic>.<field>` of the bus (`vehicle.speed.kmh`) or a fixed name (`androidauto.connected`, `headunit.cpu_load`), unique |
| `unit` | unit of the values (`km/h`, `rpm`, `°C`, `MB`), NULL if not known |
| `source` | where the values come from: a bus topic (`vehicle.speed`), `openhu:<topic>`, `headunit`, or the source named in `signals.info` |
| `first_seen` | time of the first value, ms since the Unix epoch (UTC) |

**`sample`** — values of the signals, written when they change (at most one per signal and rate period);
`WITHOUT ROWID`, primary key `(signal_id, timestamp)`

| Column | |
|---|---|
| `signal_id` | `signal.id` |
| `timestamp` | when the value arrived, ms since the Unix epoch (UTC) |
| `value` | integer, real or text without a declared type, unit see `signal.unit`; booleans as 0/1; the value holds until the next sample of the signal. Integers take 1–6 bytes (0 and 1 none), decimals 8 (rounded to 12 significant digits, so `50.370000000000005` from `raw * 0.01` is `50.37`) |

**`trip`** — one row per trip, from moving or engine on to engine off or standing still (kept when its samples are
dropped)

| Column | |
|---|---|
| `id` | trip number, in the order the trips started |
| `start_time`, `end_time` | ms since the Unix epoch (UTC); `end_time` is the current time while the trip is open |
| `open` | 1 while the trip is running |
| `raw` | 0 once its samples were dropped for space |
| `start_reason` | `speed` or `engine` |
| `end_reason` | `engine` (off), `standstill`, `power` (closed after a power cut), `off` (logging switched off) |
| `distance_km` | km, from the odometer if reported, else speed over time |
| `duration_s` | seconds, without the waiting time of the end rule |
| `max_speed_kmh`, `avg_speed_kmh` | km/h; average = distance / duration |
| `aa_time_s` | seconds Android Auto was connected during the trip |
| `fuel_l` | litres used (drop of the tank content), NULL if not reported |
| `consumption_l_100km` | l/100 km, NULL if not reported |
| `summary` | JSON with the rest (`movingTime` ms, `distanceSource`, `os`, `loggerVersion`, …) |

**`recording`** — high-rate recordings: time windows in which their signals were written on every change; the
samples are in `sample`

| Column | |
|---|---|
| `id` | recording number |
| `start_time`, `end_time` | ms since the Unix epoch (UTC), the start including the time before a trigger |
| `open` | 1 while recording |
| `trigger` | `manual`, or the condition that started it (`vehicle.engine.rpm above 3000`) |
| `label` | name given when started by hand |
| `samples` | samples in the window (for the recordings' quota) |

```sql
SELECT datetime(x.timestamp / 1000, 'unixepoch', 'localtime') AS time, x.value
FROM sample x JOIN signal s ON s.id = x.signal_id
WHERE s.name = 'vehicle.speed.kmh' ORDER BY x.timestamp;
```

A database of schema version 2 (1.1.0, with `signal.description` and no comments) is migrated in place when the
logger starts: the tables are recreated with the current schema and the data copied in one transaction, nothing is
lost (it needs free space for a copy of the data while it runs). A damaged database is put aside as
`logger.db.damaged`; a database of the first version (compressed blocks, tables `keys`/`blocks`) as
`logger.db.old-schema`, and a new one starts (the page says so; "Delete all data" removes them).

Measured with synthetic CAN data, 20 signals of a drive with sensor noise (`tests/test_storage_rate.py`, 30 s
batches). One stored sample takes about **24 bytes** (mostly decimals: 8 bytes value, 6 bytes time, row header and
B-tree):

| Case | Stored samples | Storage | 1 GB lasts |
|---|---|---|---|
| 20 signals updated at 10 Hz, logged every 5 s (default) | 3 per second | 0.25 MB/h | ~4000 hours of driving |
| 20 signals at 10 Hz, every change | 135 per second (of 200 updates) | 11 MB/h | ~93 hours |
| 20 signals at 100 Hz, every change | 1300 per second (of 2000 updates) | 106 MB/h | ~10 hours |

The size depends on how often the values change: a quiet signal costs less, a noisy one more. Python on a Raspberry
Pi is roughly ten times slower than the PC of the measurement (0.1 % / 0.8 % of one core there).

**Limits**: `limitMB` (default 1024) for the log; when it is reached the oldest samples outside recording windows go
first, trip by trip; the trip summaries stay (up to 100 000 trips). `maxAgeDays` (0 = off) drops older samples. A
lowered limit gives the space back to the file system. "Delete all data" removes the database files.

The clock: a head unit without a real-time clock and without time from the internet may have a wrong time; trip
durations and distances use the steps between samples (capped at 60 s), so a jump of the clock does not make a trip
hours long, but the start and end times are those of the clock.

## Interface for other plugins

All over the EventBus (WebSocket API, [openhu/docs/api.md](https://github.com/average-web-dev/openhu/blob/main/docs/api.md)).
Times are **ms since 1970**. Queries and commands are one-shot events (`bus.emit`); the answer is the one-shot
event `logger.result` with the same `id`. Subscribe to `logger.result` **before** sending, and use ids that are
unique for your plugin (e.g. `"org.example.charts:17"`): every subscriber sees every answer.

```python
api.on("logger.result", on_result)                      # openhu.py
await api.emit("logger.query", id="org.example.charts:1", cmd="trips", limit=20)
```

```json
→ {"type":"request","id":5,"method":"bus.emit","params":{"topic":"logger.query",
   "data":{"id":"org.example.charts:1","cmd":"samples","trip":12,"keys":["vehicle.speed.kmh"],"points":300}}}
← {"type":"event","topic":"logger.result","data":{"id":"org.example.charts:1","cmd":"samples","ok":true,
   "start":1760000000000,"end":1760001800001,"points":300,"bucket":6001,
   "series":{"vehicle.speed.kmh":{"t":[...],"v":[...],"min":[...],"max":[...],"before":null}}}}
```

An error: `{"id": ..., "cmd": ..., "ok": false, "error": "start, trip or recording missing"}`.

Samples become queryable with the next batch (up to `flushSeconds`, 30 s); the current values are in `logger.live`.
Plugins may also read the database directly (read-only, WAL allows it while the logger writes).

### Topics

| Topic | Data |
|---|---|
| `logger.live` | every second: `t`, `enabled`, `trip` (summary of the open trip or `null`), `recording` (the open recording or `null`), `values` (latest value of every logged signal) |
| `logger.state` | on changes and every 30 s, for the page: the settings (`enabled`, `groups`, `interval`, `rates`, `limitMB`, `maxAgeDays`, `stopMinutes`, `engineOffSeconds`, `flushSeconds`, `recording`), `usage` (`usedBytes` of the log, `limitBytes`, `recordingBytes`, `recordingLimitBytes`, `fileBytes`, `trips`, `recordings`, `signals`, `samples`, `oldestSample`), `trip`, `recording`, `vehicleData` (a `vehicle.*` topic arrived), `error`, `recovered`, `oldSchema` |
| `logger.trip` | one-shot: `event` (`start`, `end`), `trip` (summary) |
| `logger.recording` | one-shot: `event` (`start`, `end`), `recording` (`id`, `start`, `end`, `open`, `trigger`, `reason` (`manual`, `trigger`), `label`) |
| `logger.result` | one-shot: the answer to `logger.query` / `logger.command` with an `id`: `id`, `cmd`, `ok`, `error` or the result |
| `signals.info` | read by the logger (retained, published by sources): `source`, `signals` `{name: {unit}}` |

### `logger.query` (`cmd`)

| `cmd` | Params | Result |
|---|---|---|
| `trips` | `start`, `end` (optional, trips overlapping the range), `before` (trip id, for paging), `limit` (default 50, max 1000) | `trips` (newest first, summaries as above with `id`, `open`, `raw`), `more` |
| `trip` | `trip` (id) | `trip` |
| `recordings` | like `trips` | `recordings` (`id`, `start`, `end`, `open`, `trigger`, `reason`, `label`, `samples`, `bytes` (estimate)), `more` |
| `signals` (also `keys`) | – | `signals`: `[{name, unit, source, firstSeen, first, last, value}]` – first and last sample still stored, the last value |
| `samples` | range: `start` + `end` (default now), or `trip` or `recording` (narrowed by `start`/`end` if given); `keys` (signal names, default all); `points` (default 300, max 2000; 0 = raw); `limit` (raw only, default 5000, max 50 000 values in all) | `start`, `end`, `series`: `{name: {t: [...], v: [...], before}}`. With `points`: equal time buckets (`bucket` ms), `t` = bucket start, `v` = average, `min`, `max` of the samples in it (texts: the last value, `min`/`max` null), empty buckets left out. Raw: every stored sample, `more` = cut at `limit`. `before` = the value held at `start` (draw a step from it). Signals without data in the range are left out. signals × points at most 50 000 |
| `events` | range as for `samples`; `key` (a signal name or a prefix like `vehicle.*`); `limit` (default 1000, max 5000) | `events`: `[{t, key, value}]` – the text samples (gear, call state, Android Auto transport, …), oldest first, `more`; booleans are in `samples` |
| `live` | – | like `logger.live` |
| `status` | – | like `logger.state` |

### `logger.command` (`cmd`)

Answered on `logger.result` if an `id` is given.

| `cmd` | Params | |
|---|---|---|
| `set` | `key`, `value` | a setting: `enabled`, `interval` (head unit values, 1–60 s), `limitMB` (50–1048576), `maxAgeDays` (0–36500), `stopMinutes` (1–240), `engineOffSeconds` (0–3600), `flushSeconds` (5–600), `groups.vehicle` / `groups.openhu` / `groups.health` / `groups.position` (bool), `rates` (the whole object) or `rates.<signal or pattern>` (seconds 0.1–3600, `"update"` = every change, or `null` to remove), `recording.keys` (list of signals/patterns), `recording.triggers`, `recording.limitMB`, `recording.preSeconds`, `recording.postSeconds`, `recording.maxSeconds`. Saved in `config.json` |
| `record` | `action` (`start`, `stop`), `seconds`, `label` | a high-rate recording by hand; result `recording` |
| `deleteRecording` | `recording` (id) | deletes a recording and the samples in its window (not the running one) |
| `clear` | – | deletes all data |

Patterns (in `rates`, `recording.keys`): an exact signal name, `prefix.*`, or `*`; the most specific one wins.

## Testing

```
python3 -m unittest discover -s tests       # in this folder; test_integration needs python3-websockets
python3 -m unittest -v tests.test_storage_rate   # prints the storage numbers above
```

Without a car: `tools/fake-drive.py` publishes a simulated drive (engine, speed, rpm, throttle, gear, outside
temperature, with units on `signals.info`) at 10 Hz for 3 minutes, then brakes to 0 (`--stop 11` stands still 11
minutes with the engine running, so the trip ends by standstill; afterwards the engine goes off). On the head unit:
`cd ~/.openhu/plugins/org.openhu.logger && PYTHONPATH=lib python3 tools/fake-drive.py`. Single values also work with
`openhu-cli api bus.publish '{"topic": "vehicle.speed", "data": {"kmh": 50}}'`, and queries with
`openhu-cli watch logger.result` in a second shell plus
`openhu-cli api bus.emit '{"topic": "logger.query", "data": {"id": "cli:1", "cmd": "trips"}}'`. The database:
`sqlite3 ~/.openhu/plugin-data/org.openhu.logger/logger.db` (if `sqlite3` is installed; otherwise copy it with scp).
