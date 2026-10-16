"""What the logger records: bus topics -> signals, rates, trips, high-rate recordings, write batches (no I/O of its own
besides Store; times in ms since 1970).

Signals:
- vehicle data: "<topic>.<field>" (one level of nested objects: "<topic>.<field>.<sub>"), e.g. "vehicle.speed.kmh",
  any field a source publishes; the unit from the topic "signals.info" if the source publishes it
- OpenHU state and head unit values: fixed names (OPENHU_SIGNALS, HEADUNIT_SIGNALS)
Values are written only when they change:
- numbers at the rate of their signal (config "rates", e.g. {"vehicle.*": 5}): seconds (0.1 ... 3600), at most one
  sample per period with the time the value arrived, or "update": every change as it arrives; signals without a rate
  on every change
- booleans and texts (gear "drive", call state) right away
Groups (switches in the config): vehicle (vehicle.* without vehicle.position), position (vehicle.position), openhu
(Android Auto, call state, media source; no numbers, names or titles) and health (headunit.*, read by the process).

High-rate recordings (config "recording") are time windows in which their signals are written on every change,
whatever their rate: started by hand (start_recording) or while a trigger holds (e.g. rpm above 3000), with the
preSeconds before the trigger and postSeconds after it.
"""

import collections
import math

from logstore import public_trip
from trips import Trips

# (topic, field) -> (signal, unit): the openhu group, nothing personal
OPENHU_SIGNALS = {
    ("projection.state", "connected"): ("androidauto.connected", None),     # Android Auto connected (0/1)
    ("projection.transport", "transport"): ("androidauto.transport", None),  # usb, wifi
    ("phone.status", "callState"): ("phone.call_state", None),              # idle, incoming, in_call, ...
    ("media.status", "source"): ("media.source", None),                     # androidauto, radio, ...
    ("media.status", "state"): ("media.state", None),                       # playing, paused, stopped
}
OPENHU_TOPICS = sorted({topic for topic, _ in OPENHU_SIGNALS})
# signal -> unit: the health group, read by the process (logger.read_health)
HEADUNIT_SIGNALS = {
    "headunit.cpu_temp_c": "°C",       # hottest thermal zone
    "headunit.cpu_load": None,         # load average over 1 minute, 1.0 = one core busy
    "headunit.memory_free_mb": "MB",   # memory available to programs
    "headunit.disk_free_mb": "MB",     # free space on the data partition
}
METADATA_TOPIC = "signals.info"
MAX_TEXT = 64
# samples kept in memory while the database cannot be written (disk full); the oldest go first
MAX_BUFFER = 500_000
UPDATE = "update"


def group_of(name):
    if name.startswith("vehicle.position."):
        return "position"
    if name.startswith("vehicle."):
        return "vehicle"
    if name.startswith("headunit."):
        return "health"
    return "openhu"


def loggable(value):
    if isinstance(value, bool) or (isinstance(value, str) and len(value) <= MAX_TEXT):
        return True
    return isinstance(value, (int, float)) and math.isfinite(value)


def flatten(topic, data):
    """[(signal, value)] of the loggable fields of a topic: numbers, booleans, short texts; one level of nested
    objects for vehicle data, the fixed fields for OpenHU topics."""
    fields = []
    for field, value in (data or {}).items():
        if not topic.startswith("vehicle."):
            known = OPENHU_SIGNALS.get((topic, field))
            if known is not None and loggable(value):
                fields.append((known[0], value))
        elif isinstance(value, dict):
            fields += [("%s.%s.%s" % (topic, field, sub), inner) for sub, inner in value.items()
                       if not isinstance(inner, dict) and loggable(inner)]
        elif loggable(value):
            fields.append(("%s.%s" % (topic, field), value))
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
    if "above" in trigger and not (is_number(value) and value > trigger["above"]):
        return False
    if "below" in trigger and not (is_number(value) and value < trigger["below"]):
        return False
    if "equals" in trigger and value != trigger["equals"]:
        return False
    return any(condition in trigger for condition in ("above", "below", "equals"))


class Recorder:
    def __init__(self, store, config, info=None):
        self.store = store
        self.config = config
        self.info = dict(info or {})
        self.trips = Trips()
        self.values = {}            # signal -> latest value
        self.written = {}           # signal -> value of its last sample
        self.changed_at = {}        # signal -> time its value last changed (the time of its sample)
        self.last_sample = {}       # signal -> time of its last sample
        self.due = {}               # signal -> time of its next sample (fixed rates)
        self.rate_cache = {}
        self.samples = []           # (t, signal, value) not yet written
        self.pending_trips = []     # ended trips not yet written
        self.recording = None       # the open recording (dict) or None
        self.pending_recordings = []
        self.pre = collections.deque()  # (t, signal, value) of the last preSeconds, for a triggered recording
        self.active_triggers = set()
        self.announcements = []     # (topic, data) for the bus: logger.trip, logger.recording
        self.vehicle_data = False   # a vehicle.* topic arrived (the CAN plugin or another source runs)
        self.error = ""             # last write error, "" after a successful write
        for (topic, _), (name, unit) in OPENHU_SIGNALS.items():
            store.describe(name, unit, "openhu:" + topic)
        for name, unit in HEADUNIT_SIGNALS.items():
            store.describe(name, unit, "headunit")
        self.apply_config()

    def apply_config(self):
        self.trips.stop_ms = int(self.config["stopMinutes"] * 60_000)
        self.trips.engine_off_ms = int(self.config["engineOffSeconds"] * 1000)
        self.rate_cache.clear()
        self.due.clear()

    def enabled(self, group):
        return bool(self.config["enabled"]) and bool(self.config["groups"].get(group))

    def rate_of(self, name):
        """Seconds between samples of a signal, or UPDATE (every change)."""
        rate = self.rate_cache.get(name)
        if rate is None:
            rates = self.config.get("rates") or {}
            pattern = best_match(rates, name)
            rate = rates[pattern] if pattern is not None and valid_rate(rates[pattern]) else UPDATE
            self.rate_cache[name] = rate
        return rate

    def fastest_rate(self):
        """Seconds between ticks: the shortest fixed rate in use, at most 1 (trips and the live state)."""
        rates = [rate for rate in (self.config.get("rates") or {}).values() if is_number(rate) and valid_rate(rate)]
        return min([1.0] + rates)

    def recorded(self, name):
        return best_match(self.config["recording"].get("keys") or [], name) is not None

    # --- input ----------------------------------------------------------------------

    def on_signals_info(self, data):
        """Units of a source: {"source": ..., "signals": {"vehicle.speed.kmh": {"unit": "km/h"}}} (other fields are
        ignored)."""
        source = data.get("source") if isinstance(data.get("source"), str) else None
        for name, info in (data.get("signals") or {}).items():
            if isinstance(name, str) and isinstance(info, dict):
                unit = str(info["unit"])[:32] if info.get("unit") else None
                self.store.describe(name, unit, source)

    def on_topic(self, topic, data, t):
        if topic.startswith("vehicle."):
            self.vehicle_data = True
        for name, value in flatten(topic, data):
            self.on_value(name, value, t)

    def on_value(self, name, value, t):
        if not self.enabled(group_of(name)):
            return
        if name.startswith("vehicle.") and name not in self.store.signal_info:
            self.store.describe(name, source=name.rsplit(".", 1)[0])
        known = name in self.values
        old = self.values.get(name)
        changed = not known or old != value or type(old) is not type(value)
        self.values[name] = value
        if changed:
            self.changed_at[name] = t
            recorded = self.recorded(name)
            if not is_number(value) or self.rate_of(name) == UPDATE or (recorded and self.recording is not None):
                self._sample(t, name, value)
            elif recorded and self.config["recording"].get("triggers") and self.config["recording"].get("preSeconds"):
                self.pre.append((t, name, value))
                horizon = t - self.config["recording"]["preSeconds"] * 1000
                while self.pre and self.pre[0][0] < horizon:
                    self.pre.popleft()
        self._check_triggers(name, value, t)
        self._trip_changes(self.trips.update(t, name, value))

    def tick(self, t, health=None):
        """At least every second: health values (if given), samples of the numbers whose period is due, trip end
        rules, end of recordings."""
        if health:
            for name, value in health.items():
                self.on_value(name, value, t)
        for name, value in self.values.items():
            if not is_number(value) or self.written.get(name) == value:
                continue
            rate = self.rate_of(name)
            if rate == UPDATE or t < self.due.get(name, t):
                continue
            # the next period starts now; a tick a few ms early still counts (timer jitter)
            self.due[name] = t + int(rate * 1000) - 20
            # at the time the value arrived (it is held since then), not the time of the tick
            self._sample(self._held_time(name, t), name, value)
        self._trip_changes(self.trips.tick(t))
        self._recording_tick(t)

    def _held_time(self, name, t):
        """Time for the sample of a held value: when it arrived, after the signal's previous sample."""
        arrived = self.changed_at.get(name, t)
        last = self.last_sample.get(name)
        return arrived if last is None else max(arrived, last + 1)

    def _sample(self, t, name, value):
        self.samples.append((t, name, value))
        self.written[name] = value
        self.last_sample[name] = t

    def _trip_changes(self, changes):
        for kind, trip in changes:
            if kind == "start":
                trip.update(self.info)
                try:
                    self.store.write(trips=[trip])  # gives it its id
                except Exception as error:  # written with the next flush
                    self.error = str(error)
            else:
                self.pending_trips.append(trip)
                self._try_flush()
            self.announcements.append(("logger.trip", {"event": kind, "trip": public_trip(trip)}))

    # --- recordings -----------------------------------------------------------------

    def _check_triggers(self, name, value, t):
        settings = self.config["recording"]
        for index, trigger in enumerate(settings.get("triggers") or []):
            if trigger.get("key") != name:
                continue
            if trigger_holds(trigger, value):
                if not self.active_triggers and self.recording is None:
                    label = "%s %s" % (name, " ".join("%s %s" % (condition, trigger[condition])
                                                      for condition in ("above", "below", "equals")
                                                      if condition in trigger))
                    self.start_recording(t, label)
                self.active_triggers.add(index)
                if self.recording is not None and self.recording["trigger"] != "manual":
                    self.recording["holdUntil"] = t + settings.get("postSeconds", 10) * 1000
            else:
                self.active_triggers.discard(index)

    def start_recording(self, t, trigger="manual", label="", seconds=None):
        """trigger "manual" (ends after seconds or with stop_recording) or the condition that started it. Returns
        the recording."""
        if self.recording is not None:
            return self.recording
        settings = self.config["recording"]
        start = self.pre[0][0] if self.pre and trigger != "manual" else t
        limit = min(seconds or settings.get("maxSeconds", 600), settings.get("maxSeconds", 600))
        self.recording = {"id": None, "start": start, "end": t, "open": True, "trigger": trigger, "label": label,
                          "until": t + int(limit * 1000), "holdUntil": t}
        try:
            self.store.write(recordings=[self.recording])
        except Exception as error:
            self.error = str(error)
            self.recording = None
            return None
        if trigger != "manual":
            self.samples += list(self.pre)
        self.pre.clear()
        self.announcements.append(("logger.recording", {"event": "start", "recording": self.public_recording()}))
        return self.recording

    def stop_recording(self, t, why="manual"):
        recording = self.recording
        if recording is None:
            return None
        # the values held at the end belong to the window
        for name, value in self.values.items():
            if self.recorded(name) and self.written.get(name) != value:
                self._sample(self._held_time(name, t), name, value)
        recording.update(end=max(recording["start"], t), open=False, endReason=why)
        self.recording = None
        self.active_triggers.clear()
        self.pending_recordings.append(recording)
        self._try_flush()
        self.announcements.append(("logger.recording", {"event": "end", "recording": self.public_recording(recording),
                                                        "reason": why}))
        return recording

    def _recording_tick(self, t):
        recording = self.recording
        if recording is None:
            return
        recording["end"] = t
        limit = self.config["recording"].get("limitMB", 256) * 1024 * 1024
        if t >= recording["until"]:
            self.stop_recording(t, "time")
        elif recording["trigger"] != "manual" and not self.active_triggers and t >= recording["holdUntil"]:
            self.stop_recording(t, "trigger")
        elif self.store.recording_bytes() + len(self.samples) * self.store.sample_bytes() > limit:
            self.stop_recording(t, "quota")

    def public_recording(self, recording=None):
        recording = recording if recording is not None else self.recording
        if recording is None:
            return None
        result = {key: recording[key] for key in ("id", "start", "end", "open", "trigger", "label")}
        result["reason"] = "manual" if recording["trigger"] == "manual" else "trigger"
        return result

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
        for table in (self.written, self.due, self.last_sample):
            table.clear()
        self.samples = []
        self.pending_trips = []
        self.pending_recordings = []

    def disable(self, t):
        """Logging switched off: the trip and a recording end, what is buffered is written."""
        self.end_trip(t, "off")
        self.stop_recording(t, "off")
        self._try_flush()
        for table in (self.values, self.written, self.due, self.changed_at):
            table.clear()
        self.pre.clear()

    # --- writing --------------------------------------------------------------------

    def _try_flush(self):
        try:
            self.flush()
        except Exception as error:
            self.error = str(error)

    def flush(self):
        """Writes the buffered samples, ended trips and recordings and the open trip and recording in one
        transaction. On an error (disk full) the samples stay buffered (bounded) and the error is raised."""
        trips = list(self.pending_trips)
        if self.trips.trip is not None:
            trips.append(self.trips.trip)
        recordings = list(self.pending_recordings)
        if self.recording is not None:
            recordings.append(self.recording)
        if not (self.samples or trips or recordings):
            return
        samples, self.samples = self.samples, []
        try:
            self.store.write(samples, trips, recordings)
        except Exception as error:
            self.error = str(error)
            self.samples = (samples + self.samples)[-MAX_BUFFER:]
            raise
        self.error = ""
        self.pending_trips = []
        self.pending_recordings = []

    def live(self, t):
        return {"t": t, "enabled": bool(self.config["enabled"]), "trip": self.trip,
                "recording": self.public_recording(), "values": dict(self.values)}
