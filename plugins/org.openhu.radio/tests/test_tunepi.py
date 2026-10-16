import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))


class Api:
    """Records what the plugin publishes."""

    def __init__(self):
        self.published = []
        self.handlers = {}

    def on(self, pattern, callback):
        self.handlers[pattern] = callback

    async def publish(self, topic, **data):
        self.published.append((topic, data))

    async def safe(self, coroutine):
        return await coroutine


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class TunePiTest(unittest.TestCase):
    def setUp(self):
        import openhu
        import radio
        self.radio, self.openhu = radio, openhu
        self.data = tempfile.TemporaryDirectory()
        self.old_data_dir = radio.DATA_DIR, openhu.DATA_DIR
        # radio.py: logos, simulated stick; openhu.py: config.json
        radio.DATA_DIR = openhu.DATA_DIR = self.data.name
        self.plugin = radio.RadioPlugin()
        self.plugin.api = Api()
        self.plugin.texts.set_language("en")
        self.plugin.config.update(band="am", frequency={"fm": 101.9, "am": 1008},
                                  pis={"fm": {"96.2": "0xD382", "87.6": "0xD382", "88.6": "0xD384"}},
                                  levels={"fm": {"96.2": -10.0, "87.6": -20.0}})

    def tearDown(self):
        self.radio.DATA_DIR, self.openhu.DATA_DIR = self.old_data_dir
        self.data.cleanup()

    def state(self):
        return [data for topic, data in self.plugin.api.published if topic == "radio.state"][-1]

    def test_tune_pi(self):
        asyncio.run(self.plugin.handle_command({"cmd": "tunePi", "value": "0xd382"}))
        state = self.state()
        # switched to FM, strongest frequency of the programme
        self.assertEqual((state["band"], state["frequency"], state["error"]), ("fm", 96.2, ""))
        self.assertEqual(state["bands"]["fm"]["pis"]["88.6"], "0xD384")

        asyncio.run(self.plugin.handle_command({"cmd": "tunePi", "value": 0xD384}))
        self.assertEqual(self.state()["frequency"], 88.6)

    def test_unknown_pi(self):
        asyncio.run(self.plugin.handle_command({"cmd": "tunePi", "value": "0xD385"}))
        state = self.state()
        self.assertEqual((state["band"], state["frequency"]), ("am", 1008))
        self.assertIn("0xD385", state["error"])
        # the next tune clears it
        asyncio.run(self.plugin.handle_command({"cmd": "tune", "value": 1017}))
        self.assertEqual(self.state()["error"], "")

    def test_error_follows_language(self):
        # the error is kept as a text ID: published again in the new language after a switch (ui.language)
        self.plugin.texts.follow(self.plugin.api, self.plugin.publish_state)
        asyncio.run(self.plugin.handle_command({"cmd": "tunePi", "value": "0xD385"}))
        self.assertEqual(self.state()["error"], "Station with PI 0xD385 unknown")
        asyncio.run(self.plugin.api.handlers["ui.language"]("ui.language", {"language": "de"}))
        self.assertEqual(self.state()["error"], "Sender mit PI 0xD385 unbekannt")

    def test_rds_remembers_pi_and_name(self):
        class Reader:
            def __init__(self, lines):
                self.lines = [line.encode() + b"\n" for line in lines] + [b""]

            async def readline(self):
                return self.lines.pop(0)

        class Redsea:
            stdout = Reader(['{"pi": "0xD388", "ps": "__ffn___"}', '{"pi": "0xD388", "radiotext": "Song"}'])

        self.plugin.config.update(band="fm")
        self.plugin.playing = True
        asyncio.run(self.plugin.read_rds(Redsea()))
        self.assertEqual(self.plugin.rds, {"pi": "0xD388", "ps": "__ffn___", "rt": "Song"})
        self.assertEqual(self.plugin.config["pis"]["fm"]["101.9"], "0xD388")
        self.assertEqual(self.plugin.config["names"]["fm"]["101.9"], "__ffn___")
        self.assertEqual(self.state()["rds"]["pi"], "0xD388")


if __name__ == "__main__":
    unittest.main()
