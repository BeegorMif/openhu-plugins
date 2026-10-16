# Vehicle data logger (`org.openhu.logger`)

Records vehicle data, some OpenHU state and values of the head unit on the device, detects trips and answers queries
of other plugins. It **only logs**: showing the data (trip lists, charts), exporting it or forwarding it (MQTT, Home
Assistant, …) is the job of other plugins, which use the interface below. Everything stays on the device, nothing
needs the internet.

Logging is **off** after installing; the plugin page switches it on and shows the storage use.

## What is logged

| Group (switch) | Source | Keys |
|---|---|---|
| Vehicle data (on) | every `vehicle.*` topic, e.g. from the CAN plugin (`org.openhu.can`) | `vehicle.speed.kmh`, `vehicle.engine.rpm`, … (every number, boolean and short text field) |
| Android Auto and call state (on) | `projection.state`, `projection.transport`, `phone.status`, `media.status` | `projection.state.connected`, `phone.status.callState`, `media.status.source`, … — no numbers, names, titles or destinations |
| Head unit (on) | `/sys/class/thermal`, load, `/proc/meminfo`, free space of the data partition | `hu.cpuTemp`, `hu.load`, `hu.memFreeMB`, `hu.diskFreeMB` |
| Position (off) | `vehicle.position`, if a source publishes it (OpenHU has none today) | `vehicle.position.lat`, … |

A key is `<topic>.<field>` (one level of nested objects: `<topic>.<field>.<sub>`). Without the CAN plugin only the
OpenHU and head unit values are logged, and there are no trips; the page says so.

- **Numbers** are written at the rate of their key. Default: the interval (5 s), sample-and-hold: at most one sample
  per period, only if the value changed, with the time the value arrived. A key or pattern can have its own rate
  (`rates`): seconds (0.1–3600) or `"update"`, every update on the bus, changed or not. The page sets the rate of
  `vehicle.*` (interval, 1 s, 0.1 s, every update).
- **Booleans** are written right away when they change (as 0/1), plus an event.
- **Texts** (gear `drive`, call state, …) are events.

The CAN plugin publishes a topic only when one of its fields changed, and at most every 0.1 s (`PUBLISH_INTERVAL`
in its `bin/can.py`): "every update" is therefore at most 10 Hz per topic today, even if the CAN frame comes at
100 Hz. Higher rates need a change in the CAN plugin.

## Trips

- **Start**: the car moves (`vehicle.speed.kmh` > 0.5) or the engine is switched on (`vehicle.engine.running`,
  `vehicle.engine.on` or `vehicle.engine.rpm` > 0).
- **End**: the engine stays off for 60 s (`engineOffSeconds`; start-stop systems switch it off at traffic lights), at
  the time it was switched off; or the car stands still for 10 minutes (`stopMinutes`), at the time it stopped, also
  while the engine idles. Cars that report only the engine end their trips with the engine. Switching logging off
  ends a trip.
- **Power cut / restart**: the open trip is written every 30 s. At the next start a trip whose last activity is
  less than `stopMinutes` ago goes on (restart while driving), an older one is closed at its last activity
  (`endReason: "power"`).
- **Summary**: `start`, `end`, `duration` (ms, without the final standstill), `movingTime`, `distance` (km, from
  `vehicle.odometer.km` if the car reports it, otherwise speed over time; `distanceSource`: `odometer`/`speed`),
  `maxSpeed`, `avgSpeed`, `aaTime` (Android Auto connected), `fuel` (litres, drop of `vehicle.fuel.liters` from start
  to end) and `consumption` (l/100 km) if the car reports the tank content, `startReason`, `endReason` (`engine`,
  `standstill`, `power`, `off`), `os`, `loggerVersion`, `raw` (false once its samples were dropped for space).

## High-rate recordings

In addition to the log: recordings take **every update** of their keys (default `vehicle.*`) and are stored
separately, with their own quota (`recording.limitMB`, default 256 MB, the oldest recording goes first), so they never
push the normal log out.

- by hand: `logger.command {cmd: "record", action: "start", seconds, label}` / `{action: "stop"}`, or the button on
  the page (ends after `recording.maxSeconds`, default 600)
- by a trigger: `recording.triggers`, e.g. `[{"key": "vehicle.engine.rpm", "above": 3000},
  {"key": "vehicle.engine.throttle", "above": 90}]` (`above`, `below`, `equals`). The recording starts with the
  `preSeconds` (5) before the trigger and goes on `postSeconds` (10) after the last trigger let go.

## Storage

SQLite in `OPENHU_DATA_DIR/logger.db` (`~/.openhu/plugin-data/org.openhu.logger`, on OpenHU OS the data partition,
kept on plugin updates). WAL with `synchronous=NORMAL`; rows are written in batches every 30 s (`flushSeconds`), so a
power cut loses at most that much, never the database. A damaged database is put aside as `logger.db.damaged` and a
new one started (the page says so).

Samples are stored in **blocks per key** (one row per key and batch, at most 4096 values or 120 s): timestamps as
deltas, values as deltas of integers when they are decimals (CAN signals are raw integers times a scale such as
0.01; exact to 12 significant digits, so `50.370000000000005` comes back as `50.37`), otherwise byte-shuffled
float64, all compressed with zlib (`bin/codec.py`, standard library only). Each block also keeps count, min, max and
sum for queries over long ranges.

Measured with synthetic CAN data, 20 signals of a drive with sensor noise (`tests/test_storage_rate.py`, all logged
on every update, 30 s batches):

| Rate | Storage | Per value | 1 GB lasts |
|---|---|---|---|
| 20 signals at 10 Hz | 0.94 MB/h | 1.4 bytes | ~1090 hours of driving |
| 20 signals at 100 Hz | 6.8 MB/h | 1.0 bytes | ~150 hours of driving |
| 20 signals updated at 10 Hz, logged at the default 5 s | 0.21 MB/h | | ~4900 hours of driving |

The size depends on the noise of the signals: a smooth signal costs less, a noisy one more. Python on a Raspberry Pi
is roughly ten times slower than the PC of the measurement (0.1 % / 0.7 % of one core there). At low rates the
SQLite row of each block costs more than its few values; that is why the 5 s default is not 50 times smaller.

**Limits**: `limitMB` (default 1024) for the log; when it is reached the samples and events of the oldest trips go
first, their summaries stay (up to 100 000 trips). `maxAgeDays` (0 = off) drops older samples. Recordings have their
own `recording.limitMB`. A lowered limit gives the space back to the file system. "Delete all data" removes the
database files.

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

### Topics

| Topic | Data |
|---|---|
| `logger.live` | published every interval: `t`, `enabled`, `trip` (summary of the open trip or `null`), `recording` (the open recording or `null`), `values` (latest value of every logged key, numbers, booleans and texts) |
| `logger.state` | published on changes and every 30 s, for the page: the settings (`enabled`, `groups`, `interval`, `rates`, `limitMB`, `maxAgeDays`, `stopMinutes`, `engineOffSeconds`, `flushSeconds`, `recording`), `usage` (`usedBytes` of the log, `limitBytes`, `recordingBytes`, `recordingLimitBytes`, `fileBytes`, `trips`, `recordings`, `keys`, `oldestSample`), `trip`, `recording`, `vehicleData` (a `vehicle.*` topic arrived), `error`, `recovered` |
| `logger.trip` | one-shot: `event` (`start`, `end`), `trip` (summary) |
| `logger.recording` | one-shot: `event` (`start`, `end`), `recording` (`id`, `start`, `end`, `open`, `reason`, `label`) |
| `logger.result` | one-shot: the answer to `logger.query` / `logger.command` with an `id`: `id`, `cmd`, `ok`, `error` or the result |

### `logger.query` (`cmd`)

| `cmd` | Params | Result |
|---|---|---|
| `trips` | `start`, `end` (optional, trips overlapping the range), `before` (trip id, for paging), `limit` (default 50, max 1000) | `trips` (newest first, summaries as above with `id`, `open`, `raw`), `more` |
| `trip` | `trip` (id) | `trip` |
| `recordings` | like `trips` | `recordings` (`id`, `start`, `end`, `open`, `reason` (`manual`, `trigger`), `label`, `bytes`), `more` |
| `keys` | `recording` (optional) | `keys`: `[{key, first, last, value}]` – logged keys with their first and last sample and the last value |
| `samples` | range: `start` + `end` (default now), or `trip` or `recording` (narrowed by `start`/`end` if given); `keys` (list, default all); `points` (default 300, max 2000; 0 = raw); `limit` (raw only, default 5000, max 50 000 values in all) | `start`, `end`, `series`: `{key: {t: [...], v: [...], before}}`. With `points`: equal time buckets (`bucket` ms), `t` = bucket start, `v` = average, `min`, `max` of the samples in it, empty buckets left out; buckets of 8 minutes or more come from the block summaries (a block counts in the bucket of its first sample). Raw: every sample, `more` = cut at `limit`. `before` = the value held at `start` (sample-and-hold: draw a step from it). Keys without data in the range are left out. keys × points at most 50 000 |
| `events` | range as for `samples`; `topic` (exact, or a prefix like `vehicle.*`); `limit` (default 1000, max 5000) | `events`: `[{t, topic, data}]` oldest first (gear, Android Auto, call state, `logger.trip`, `logger.recording`), `more` |
| `live` | – | like `logger.live` |
| `status` | – | like `logger.state` |

### `logger.command` (`cmd`)

Answered on `logger.result` if an `id` is given.

| `cmd` | Params | |
|---|---|---|
| `set` | `key`, `value` | a setting: `enabled`, `interval` (1–60), `limitMB` (50–1048576), `maxAgeDays` (0–36500), `stopMinutes` (1–240), `engineOffSeconds` (0–3600), `flushSeconds` (5–600), `groups.vehicle` / `groups.openhu` / `groups.health` / `groups.position` (bool), `rates` (the whole object) or `rates.<key or pattern>` (seconds 0.1–3600, `"update"`, or `null` to remove), `recording.keys` (list of keys/patterns), `recording.triggers`, `recording.limitMB`, `recording.preSeconds`, `recording.postSeconds`, `recording.maxSeconds`. Saved in `config.json` |
| `record` | `action` (`start`, `stop`), `seconds`, `label` | a high-rate recording by hand; result `recording` |
| `deleteRecording` | `recording` (id) | deletes a recording (not the running one) |
| `clear` | – | deletes all data (log, trips, recordings) |

Patterns (in `rates`, `recording.keys`): an exact key, `prefix.*`, or `*`; the most specific one wins.

## Testing

```
python3 -m unittest discover -s tests       # in this folder; test_integration needs python3-websockets
python3 -m unittest -v tests.test_storage_rate   # prints the storage numbers above
```

Without a car: `tools/fake-drive.py` publishes a simulated drive (engine, speed, rpm, throttle, outside temperature)
at 10 Hz for 3 minutes, then brakes to 0 (`--stop 11` stands still 11 minutes with the engine running, so the trip
ends by standstill; afterwards the engine goes off). On the head unit: `cd ~/.openhu/plugins/org.openhu.logger &&
PYTHONPATH=lib python3 tools/fake-drive.py`. Single values also work with `openhu-cli api bus.publish
'{"topic": "vehicle.speed", "data": {"kmh": 50}}'`, and queries with `openhu-cli watch logger.result` in a second
shell plus `openhu-cli api bus.emit '{"topic": "logger.query", "data": {"id": "cli:1", "cmd": "trips"}}'`.
