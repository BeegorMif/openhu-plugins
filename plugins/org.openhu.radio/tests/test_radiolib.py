import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import radiolib  # noqa: E402


class RadioLibTest(unittest.TestCase):
    def test_play_while_playing_does_not_restart(self):
        self.assertTrue(radiolib.start_needed(False, False))
        self.assertTrue(radiolib.start_needed(True, False))   # processes died: start again
        self.assertTrue(radiolib.start_needed(False, True))
        self.assertFalse(radiolib.start_needed(True, True))

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

    def test_pi(self):
        self.assertEqual(radiolib.normalize_pi("0xd382"), "0xD382")
        self.assertEqual(radiolib.normalize_pi("D382"), "0xD382")
        self.assertEqual(radiolib.normalize_pi(0xD382), "0xD382")
        self.assertEqual(radiolib.normalize_pi(" 0x1b82 "), "0x1B82")
        for bad in (None, "", "xyz", 0, 0x10000, True, "0x"):
            self.assertIsNone(radiolib.normalize_pi(bad), bad)

        pis = {}
        self.assertTrue(radiolib.remember(pis, "fm", 96.2, "0xD382"))
        self.assertFalse(radiolib.remember(pis, "fm", 96.2, "0xD382"))
        self.assertFalse(radiolib.remember(pis, "fm", 96.2, None))
        self.assertEqual(pis, {"fm": {"96.2": "0xD382"}})

    def test_pi_frequency(self):
        # NDR 2 on three transmitters, levels of the last scan for two of them
        config = {"pis": {"fm": {"96.2": "0xD382", "87.6": "0xD382", "102.6": "0xD382", "88.6": "0xD384"}},
                  "levels": {"fm": {"96.2": -12.0, "87.6": -25.5, "88.6": -10.0}}}
        self.assertEqual(radiolib.pi_frequency(config, "0xD382"), 96.2)
        self.assertEqual(radiolib.pi_frequency(config, "d382", current=102.6), 96.2)
        self.assertEqual(radiolib.pi_frequency(config, 0xD384), 88.6)
        self.assertIsNone(radiolib.pi_frequency(config, "0xD385"))
        self.assertIsNone(radiolib.pi_frequency(config, "garbage"))
        # no levels: the current frequency if it has the PI, else the lowest
        config.pop("levels")
        self.assertEqual(radiolib.pi_frequency(config, "0xD382", current=102.6), 102.6)
        self.assertEqual(radiolib.pi_frequency(config, "0xD382", current=88.6), 87.6)
        self.assertIsNone(radiolib.pi_frequency({}, "0xD382"))

    def test_band_summary(self):
        config = {"stations": {"fm": [96.2, 101.9]}, "presets": {"am": [1008]}, "names": {"fm": {"96.2": "NDR 2"}},
                  "pis": {"fm": {"96.2": "0xD382"}}}
        bands = radiolib.band_summary(config)
        self.assertEqual(bands["fm"]["pis"], {"96.2": "0xD382"})
        self.assertEqual(bands["am"]["pis"], {})
        self.assertEqual(set(bands), {"fm", "am", "dab"})
        self.assertEqual(bands["fm"]["stations"], [96.2, 101.9])
        self.assertEqual(bands["fm"]["names"], {"96.2": "NDR 2"})
        self.assertEqual(bands["fm"]["unit"], "MHz")
        self.assertEqual(bands["am"]["presets"], [1008])
        self.assertEqual(bands["am"]["stations"], [])
        self.assertEqual((bands["am"]["min"], bands["am"]["max"], bands["am"]["step"]), (531, 1602, 9))

    def test_media_metadata(self):
        names = {"fm": {"96.2": "NDR 2"}}
        playing = radiolib.media_metadata("fm", 96.2, {"ps": "NDR 2   ", "rt": "Dreamer - Ozzy Osbourne"}, names)
        self.assertEqual((playing["title"], playing["artist"], playing["album"], playing["source"]),
                         ("Dreamer - Ozzy Osbourne", "NDR 2", "UKW 96,2 MHz", "radio"))
        # no RDS yet: the remembered name, else the frequency
        self.assertEqual(radiolib.media_metadata("fm", 96.2, {}, names)["title"], "NDR 2")
        unknown = radiolib.media_metadata("fm", 101.9, {}, names)
        self.assertEqual((unknown["title"], unknown["artist"]), ("UKW 101,9 MHz", "UKW 101,9 MHz"))
        self.assertEqual(radiolib.media_metadata("am", 1008, {}, {})["album"], "MW 1008 kHz")
        # the station logo as cover
        self.assertEqual(playing["cover"], "")
        self.assertEqual(radiolib.media_metadata("fm", 96.2, {}, names, "data:image/png;base64,AA==")["cover"],
                         "data:image/png;base64,AA==")

    def test_logo_files(self):
        index = radiolib.logo_index(["96.2.png", "88,6.JPG", "1008.jpeg", "NDR 2.png", "n-joy.jpg", "Radio 21.PNG",
                                     "notes.txt", ".png", "2.png", "96.2.jpg"])
        self.assertEqual(index["fm"], {"96.2": "96.2.jpg", "88.6": "88,6.JPG"})
        self.assertEqual(index["am"], {"1008": "1008.jpeg"})
        # names: case, spaces and punctuation do not count; a number outside both bands is a name
        self.assertEqual(index["name"], {"ndr2": "NDR 2.png", "njoy": "n-joy.jpg", "radio21": "Radio 21.PNG",
                                         "2": "2.png"})

        # frequency first, then the remembered RDS name
        self.assertEqual(radiolib.find_logo(index, "fm", "96.2", "NDR 2"), "96.2.jpg")
        self.assertEqual(radiolib.find_logo(index, "fm", "87.6", "NDR 2"), "NDR 2.png")
        self.assertEqual(radiolib.find_logo(index, "fm", "92.6", "N-JOY   "), "n-joy.jpg")
        self.assertEqual(radiolib.find_logo(index, "fm", "104.9", "RADIO 21"), "Radio 21.PNG")
        self.assertIsNone(radiolib.find_logo(index, "fm", "101.9", ""))
        self.assertIsNone(radiolib.find_logo(index, "fm", "101.9", "FFN"))
        self.assertEqual(radiolib.find_logo(index, "am", "1008"), "1008.jpeg")
        self.assertIsNone(radiolib.find_logo(index, "am", "96.2"))

    def test_logo_keys(self):
        config = {"stations": {"fm": [96.2, 101.9]}, "presets": {"fm": [104.9, 96.2]},
                  "names": {"fm": {"92.6": "N-JOY"}}}
        self.assertEqual(radiolib.logo_keys(config, "fm", 87.6), ["101.9", "104.9", "87.6", "92.6", "96.2"])
        self.assertEqual(radiolib.logo_keys(config, "am", 1008), ["1008"])
        self.assertEqual(radiolib.logo_keys({}, "am"), [])

    def test_data_url(self):
        png = b"\x89PNG\r\n\x1a\n" + b"rest"
        self.assertEqual(radiolib.image_type(png), "image/png")
        self.assertEqual(radiolib.data_url(png), "data:image/png;base64,iVBORw0KGgpyZXN0")
        self.assertTrue(radiolib.data_url(b"\xff\xd8\xff\xe0rest").startswith("data:image/jpeg;base64,"))
        self.assertIsNone(radiolib.data_url(b"<svg/>"))
        self.assertIsNone(radiolib.data_url(b""))

    def test_action_commands(self):
        self.assertEqual(radiolib.action_command("radio.next", False), {"cmd": "seek", "value": 1})
        self.assertEqual(radiolib.action_command("radio.toggle", False), {"cmd": "toggle"})
        # media keys only while the radio is the media source
        self.assertIsNone(radiolib.action_command("media.next", False))
        self.assertEqual(radiolib.action_command("media.next", True), {"cmd": "seek", "value": 1})
        self.assertEqual(radiolib.action_command("media.previous", True), {"cmd": "seek", "value": -1})
        self.assertEqual(radiolib.action_command("media.play_pause", True), {"cmd": "toggle"})
        self.assertEqual(radiolib.action_command("media.pause", True), {"cmd": "stop"})
        self.assertIsNone(radiolib.action_command("volume.up", True))
        # the table itself stays unchanged
        radiolib.action_command("media.next", True)["value"] = 5
        self.assertEqual(radiolib.MEDIA_KEY_COMMANDS["media.next"]["value"], 1)

    def test_scan(self):
        noise = ", ".join(["-40"] * 10)
        lines = [
            "2026-10-10, 12:00:00, 100000000, 101000000, 100000, 10, " + noise,
            "2026-10-10, 12:00:00, 101000000, 102000000, 100000, 10, -40, -40, -40, -20, -25, -40, -40, -40, -40, -40",
        ]
        self.assertEqual(radiolib.parse_rtl_power(lines), [101.3])
        self.assertEqual(radiolib.parse_rtl_power_levels(lines), {101.3: -20.0})
        self.assertEqual(radiolib.parse_rtl_power_levels([]), {})

    def test_redsea(self):
        self.assertEqual(radiolib.parse_redsea('{"pi":"0xd382","ps":"NDR 2   ","radiotext":"Musik "}'),
                         {"pi": "0xD382", "ps": "NDR 2", "rt": "Musik"})
        self.assertEqual(radiolib.parse_redsea('{"pi":"0x0000","ps":"X"}'), {"ps": "X"})
        self.assertEqual(radiolib.parse_redsea('[1, 2]'), {})
        self.assertEqual(radiolib.parse_redsea("garbage"), {})


if __name__ == "__main__":
    unittest.main()
