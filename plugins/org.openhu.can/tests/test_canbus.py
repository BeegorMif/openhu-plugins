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


if __name__ == "__main__":
    unittest.main()
