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
        # sox: de-emphasis only at 44.1 kHz, i.e. after the rate conversion
        sox = radiolib.sox_mpx_to_audio()
        self.assertLess(sox.index("rate"), sox.index("deemph"))

    def test_station_names(self):
        names = {}
        self.assertTrue(radiolib.remember_name(names, "fm", 96.2, "NDR 2   "))
        self.assertFalse(radiolib.remember_name(names, "fm", 96.20000001, "NDR 2"))
        self.assertFalse(radiolib.remember_name(names, "fm", 96.2, "  "))
        self.assertTrue(radiolib.remember_name(names, "am", 1008, "AM TEST"))
        self.assertEqual(names, {"fm": {"96.2": "NDR 2"}, "am": {"1008": "AM TEST"}})

    def test_band_summary(self):
        config = {"stations": {"fm": [96.2, 101.9]}, "presets": {"am": [1008]}, "names": {"fm": {"96.2": "NDR 2"}}}
        bands = radiolib.band_summary(config)
        self.assertEqual(set(bands), {"fm", "am"})
        self.assertEqual(bands["fm"]["stations"], [96.2, 101.9])
        self.assertEqual(bands["fm"]["names"], {"96.2": "NDR 2"})
        self.assertEqual(bands["fm"]["unit"], "MHz")
        self.assertEqual(bands["am"]["presets"], [1008])
        self.assertEqual(bands["am"]["stations"], [])
        self.assertEqual((bands["am"]["min"], bands["am"]["max"], bands["am"]["step"]), (531, 1602, 9))

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
