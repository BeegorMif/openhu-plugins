import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import radiolib  # noqa: E402


class RadioLibTest(unittest.TestCase):
    def test_frequencies(self):
        self.assertEqual(radiolib.clamp_frequency("fm", 101.34), 101.3)
        self.assertEqual(radiolib.clamp_frequency("fm", 120), 108.0)
        self.assertEqual(radiolib.clamp_frequency("am", 1010), 1008)
        self.assertEqual(radiolib.step_frequency("fm", 101.3, 1), 101.4)
        self.assertEqual(radiolib.step_frequency("fm", 108.0, 1), 87.5)
        self.assertEqual(radiolib.step_frequency("am", 531, -1), 1602)

    def test_commands(self):
        args, rate = radiolib.rtl_fm_command("fm", 101.3, {"gain": "auto"}, rds=False)
        self.assertIn("101.3M", args)
        self.assertEqual(rate, 48000)
        args, rate = radiolib.rtl_fm_command("fm", 99.0, {"gain": 30, "ppm": 2}, rds=True)
        self.assertEqual(rate, 171000)
        self.assertIn("171k", args)
        self.assertEqual(args[1:5], ["-g", "30", "-p", "2"])
        args, _ = radiolib.rtl_fm_command("am", 1008, {}, rds=False)
        self.assertIn("1008k", args)
        self.assertIn("direct2", args)

    def test_scan(self):
        noise = ", ".join(["-40"] * 10)
        lines = [
            "2026-10-10, 12:00:00, 100000000, 101000000, 100000, 10, " + noise,
            "2026-10-10, 12:00:00, 101000000, 102000000, 100000, 10, -40, -40, -40, -20, -25, -40, -40, -40, -40, -40",
        ]
        self.assertEqual(radiolib.parse_rtl_power(lines), [101.3])

    def test_redsea(self):
        self.assertEqual(radiolib.parse_redsea('{"pi":"0xD3C2","ps":"NDR 2   ","radiotext":"Musik "}'),
                         {"ps": "NDR 2", "rt": "Musik"})
        self.assertEqual(radiolib.parse_redsea("garbage"), {})


if __name__ == "__main__":
    unittest.main()
