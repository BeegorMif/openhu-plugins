"""What the logger records: bus topics -> keys, rates, events, trips, high-rate recordings, write batches (no I/O of
its own besides Store; times in ms since 1970).

Keys are "<topic>.<field>" (one level of nested objects: "<topic>.<field>.<sub>"), e.g. "vehicle.speed.kmh".
- numbers: written at the rate of their key (config "rates", default "interval"):
    seconds (0.1 ... 3600)  sample-and-hold: at most one sample per period, only if the value changed
    "update"                every update that arrives on the bus, changed or not
- booleans: a sample (0/1) right away when they change, and an event
- texts (gear "drive", call state, ...): an event when they change
Groups (switches in the config): vehicle (vehicle.* without vehicle.position), position (vehicle.position),
openhu (Android Auto connected/transport, call state, media source; no numbers, names or titles) and health
(hu.*: values of the head unit itself, read by the process).

High-rate recordings (config "recording") take every update of their keys, separately from the log and with their
own quota: started by hand (start_recording) or while a trigger holds (e.g. rpm above 3000), with the
preSeconds before the trigger and postSeconds after it.
"""

import collections
import math

from logstore import public_trip
from trips import Trips

# topic -> fields logged (the openhu group; nothing personal)
OPENHU_TOPICS = {
    "projection.state": ("connected",),
    "projection.transport": ("transport",),
    "phone.status": ("callState",),
    "media.status": ("source", "state"),
}
MAX_TEXT = 64
# values kept in memory while the database cannot be written (disk full); the oldest go first
MAX_BUFFER = 500_000
UPDATE = "update"


def group_of(topic):
    if topic == "vehicle.position":
        return "position"
    if topic.startswith("vehicle."):
        return "vehicle"
    if topic in OPENHU_TOPICS:
        return "openhu"
    if topic.startswith("hu."):
        return "health"
    return None


def flatten(topic, data):
    """[(key, value)] of the loggable fields: numbers, booleans, short texts; one level of nested objects."""
    fields = []

    def add(name, value):
        if isinstance(value, bool) or (isinstance(value, str) and len(value) <= MAX_TEXT):
            fields.append((name, value))
        elif isinstance(value, (int, float)) and math.isfinite(value):
            fields.append((name, value))

    allowed = OPENHU_TOPICS.get(topic)
    for field, value in (data or {}).items():
        if allowed is not None and field not in allowed:
            continue
        if isinstance(value, dict) and allowed is None:
            for sub, inner in value.items():
                if not isinstance(inner, dict):
                    add("%s.%s.%s" % (topic, field, sub), inner)
        else:
            add("%s.%s" % (topic, field), value)
    return fields


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def pattern_matches(pattern, key):
    return pattern == "*" or pattern == key or (pattern.endswith(".*") and key.startswith(pattern[:-1]))


def best_match(patterns, key):
    """The most specific pattern for key: exact, then the longest prefix "a.b.*", then "*"; None if none."""
    best = None
    for pattern in patterns:
        if pattern_matches(pattern, key):
            rank = (2, 0) if pattern == key else (1, len(pattern)) if pattern != "*" else (0, 0)
            if best is None or rank > best[0]:
                best = (rank, pattern)
    return best[1] if best else None


def valid_rate(value):
    return value == UPDATE or (is_number(value) and 0.1 <= value <= 3600)


def trigger_holds(trigger, value):
    if "above" in trigger and not value > trigger["above"]:
        return False
    if "below" in trigger and not value < trigger["below"]:
        return False
    if "equals" in trigger and value != trigger["equals"]:
        return False
    return any(condition in trigger for condition in ("above", "below", "equals"))


class Buffers:
    """Samples per key waiting for the next write: {key: ([times], [values])}"""

    def __init__(self):
        self.series = {}
        self.count = 0

    def add(self, key, t, value):
        times, values = self.series.setdefault(key, ([], []))
        times.append(t)
        values.append(float(value))
        self.count += 1

    def take(self):
        series, self.series, self.count = self.series, {}, 0
        return series

    def put_back(self, series):
        """After a failed write: the rows go back in front, the oldest beyond MAX_BUFFER are dropped."""
        for key, (times, values) in series.items():
            newer = self.series.get(key, ([], []))
            self.series[key] = (times + newer[0], values + newer[1])
        self.count = sum(len(times) for times, _ in self.series.values())
        while self.count > MAX_BUFFER:
            key = max(self.series, key=lambda k: len(self.series[k][0]))
            times, values = self.series[key]
            cut = max(1, len(times) // 2)
            self.series[key] = (times[cut:], values[cut:])
            self.count -= cut


class Recorder:
    def __init__(self, store, config, info=None):
        self.store = store
        self.config = config
        self.info = dict(info or {})
        self.trips = Trips()
        self.values = {}            # key -> latest value
        self.written = {}           # key -> value of its last sample in the log
        self.due = {}               # key -> time of its next sample (fixed rates)
        self.changed_at = {}        # key -> time its value last changed (the time of its sample)
        self.last_sample = {}       # key -> time of its last sample
        self.rate_cache = {}
        self.log = Buffers()        # samples of the log not yet written
        self.events = []            # (t, topic, data)
        self.pending_trips = []     # ended trips not yet written
        self.recording = None       # the open recording (dict) or None
        self.pending_recordings = []
        self.rec = Buffers()        # samples of recordings not yet written ((recording id, key) as key)
        self.pre = collections.deque()  # (t, key, value) of the last preSeconds, for a triggered recording
        self.active_triggers = set()
        self.announcements = []     # (topic, data) for the bus: logger.trip, logger.recording
        self.vehicle_data = False   # a vehicle.* topic arrived (the CAN plugin or another source runs)
        self.error = ""             # last write error, "" after a successful write
        self.apply_config()

    def apply_config(self):
        self.trips.stop_ms = int(self.config["stopMinutes"] * 60_000)
        self.trips.engine_off_ms = int(self.config["engineOffSeconds"] * 1000)
        self.rate_cache.clear()
        self.due.clear()

    def enabled(self, group):
        return bool(self.config["enabled"]) and bool(self.config["groups"].get(group))

    def rate_of(self, key):
        """Seconds between samples of key, or UPDATE."""
        rate = self.rate_cache.get(key)
        if rate is None:
            rates = self.config.get("rates") or {}
            pattern = best_match(rates, key)
            rate = rates[pattern] if pattern is not None and valid_rate(rates[pattern]) else self.config["interval"]
            self.rate_cache[key] = rate
        return rate

    def fastest_rate(self):
        """Seconds between ticks: the shortest fixed rate in use."""
        rates = [rate for rate in (self.config.get("rates") or {}).values() if is_number(rate) and valid_rate(rate)]
        return min([float(self.config["interval"])] + rates)

    def recorded(self, key):
        return best_match(self.config["recording"].get("keys") or [], key) is not None

    # --- input ----------------------------------------------------------------------

    def on_topic(self, topic, data, t):
        group = group_of(topic)
        if group in ("vehicle", "position"):
            self.vehicle_data = True
        if group is None or not self.enabled(group):
            return
        changed = {}
        for key, value in flatten(topic, data):
            known = key in self.values
            old = self.values.get(key)
            self.values[key] = value
            if not known or old != value:
                self.changed_at[key] = t
            if isinstance(value, bool):
                if not known or old != value or not isinstance(old, bool):
                    self._sample(t, key, value)
                    changed[key[len(topic) + 1:]] = value
            elif isinstance(value, str):
                if not known or old != value:
                    changed[key[len(topic) + 1:]] = value
            elif self.rate_of(key) == UPDATE:
                self._sample(t, key, value)
            if not isinstance(value, str):
                self._record_value(t, key, value)
            self._trip_changes(self.trips.update(t, key, value))
        if changed:
            self._event(t, topic, changed)

    def tick(self, t, health=None):
        """Every fastest_rate(): health values (if given), samples of the numbers whose period is due, trip end rules,
        end of recordings."""
        if health and self.enabled("health"):
            self.values.update(health)
        for key, value in self.values.items():
            if not is_number(value):
                continue
            rate = self.rate_of(key)
            if rate == UPDATE or t < self.due.get(key, t):
                continue
            # the next period starts now; a tick a few ms early still counts (timer jitter)
            self.due[key] = t + int(rate * 1000) - 20
            if self.written.get(key) != value:
                # at the time the value arrived (it is held since then), not the time of the tick
                self._sample(max(self.changed_at.get(key, t), self.last_sample.get(key, 0)), key, value)
        self._trip_changes(self.trips.tick(t))
        self._recording_tick(t)

    def _sample(self, t, key, value):
        self.log.add(key, t, value)
        self.written[key] = value
        self.last_sample[key] = t

    def _event(self, t, topic, data):
        self.events.append((t, topic, data))

    def _trip_changes(self, changes):
        for kind, trip in changes:
            if kind == "start":
                trip.update(self.info)
                try:
                    self.store.write(trips=[trip])  # gives it its id
                except Exception as error:  # written with the next flush
                    self.error = str(error)
                self._event(trip["start"], "logger.trip", {"event": "start", "trip": trip.get("id")})
            else:
                self._event(trip["end"], "logger.trip", {"event": "end", "trip": trip.get("id"),
                                                         "reason": trip["endReason"]})
                self.pending_trips.append(trip)
                self._try_flush()
            self.announcements.append(("logger.trip", {"event": kind, "trip": public_trip(trip)}))

    # --- recordings -----------------------------------------------------------------

    def _record_value(self, t, key, value):
        settings = self.config["recording"]
        if not self.recorded(key):
            return
        if self.recording is not None:
            self.rec.add((self.recording["id"], key), t, value)
        elif settings.get("triggers") and settings.get("preSeconds", 0) > 0:
            self.pre.append((t, key, float(value)))
            horizon = t - settings["preSeconds"] * 1000
            while self.pre and self.pre[0][0] < horizon:
                self.pre.popleft()
        for index, trigger in enumerate(settings.get("triggers") or []):
            if trigger.get("key") != key or isinstance(value, str):
                continue
            if trigger_holds(trigger, value):
                if not self.active_triggers:
                    label = "%s %s" % (key, " ".join("%s %s" % (condition, trigger[condition])
                                                     for condition in ("above", "below", "equals")
                                                     if condition in trigger))
                    if self.recording is None:
                        self.start_recording(t, "trigger", label)
                self.active_triggers.add(index)
                if self.recording is not None and self.recording["reason"] == "trigger":
                    self.recording["holdUntil"] = t + settings.get("postSeconds", 10) * 1000
            else:
                self.active_triggers.discard(index)

    def start_recording(self, t, reason, label="", seconds=None):
        """reason "manual" (ends after seconds or with stop_recording) or "trigger". Returns the recording."""
        if self.recording is not None:
            return self.recording
        settings = self.config["recording"]
        start = self.pre[0][0] if self.pre and reason == "trigger" else t
        limit = min(seconds or settings.get("maxSeconds", 600), settings.get("maxSeconds", 600))
        self.recording = {"id": None, "start": start, "end": t, "open": True, "reason": reason, "label": label,
                          "until": t + int(limit * 1000), "holdUntil": t}
        try:
            self.store.write(recordings=[self.recording])
        except Exception as error:
            self.error = str(error)
            self.recording = None
            return None
        if reason == "trigger":
            for pre_t, key, value in self.pre:
                self.rec.add((self.recording["id"], key), pre_t, value)
        self.pre.clear()
        self._event(t, "logger.recording", {"event": "start", "recording": self.recording["id"], "reason": reason,
                                            "label": label})
        self.announcements.append(("logger.recording", {"event": "start", "recording": self.public_recording()}))
        return self.recording

    def stop_recording(self, t, why="manual"):
        recording = self.recording
        if recording is None:
            return None
        recording.update(end=max(recording["start"], t), open=False, endReason=why)
        self.recording = None
        self.active_triggers.clear()
        self.pending_recordings.append(recording)
        self._event(t, "logger.recording", {"event": "end", "recording": recording["id"], "reason": why})
        self._try_flush()
        self.announcements.append(("logger.recording", {"event": "end", "recording": self.public_recording(recording)}))
        return recording

    def _recording_tick(self, t):
        recording = self.recording
        if recording is None:
            return
        recording["end"] = t
        limit = self.config["recording"].get("limitMB", 256) * 1024 * 1024
        if t >= recording["until"]:
            self.stop_recording(t, "time")
        elif recording["reason"] == "trigger" and not self.active_triggers and t >= recording["holdUntil"]:
            self.stop_recording(t, "trigger")
        elif self.store.recording_bytes(recording["id"]) + self.rec.count * 2 > limit:
            self.stop_recording(t, "quota")

    def public_recording(self, recording=None):
        recording = recording if recording is not None else self.recording
        if recording is None:
            return None
        return {key: recording[key] for key in ("id", "start", "end", "open", "reason", "label")}

    # --- trips ----------------------------------------------------------------------

    def restore(self, now):
        """Closes or resumes the trips left open in the database (see Trips.restore), closes open recordings."""
        self.store.close_recordings()
        open_trips = self.store.open_trips()
        for index, trip in enumerate(open_trips):
            if index < len(open_trips) - 1:
                trip.update(open=False, end=max(trip["start"], trip.get("last") or trip["end"]), endReason="power")
                self.store.write(trips=[trip])
            else:
                for kind, closed in self.trips.restore(trip, now):
                    self.store.write(trips=[closed])
                    self.announcements.append(("logger.trip", {"event": kind, "trip": public_trip(closed)}))

    def end_trip(self, t, reason):
        if self.trips.trip is not None:
            self._trip_changes([self.trips.end(t, reason)])

    @property
    def trip(self):
        return public_trip(self.trips.trip)

    def reset(self):
        """After deleting all data: nothing open, the next values are written again."""
        self.trips.trip = None
        self.recording = None
        self.active_triggers.clear()
        self.pre.clear()
        self.written.clear()
        self.due.clear()
        self.log.take()
        self.rec.take()
        self.events.clear()
        self.pending_trips.clear()
        self.pending_recordings.clear()

    def disable(self, t):
        """Logging switched off: the trip and a recording end, what is buffered is written."""
        self.end_trip(t, "off")
        self.stop_recording(t, "off")
        self._try_flush()
        self.values.clear()
        self.written.clear()
        self.due.clear()
        self.pre.clear()

    # --- writing --------------------------------------------------------------------

    def _try_flush(self):
        try:
            self.flush()
        except Exception as error:
            self.error = str(error)

    def flush(self):
        """Writes the buffered samples, events, ended trips and recordings and the summary of the open trip in one
        transaction. On an error (disk full) the rows stay buffered (bounded) and the error is raised."""
        trips = list(self.pending_trips)
        if self.trips.trip is not None:
            trips.append(self.trips.trip)
        recordings = list(self.pending_recordings)
        if self.recording is not None:
            recordings.append(self.recording)
        if not (self.log.count or self.rec.count or self.events or trips or recordings):
            return
        series, rseries, events = self.log.take(), self.rec.take(), self.events
        self.events = []
        try:
            self.store.write(series, events, trips, recordings, rseries)
        except Exception as error:
            self.error = str(error)
            self.log.put_back(series)
            self.rec.put_back(rseries)
            self.events = (events + self.events)[-MAX_BUFFER:]
            raise
        self.error = ""
        self.pending_trips = []
        self.pending_recordings = []

    def live(self, t):
        return {"t": t, "enabled": bool(self.config["enabled"]), "trip": self.trip,
                "recording": self.public_recording(), "values": dict(self.values)}
