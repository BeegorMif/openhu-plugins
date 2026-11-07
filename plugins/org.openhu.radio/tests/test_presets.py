import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))

from test_tunepi import Api  # noqa: E402


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class PresetTest(unittest.TestCase):
    """savePreset/removePreset: the heart on the page keeps the station that plays or one of the list."""

    def setUp(self):
        import openhu
        import radio
        self.radio, self.openhu = radio, openhu
        self.data = tempfile.TemporaryDirectory()
        self.old_data_dir = radio.DATA_DIR, openhu.DATA_DIR
        radio.DATA_DIR = openhu.DATA_DIR = self.data.name
        self.plugin = radio.RadioPlugin()
        self.plugin.api = Api()
        self.plugin.texts.set_language("en")
        # own lists: the defaults of the config are shared between plugin instances
        self.plugin.config.update(band="fm", frequency={"fm": 96.2, "am": 1008, "dab": "0xD882"},
                                  presets={"fm": [], "am": [], "dab": []})

    def tearDown(self):
        self.radio.DATA_DIR, self.openhu.DATA_DIR = self.old_data_dir
        self.data.cleanup()

    def command(self, cmd, value=None, band=None):
        data = {"cmd": cmd, "value": value}
        if band:
            data["band"] = band
        asyncio.run(self.plugin.handle_command(data))
        return [data for topic, data in self.plugin.api.published if topic == "radio.state"][-1]

    def test_station_that_plays(self):
        self.assertEqual(self.command("savePreset")["presets"], [96.2])

    def test_station_of_the_list(self):
        # snapped to the raster, sorted, no duplicates
        self.command("savePreset", 100.0)
        self.command("savePreset", 89.04)
        self.assertEqual(self.command("savePreset", 89.0)["presets"], [89.0, 100.0])
        self.assertEqual(self.command("removePreset", 89.0)["presets"], [100.0])

    def test_dab_service(self):
        self.plugin.config["band"] = "dab"
        self.assertEqual(self.command("savePreset", "0xd312")["presets"], ["0xD312"])
        # an invalid service id is ignored
        self.assertEqual(self.command("savePreset", "radio")["presets"], ["0xD312"])

    def test_other_band(self):
        # the favorites tab of the page: hearts of stations of another band
        state = self.command("savePreset", "0xd312", band="dab")
        self.assertEqual(state["band"], "fm")
        self.assertEqual(state["bands"]["dab"]["presets"], ["0xD312"])
        self.assertEqual(state["presets"], [])
        state = self.command("savePreset", 1008, band="am")
        self.assertEqual(state["bands"]["am"]["presets"], [1008])
        # without a value only the band that plays has a station that plays
        self.assertEqual(self.command("savePreset", band="am")["bands"]["am"]["presets"], [1008])
        self.assertEqual(self.command("removePreset", "0xD312", band="dab")["bands"]["dab"]["presets"], [])

    def test_tune_other_band(self):
        state = self.command("tune", 1422, band="am")
        self.assertEqual((state["band"], state["frequency"]), ("am", 1422))
        state = self.command("tune", 100.0, band="fm")
        self.assertEqual((state["band"], state["frequency"]), ("fm", 100.0))
        # an unknown band is ignored: the current one
        state = self.command("tune", 101.0, band="sw")
        self.assertEqual((state["band"], state["frequency"]), ("fm", 101.0))

    def test_columns_setting(self):
        # changed in Settings → Apps: sent to the page, within 3-6
        self.plugin.config["columns"] = 5
        asyncio.run(self.plugin.settings_changed(["columns"]))
        self.assertEqual(self.plugin.api.published[-1][1]["columns"], 5)
        self.plugin.config["columns"] = 9
        asyncio.run(self.plugin.settings_changed(["columns"]))
        self.assertEqual(self.plugin.api.published[-1][1]["columns"], 6)


if __name__ == "__main__":
    unittest.main()
