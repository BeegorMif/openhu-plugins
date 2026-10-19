import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import canbus  # noqa: E402

PROFILE = os.path.join(os.path.dirname(__file__), "..", "profiles", "example.json")


def frame(can_id, data):
    return struct.pack("=IB3x8s", can_id, len(data), bytes(data))


class ExtractTest(unittest.TestCase):
    def test_parse_frame(self):
        self.assertEqual(canbus.parse_frame(frame(0x123, [1, 2])), (0x123, b"\x01\x02"))
        self.assertEqual(canbus.parse_frame(frame(0x80001234, [9])), (0x1234, b"\x09"))
        self.assertIsNone(canbus.parse_frame(frame(0x40000123, [])))

    def test_extract(self):
        data = bytes([0x12, 0x34, 0b1010_0110, 0xF6])
        self.assertEqual(canbus.extract(data, {"byte": 0, "length": 16}), 0x1234)
        self.assertEqual(canbus.extract(data, {"byte": 0, "length": 16, "endian": "little"}), 0x3412)
        self.assertEqual(canbus.extract(data, {"byte": 2, "bit": 1, "length": 1}), True)
        self.assertEqual(canbus.extract(data, {"byte": 2, "bit": 0, "length": 1}), False)
        self.assertEqual(canbus.extract(data, {"byte": 2, "bit": 4, "length": 4}), 0b1010)
        self.assertEqual(canbus.extract(data, {"byte": 3, "length": 8, "signed": True, "scale": 0.5}), -5.0)
        self.assertEqual(canbus.extract(data, {"byte": 3, "length": 8, "map": {"246": "P"}}), "P")
        self.assertIsNone(canbus.extract(data, {"byte": 3, "length": 16}))


class TopicTest(unittest.TestCase):
    def test_data_topic(self):
        self.assertEqual(canbus.data_topic("speed"), "can.speed")
        self.assertEqual(canbus.data_topic("can.speed"), "can.speed")
        # profiles from before openhu-plugins#29
        self.assertEqual(canbus.data_topic("vehicle.gear"), "can.gear")
        for topic in ("", None, "state", "can.monitor", "vehicle.command", "signals.extra"):
            self.assertIsNone(canbus.data_topic(topic), topic)

    def test_old_profile(self):
        profile = canbus.Profile({
            "signals": [{"id": "0x100", "topic": "vehicle.speed", "field": "kmh", "byte": 0, "length": 8},
                        {"id": "0x100", "topic": "state", "field": "x", "byte": 1, "length": 8}],
            "triggers": [{"topic": "vehicle.speed", "field": "kmh", "equals": 0, "then": {"action": "a"}}]})
        changed, _, commands = profile.feed(0x100, bytes([0, 7]))
        self.assertEqual(changed, {"can.speed": {"kmh": 0}})
        self.assertEqual(commands, [{"action": "a"}])
        self.assertEqual(len(profile.warnings), 3)


class ProfileTest(unittest.TestCase):
    def setUp(self):
        with open(PROFILE) as file:
            self.profile = canbus.Profile(json.load(file))

    def test_signals_publish_only_changes(self):
        changed, _, _ = self.profile.feed(0x100, bytes([0x13, 0x88, 0x0B, 0xB8]))
        self.assertEqual(changed["can.speed"], {"kmh": 50.0})
        self.assertEqual(changed["can.engine"], {"rpm": 3000})
        changed, _, _ = self.profile.feed(0x100, bytes([0x13, 0x88, 0x0B, 0xB8]))
        self.assertEqual(changed, {})

    def test_buttons_press_and_release(self):
        _, actions, _ = self.profile.feed(0x300, bytes([0x04]))
        self.assertEqual(actions, [("media.next", "press")])
        _, actions, _ = self.profile.feed(0x300, bytes([0x04]))
        self.assertEqual(actions, [])
        _, actions, _ = self.profile.feed(0x300, bytes([0x00]))
        self.assertEqual(actions, [("media.next", "release")])

    def test_triggers(self):
        _, _, commands = self.profile.feed(0x200, bytes([0x01, 0x00]))
        self.assertIn({"action": "camera.show"}, commands)
        self.assertIn({"method": "daynight.set", "params": {"night": False}}, commands)
        _, _, commands = self.profile.feed(0x200, bytes([0x03, 0x00]))
        self.assertEqual(commands, [{"method": "daynight.set", "params": {"night": True}}])
        _, _, commands = self.profile.feed(0x200, bytes([0x02, 0x00]))
        self.assertEqual(commands, [{"action": "camera.hide"}])


class ControlTest(unittest.TestCase):
    """Car controls for Android Auto (openhu#121): read like a signal, write into a frame template"""

    def setUp(self):
        with open(PROFILE) as file:
            self.profile = canbus.Profile(json.load(file))

    def test_encode(self):
        self.assertEqual(canbus.encode({"id": "0x3B0", "data": "01 00", "byte": 1, "length": 8, "scale": 0.5}, 21.5),
                         (0x3B0, bytes([0x01, 43])))
        self.assertEqual(canbus.encode({"id": 1, "byte": 0, "length": 16, "endian": "little"}, 0x1234)[1][:2],
                         bytes([0x34, 0x12]))
        # bits: the rest of the template stays
        self.assertEqual(canbus.encode({"id": 1, "data": "FF", "byte": 0, "bit": 4, "length": 2}, 1)[1], bytes([0xDF]))
        self.assertEqual(canbus.encode({"id": 1, "data": "00", "bit": 3, "length": 1}, True)[1], bytes([0x08]))
        self.assertEqual(canbus.encode({"id": 1, "data": "00", "length": 8, "signed": True}, -2)[1], bytes([0xFE]))
        self.assertEqual(canbus.encode({"id": 1, "data": "00", "length": 8, "map": {"3": "auto"}}, "auto")[1],
                         bytes([3]))
        # clamped to the field
        self.assertEqual(canbus.encode({"id": 1, "data": "00", "length": 4}, 99)[1], bytes([0x0F]))
        with self.assertRaises(ValueError):
            canbus.encode({"id": 1, "data": "00", "byte": 1, "length": 8}, 1)

    def test_encode_and_extract_agree(self):
        for spec, value in (({"byte": 1, "length": 8, "scale": 0.5}, 22.5), ({"byte": 2, "bit": 4, "length": 1}, True),
                            ({"byte": 0, "length": 16, "endian": "little", "offset": -40}, 25),
                            ({"byte": 3, "bit": 2, "length": 3}, 5)):
            _, data = canbus.encode(dict(spec, id=1), value)
            self.assertEqual(canbus.extract(data, spec), value, spec)

    def test_controls(self):
        state = self.profile.controls_state()
        self.assertEqual(state["driverSide"], "left")
        self.assertEqual([(entry["name"], entry["area"]) for entry in state["properties"]],
                         [("temperature", "driver"), ("temperature", "passenger"), ("seatHeating", "driver"),
                          ("ac", "front")])
        self.assertNotIn("value", state["properties"][0])
        self.assertTrue(state["properties"][0]["writable"])

        # values from the bus: driver 21.5, passenger 22, seat heating 2, A/C on
        changed, _, _ = self.profile.feed(0x3A0, bytes([43, 44, 0b0001_0010]))
        values = [entry["value"] for entry in changed["can.controls"]["properties"]]
        self.assertEqual(values, [21.5, 22.0, 2, True])
        changed, _, _ = self.profile.feed(0x3A0, bytes([43, 44, 0b0001_0010]))
        self.assertNotIn("can.controls", changed)

        frame, error = self.profile.set_control("temperature", "passenger", 23.0)
        self.assertIsNone(error)
        self.assertEqual(frame, (0x3B0, bytes([0x02, 46, 0, 0, 0, 0, 0, 0])))
        # read from the bus: the value follows the car, not the request
        self.assertEqual(self.profile.control_values[("temperature", "passenger")], 22.0)
        self.assertEqual(self.profile.set_control("temperature", "rear", 20), (None, "unknown control"))

    def test_write_only_and_driving(self):
        profile = canbus.Profile({"controls": [
            {"name": "steeringWheelHeating", "min": 0, "max": 3, "whileDriving": False,
             "write": {"id": "0x400", "data": "00", "length": 8}},
            {"name": "hvacPower", "area": "front", "read": {"id": "0x401", "length": 1}}]})
        self.assertEqual(profile.controls[0]["area"], "global")
        self.assertEqual(profile.set_control("steeringWheelHeating", "global", 2, restricted=True),
                         (None, "not while driving"))
        self.assertEqual(profile.set_control("steeringWheelHeating", "global", 2), ((0x400, bytes([2])), None))
        # without "read" the value counts as set
        self.assertEqual(profile.controls_state()["properties"][0]["value"], 2)
        self.assertEqual(profile.set_control("hvacPower", "front", True), (None, "read only"))
        self.assertFalse(profile.controls_state()["properties"][1]["writable"])

    def test_pack_frame(self):
        self.assertEqual(canbus.parse_frame(canbus.pack_frame(0x3B0, b"\x01\x02")), (0x3B0, b"\x01\x02"))
        self.assertEqual(canbus.parse_frame(canbus.pack_frame(0x18DAF110, b"\x01"))[0], 0x18DAF110)


if __name__ == "__main__":
    unittest.main()
