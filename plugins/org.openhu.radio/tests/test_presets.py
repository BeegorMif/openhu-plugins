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

    def command(self, cmd, value=None):
        asyncio.run(self.plugin.handle_command({"cmd": cmd, "value": value}))
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


if __name__ == "__main__":
    unittest.main()
