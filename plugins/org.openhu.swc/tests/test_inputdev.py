import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import inputdev  # noqa: E402

DEVICES = """I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name="Logitech USB Receiver"
H: Handlers=sysrq kbd leds event3
B: EV=120013
B: KEY=1000000000007 ff9f207ac14057ff febeffdfffefffff fffffffffffffffe

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event1
B: EV=3
B: KEY=10000000000000 0

I: Bus=0003 Vendor=1bcf Product=0005 Version=0110
N: Name="USB Optical Mouse"
H: Handlers=mouse0 event5
B: EV=17
B: KEY=0
"""


class InputDevTest(unittest.TestCase):
    def test_parse_devices(self):
        self.assertEqual(inputdev.parse_devices(DEVICES), [
            {"name": "Logitech USB Receiver", "event": "event3"},
            {"name": "Power Button", "event": "event1"},
        ])

    def test_key_name(self):
        self.assertEqual(inputdev.key_name(163), "NEXTSONG")
        self.assertEqual(inputdev.key_name(999), "KEY_999")


if __name__ == "__main__":
    unittest.main()
