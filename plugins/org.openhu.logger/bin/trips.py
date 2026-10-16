"""Trip detection and the running summary of a trip (no I/O, times in ms since 1970).

A trip starts when the car moves (speed above MOVING_KMH) or the engine is switched on. It ends
- when the engine is switched off and stays off for `engine_off_ms` (start-stop systems switch it off at traffic
  lights; the trip goes on when it runs again within that time), at the time it was switched off, or
- when the car stands still for `stop_ms` (default 10 minutes), at the time it stopped. Only with speed data: a car
  that reports only the engine ends its trips with the engine.
The process ends a trip itself when logging is switched off; a trip left open by a power cut is closed at the next
start (Trips.restore).

Distance: the odometer (vehicle.odometer.km) if the car reports it, otherwise the speed integrated over time. Fuel:
the drop of the tank content (vehicle.fuel.liters) between the start and the end, if the car reports it.
"""

MOVING_KMH = 0.5
# integration steps longer than this (process not running, clock jumps) count as this long
MAX_STEP_MS = 60_000


class Trips:
    def __init__(self, stop_ms=600_000, engine_off_ms=60_000):
        self.stop_ms = stop_ms
        self.engine_off_ms = engine_off_ms
        self.trip = None            # summary of the open trip (dict), None between trips
        self.speed = None           # last speed (km/h), None = car reports none
        self.engine = None          # engine running (bool), None = unknown
        self.aa = False             # Android Auto connected
        self.stopped_since = None   # time the speed dropped to 0
        self.engine_off_since = None
        self.last = None            # time of the last integration step

    # --- inputs ---------------------------------------------------------------------

    def update(self, t, key, value):
        """A new value of a logged key. Returns [("start"|"end", trip)] for the changes it caused."""
        changes = []
        if key == "vehicle.speed.kmh" and isinstance(value, (int, float)) and not isinstance(value, bool):
            self._step(t)
            was_moving = self.moving
            self.speed = float(value)
            if self.moving:
                self.stopped_since = None
                if self.trip is None:
                    changes.append(self._start(t, "speed"))
                self.trip["maxSpeed"] = max(self.trip["maxSpeed"], self.speed)
            elif was_moving or self.stopped_since is None:
                self.stopped_since = t
                self._snapshot("atStop")
        elif key in ("vehicle.engine.running", "vehicle.engine.on", "vehicle.engine.rpm"):
            running = bool(value) if key != "vehicle.engine.rpm" else float(value) > 0
            self._step(t)
            was_running = self.engine
            self.engine = running
            if running:
                self.engine_off_since = None
                if not was_running and self.trip is None:
                    changes.append(self._start(t, "engine"))
            elif was_running:
                self.engine_off_since = t
                self._snapshot("atEngineOff")
        elif key == "vehicle.odometer.km" and self.trip is not None:
            self.trip.setdefault("odometerStart", float(value))
            self.trip["odometerEnd"] = float(value)
        elif key == "vehicle.fuel.liters" and self.trip is not None:
            self.trip.setdefault("fuelStart", float(value))
            self.trip["fuelEnd"] = float(value)
        elif key == "androidauto.connected":
            self._step(t)
            self.aa = bool(value)
        self._refresh(t)
        return changes

    def tick(self, t):
        """Called every interval: integrates and applies the end rules. Returns [("end", trip)] or []."""
        self._step(t)
        changes = []
        if self.trip is not None and not self.moving:
            if self.engine_off_since is not None and t - self.engine_off_since >= self.engine_off_ms:
                changes.append(self.end(self.engine_off_since, "engine", t))
            elif self.speed is not None and self.stopped_since is not None and t - self.stopped_since >= self.stop_ms:
                # also while the engine idles
                changes.append(self.end(self.stopped_since, "standstill", t))
        self._refresh(t)
        return changes

    @property
    def moving(self):
        return self.speed is not None and self.speed > MOVING_KMH

    # --- trips ----------------------------------------------------------------------

    def _start(self, t, reason):
        self.trip = {
            "id": None, "start": t, "end": t, "open": True, "startReason": reason, "endReason": None,
            "duration": 0, "movingTime": 0, "aaTime": 0, "maxSpeed": self.speed if self.moving else 0.0,
            "speedDistance": 0.0, "last": t,
        }
        self.last = t
        if not self.moving:
            self.stopped_since = t
            self._snapshot("atStop")
        self._refresh(t)
        return ("start", self.trip)

    def _snapshot(self, name):
        """Duration and Android Auto time at this moment: a trip that ends here later (standstill, engine off) gets
        these, not the minutes counted while waiting for the end rule."""
        if self.trip is not None:
            self.trip[name] = [self.trip["duration"], self.trip["aaTime"]]

    def end(self, t, reason, now=None):
        """Ends the open trip at time t (not before its start). With now (> t): the end rule fired later than t, the
        time between them is not part of the trip (duration and Android Auto time as they were at t)."""
        trip = self.trip
        snapshot = trip.get({"standstill": "atStop", "engine": "atEngineOff"}.get(reason, ""))
        if now is not None and snapshot is not None:
            trip["duration"], trip["aaTime"] = snapshot
        elif now is not None:
            trip["duration"] = max(0, trip["duration"] - max(0, now - t))
            trip["aaTime"] = min(trip["aaTime"], trip["duration"])
        else:
            self._step(t)  # up to the end (logging switched off while driving)
        trip["end"] = max(trip["start"], t)
        trip["open"] = False
        trip["endReason"] = reason
        self._summarize(trip)
        self.trip = None
        self.engine_off_since = None
        return ("end", trip)

    def restore(self, trip, now):
        """A trip that was open when the process ended (from the database). Resumed if the car was active less
        than stop_ms ago (process restart while driving), otherwise closed at its last activity (power cut,
        head unit switched off). Returns [("end", trip)] or []."""
        trip = dict(trip)
        last = trip.get("last") or trip["end"]
        if 0 <= now - last < self.stop_ms:
            trip["open"] = True
            self.trip = trip
            self.last = now
            self.stopped_since = last
            trip["atStop"] = [trip.get("lastDuration", trip["duration"]), trip.get("lastAa", trip["aaTime"])]
            return []
        trip["open"] = False
        trip["end"] = max(trip["start"], last)
        # as it was at the last activity, not at the last write
        trip["duration"] = trip.get("lastDuration", trip["duration"])
        trip["aaTime"] = min(trip.get("lastAa", trip["aaTime"]), trip["duration"])
        trip["endReason"] = "power"
        self._summarize(trip)
        return [("end", trip)]

    def _step(self, t):
        """Integrates the held speed, moving time and Android Auto time up to t."""
        if self.last is None or self.trip is None:
            self.last = t
            return
        dt = min(max(t - self.last, 0), MAX_STEP_MS)
        self.last = t
        trip = self.trip
        trip["duration"] += dt
        if self.moving:
            trip["speedDistance"] += self.speed * dt / 3_600_000.0
            trip["movingTime"] += dt
        if self.aa:
            trip["aaTime"] += dt

    def _refresh(self, t):
        if self.trip is None:
            return
        if self.moving or self.engine:
            self.trip["last"] = t
            self.trip["lastDuration"], self.trip["lastAa"] = self.trip["duration"], self.trip["aaTime"]
        self.trip["end"] = max(self.trip["end"], t)
        self._summarize(self.trip)

    @staticmethod
    def _summarize(trip):
        odometer = None
        if "odometerStart" in trip and trip["odometerEnd"] >= trip["odometerStart"]:
            odometer = trip["odometerEnd"] - trip["odometerStart"]
        if odometer is not None:
            trip["distance"], trip["distanceSource"] = round(odometer, 3), "odometer"
        else:
            trip["distance"], trip["distanceSource"] = round(trip["speedDistance"], 3), "speed"
        hours = trip["duration"] / 3_600_000.0
        trip["avgSpeed"] = round(trip["distance"] / hours, 1) if hours > 0 else 0.0
        if "fuelStart" in trip and trip["fuelStart"] >= trip["fuelEnd"]:
            trip["fuel"] = round(trip["fuelStart"] - trip["fuelEnd"], 2)
            trip["consumption"] = round(trip["fuel"] * 100.0 / trip["distance"], 2) if trip["distance"] > 1 else None
