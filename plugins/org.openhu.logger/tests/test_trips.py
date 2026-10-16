"""Trip detection: start and end rules, distance, duration, fuel, restore after a restart or power cut."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from trips import Trips  # noqa: E402

S = 1000
MIN = 60 * S
SPEED = "vehicle.speed.kmh"
ENGINE = "vehicle.engine.running"


def drive(trips, start, end, kmh, step=5 * S):
    """Holds a speed from start to end, ticking every step like the process. Returns the changes."""
    changes = trips.update(start, SPEED, kmh)
    t = start
    while t < end:
        t = min(t + step, end)
        changes += trips.tick(t)
    return changes


class TripsTest(unittest.TestCase):
    def test_speed_starts_and_standstill_ends(self):
        trips = Trips()
        changes = drive(trips, 0, 6 * MIN, 50)
        self.assertEqual([kind for kind, _ in changes], ["start"])
        self.assertEqual(changes[0][1]["startReason"], "speed")
        trip = trips.trip
        self.assertAlmostEqual(trip["distance"], 5.0, places=3)  # 50 km/h for 6 minutes
        self.assertEqual(trip["maxSpeed"], 50)

        # standing for 9 minutes: still the same trip
        self.assertEqual(drive(trips, 6 * MIN, 15 * MIN, 0), [])
        self.assertIsNotNone(trips.trip)
        # moving again resets the standstill time
        drive(trips, 15 * MIN, 16 * MIN, 30)
        changes = drive(trips, 16 * MIN, 27 * MIN, 0)
        self.assertEqual([kind for kind, _ in changes], ["end"])
        trip = changes[0][1]
        self.assertIsNone(trips.trip)
        self.assertEqual(trip["endReason"], "standstill")
        self.assertEqual(trip["end"], 16 * MIN)  # when it stopped, not 10 minutes later
        self.assertEqual(trip["duration"], 16 * MIN)  # the final 10 minutes standing are not part of it
        self.assertAlmostEqual(trip["distance"], 5.5, places=3)
        self.assertAlmostEqual(trip["avgSpeed"], 5.5 / (16 / 60), places=1)
        self.assertEqual(trip["movingTime"], 7 * MIN)
        self.assertFalse(trip["open"])

    def test_noise_below_threshold_starts_nothing(self):
        trips = Trips()
        self.assertEqual(drive(trips, 0, MIN, 0.3), [])
        self.assertIsNone(trips.trip)

    def test_engine_on_starts_and_off_ends_after_grace(self):
        trips = Trips(engine_off_ms=60 * S)
        changes = trips.update(0, ENGINE, True)
        self.assertEqual(changes[0][1]["startReason"], "engine")
        drive(trips, 10 * S, 5 * MIN, 40)
        trips.update(5 * MIN, SPEED, 0)
        # start-stop at a traffic light: engine off for 30 s, then on again
        trips.update(5 * MIN + 1 * S, ENGINE, False)
        self.assertEqual(drive(trips, 5 * MIN + 1 * S, 5 * MIN + 31 * S, 0), [])
        trips.update(5 * MIN + 31 * S, ENGINE, True)
        self.assertEqual(drive(trips, 5 * MIN + 31 * S, 6 * MIN, 0), [])
        self.assertIsNotNone(trips.trip)
        # parked: engine off for good
        trips.update(6 * MIN, ENGINE, False)
        changes = drive(trips, 6 * MIN, 8 * MIN, 0)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0][1]["endReason"], "engine")
        self.assertEqual(changes[0][1]["end"], 6 * MIN)
        self.assertEqual(changes[0][1]["duration"], 6 * MIN)

    def test_rpm_counts_as_engine(self):
        trips = Trips()
        self.assertEqual(trips.update(0, "vehicle.engine.rpm", 800)[0][0], "start")
        trips.update(MIN, "vehicle.engine.rpm", 0)
        self.assertEqual(trips.tick(3 * MIN)[0][1]["endReason"], "engine")

    def test_engine_only_car_ends_with_engine(self):
        """Without speed data the standstill rule does not apply (it would end every trip after 10 minutes)."""
        trips = Trips()
        trips.update(0, ENGINE, True)
        for t in range(0, 30 * MIN, 5 * S):
            self.assertEqual(trips.tick(t), [])
        trips.update(30 * MIN, ENGINE, False)
        self.assertEqual(trips.tick(32 * MIN)[0][1]["end"], 30 * MIN)

    def test_idling_ends_after_standstill(self):
        trips = Trips()
        trips.update(0, ENGINE, True)
        drive(trips, 0, MIN, 50)
        changes = drive(trips, MIN, 12 * MIN, 0)
        self.assertEqual(changes[0][1]["endReason"], "standstill")
        # engine still on: the next trip starts when the car moves
        self.assertIsNone(trips.trip)
        self.assertEqual(drive(trips, 12 * MIN, 13 * MIN, 20)[0][0], "start")

    def test_odometer_and_fuel(self):
        trips = Trips()
        trips.update(0, "vehicle.odometer.km", 1000.0)  # before a trip: ignored
        drive(trips, 0, 6 * MIN, 50)
        trips.update(1 * S, "vehicle.odometer.km", 1000.2)
        trips.update(1 * S, "vehicle.fuel.liters", 40.0)
        trips.update(6 * MIN, "vehicle.odometer.km", 1005.4)
        trips.update(6 * MIN, "vehicle.fuel.liters", 39.6)
        trip = trips.trip
        self.assertEqual(trip["distanceSource"], "odometer")
        self.assertAlmostEqual(trip["distance"], 5.2)
        self.assertAlmostEqual(trip["fuel"], 0.4)
        self.assertAlmostEqual(trip["consumption"], 7.69)

    def test_android_auto_time(self):
        trips = Trips()
        drive(trips, 0, MIN, 50)
        trips.update(MIN, "androidauto.connected", True)
        drive(trips, MIN, 3 * MIN, 50)
        trips.update(3 * MIN, "androidauto.connected", False)
        drive(trips, 3 * MIN, 4 * MIN, 50)
        self.assertEqual(trips.trip["aaTime"], 2 * MIN)

    def test_android_auto_time_stops_with_the_trip(self):
        """Android Auto stays connected while the car stands (the end rule fires 10 minutes later): that time is
        not part of the trip (seen in the VM: aaTime 761 s for a trip of 228 s)."""
        trips = Trips()
        trips.update(0, "androidauto.connected", True)
        drive(trips, 0, 4 * MIN, 50)
        changes = drive(trips, 4 * MIN, 15 * MIN, 0)
        trip = changes[0][1]
        self.assertEqual((trip["duration"], trip["aaTime"]), (4 * MIN, 4 * MIN))
        # same with the engine: off for good, the grace minute is not counted either
        trips = Trips()
        trips.update(0, "vehicle.engine.running", True)
        trips.update(0, "androidauto.connected", True)
        drive(trips, 0, 3 * MIN, 30)
        trips.update(3 * MIN, SPEED, 0)
        trips.update(3 * MIN, "vehicle.engine.running", False)
        trip = drive(trips, 3 * MIN, 5 * MIN, 0)[0][1]
        self.assertEqual((trip["endReason"], trip["duration"], trip["aaTime"]), ("engine", 3 * MIN, 3 * MIN))
        # and after a power cut: as it was at the last activity
        trips = Trips()
        trips.update(0, "androidauto.connected", True)
        drive(trips, 0, 2 * MIN, 50)
        drive(trips, 2 * MIN, 6 * MIN, 0)  # written while standing, then the power goes
        saved = dict(trips.trip, id=1)
        trip = Trips().restore(saved, 10 * 60 * MIN)[0][1]
        self.assertEqual((trip["duration"], trip["aaTime"]), (2 * MIN, 2 * MIN))

    def test_gaps_are_capped(self):
        """The process did not run for an hour (or the clock jumped): not an hour at 50 km/h."""
        trips = Trips()
        trips.update(0, SPEED, 50)
        trips.tick(60 * MIN)
        self.assertLessEqual(trips.trip["distance"], 50 / 60 + 1e-9)

    def test_restore_resumes_recent_trip(self):
        trips = Trips()
        drive(trips, 0, 5 * MIN, 50)
        saved = dict(trips.trip, id=7)
        restarted = Trips()
        self.assertEqual(restarted.restore(saved, 5 * MIN + 20 * S), [])
        self.assertEqual(restarted.trip["id"], 7)
        drive(restarted, 5 * MIN + 20 * S, 6 * MIN, 50)
        self.assertGreater(restarted.trip["distance"], saved["distance"])

    def test_restore_closes_old_trip(self):
        trips = Trips()
        drive(trips, 0, 5 * MIN, 50)
        saved = dict(trips.trip, id=7)
        changes = Trips().restore(saved, 5 * 60 * MIN)
        self.assertEqual(len(changes), 1)
        trip = changes[0][1]
        self.assertEqual((trip["endReason"], trip["end"], trip["open"]), ("power", 5 * MIN, False))


if __name__ == "__main__":
    unittest.main()
