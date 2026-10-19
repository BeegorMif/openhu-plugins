import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "common"))
import vehicle  # noqa: E402


class VehicleTest(unittest.TestCase):
    def test_vehicle_topic(self):
        self.assertEqual(vehicle.vehicle_topic("can.speed"), "vehicle.speed")
        self.assertEqual(vehicle.vehicle_topic("can.parkingBrake"), "vehicle.parkingBrake")
        for topic in ("can.state", "can.monitor", "can.doorOpen", "vehicle.speed", "canx.speed"):
            self.assertIsNone(vehicle.vehicle_topic(topic), topic)

    def test_forwards_values(self):
        forwarder = vehicle.Forwarder()
        self.assertEqual(forwarder.on_can("can.speed", {"kmh": 50}, 0), [("vehicle.speed", {"kmh": 50})])
        self.assertEqual(forwarder.on_can("can.gear", {"reverse": True}, 0), [("vehicle.gear", {"reverse": True})])
        self.assertEqual(forwarder.on_can("can.monitor", {"frames": []}, 0), [])
        self.assertEqual(forwarder.on_can("can.state", {"connected": True}, 0), [])

    def test_bus_gone(self):
        forwarder = vehicle.Forwarder()
        forwarder.on_can("can.speed", {"kmh": 50}, 0)
        forwarder.on_can("can.gear", {"reverse": False}, 0)
        self.assertEqual(forwarder.on_can("can.state", {"connected": False}, 1),
                         [("vehicle.gear", {"available": False}), ("vehicle.speed", {"available": False})])
        # once
        self.assertEqual(forwarder.on_can("can.state", {"connected": False}, 2), [])
        self.assertEqual(forwarder.on_can("can.speed", {"kmh": 0}, 3), [("vehicle.speed", {"kmh": 0})])

    def test_can_plugin_stops_reporting(self):
        forwarder = vehicle.Forwarder()
        self.assertEqual(forwarder.check(100), [])  # never reported
        forwarder.on_can("can.state", {"connected": True}, 0)
        forwarder.on_can("can.speed", {"kmh": 50}, 0)
        self.assertEqual(forwarder.check(vehicle.STATE_TIMEOUT), [])
        self.assertEqual(forwarder.check(vehicle.STATE_TIMEOUT + 1), [("vehicle.speed", {"available": False})])
        self.assertEqual(forwarder.check(vehicle.STATE_TIMEOUT + 2), [])

    def test_demo_controls(self):
        demo = vehicle.demo_controls()
        names = [(entry["name"], vehicle.area_of(entry)) for entry in demo["properties"]]
        self.assertIn(("temperature", "driver"), names)
        self.assertIn(("steeringWheelHeating", "global"), names)
        self.assertIn(("defrost", "windshield"), names)
        self.assertTrue(vehicle.apply_set(demo, {"name": "temperature", "area": "passenger", "value": 23.5}))
        self.assertEqual(demo["properties"][1]["value"], 23.5)
        self.assertTrue(vehicle.apply_set(demo, {"name": "steeringWheelHeating", "area": "global", "value": 2}))
        self.assertFalse(vehicle.apply_set(demo, {"name": "temperature", "area": "rear", "value": 20}))


if __name__ == "__main__":
    unittest.main()
