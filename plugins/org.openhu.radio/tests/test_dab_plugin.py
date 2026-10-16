"""The radio plugin's DAB part against the simulated welle-cli (tools/fake-sdr): scan, playback, DLS, slideshow.
Needs ffmpeg (fake welle-cli encodes MP3, the plugin decodes it when mpg123 is missing); pacat is replaced."""

import asyncio
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAKE_SDR = os.path.join(TESTS, "..", "tools", "fake-sdr")
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))

STATIONS = {
    "fm": [],
    "dab": [{"channel": "12D", "ensemble": "0xF0F0", "label": "OpenHU Test", "services": [
        {"sid": "0xF001", "label": "Testton DAB", "tone": 440, "dls": "Simulierter DAB+-Dienst",
         "slides": [os.path.join(FAKE_SDR, "slides", "test-1.png")]},
        {"sid": "0xF002", "label": "Zweiter Ton", "tone": 880}]}],
    "error": None,
}


class Api:
    def __init__(self):
        self.published = []

    async def publish(self, topic, **data):
        self.published.append((topic, data))

    async def safe(self, coroutine):
        return await coroutine

    def last(self, topic):
        return next((data for name, data in reversed(self.published) if name == topic), None)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(importlib.util.find_spec("websockets") and shutil.which("ffmpeg"), "needs websockets and ffmpeg")
class DabPluginTest(unittest.TestCase):
    def setUp(self):
        import openhu
        import radio
        self.radio, self.openhu = radio, openhu
        self.data = tempfile.TemporaryDirectory()
        self.old = radio.DATA_DIR, openhu.DATA_DIR, dict(os.environ)
        radio.DATA_DIR = openhu.DATA_DIR = self.data.name
        stations = os.path.join(self.data.name, "stations.json")
        with open(stations, "w") as file:
            json.dump(STATIONS, file)
        bin_dir = os.path.join(self.data.name, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "pacat"), "w") as file:
            file.write("#!/bin/sh\nexec cat >/dev/null\n")
        os.chmod(os.path.join(bin_dir, "pacat"), 0o755)
        os.environ.update(OPENHU_FAKE_SDR_STATIONS=stations, XDG_RUNTIME_DIR=self.data.name,
                          OPENHU_FAKE_SDR_DAB_SYNC_SECONDS="0.2", PATH=bin_dir + os.pathsep + os.environ["PATH"])
        self.plugin = radio.RadioPlugin()
        self.plugin.api = Api()
        self.plugin.config.update(fakeSdr=True, dabPort=free_port(), dabScanSeconds=1, dabChannels=["5A", "12D"])

    def tearDown(self):
        self.radio.DATA_DIR, self.openhu.DATA_DIR, environment = self.old
        os.environ.clear()
        os.environ.update(environment)
        self.data.cleanup()

    def test_scan_play_dls_slide(self):
        asyncio.run(self.scenario())

    async def wait(self, condition, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return True
            await asyncio.sleep(0.2)
        self.fail("timed out")

    async def scenario(self):
        plugin = self.plugin
        self.assertTrue(plugin.dab_available())
        await plugin.handle_command({"cmd": "band", "value": "dab"})
        await plugin.handle_command({"cmd": "scan"})
        self.assertTrue(plugin.scanning)
        # commands other than stop wait for the scan
        await plugin.handle_command({"cmd": "play"})
        self.assertFalse(plugin.playing)
        await self.wait(lambda: not plugin.scanning)
        self.assertEqual(plugin.error, "")
        self.assertEqual(plugin.config["stations"]["dab"], ["0xF001", "0xF002"])
        self.assertEqual(plugin.config["names"]["dab"]["0xF001"], "Testton DAB")
        self.assertEqual(plugin.config["dabServices"]["0xF001"]["channel"], "12D")

        await plugin.handle_command({"cmd": "tune", "value": "0xf001"})
        await plugin.handle_command({"cmd": "play"})
        self.assertTrue(plugin.playing)
        # DLS as radiotext, the slide as radio.slide and as cover
        await self.wait(lambda: plugin.rds.get("rt") == "Simulierter DAB+-Dienst" and plugin.slide)
        state = self.plugin.api.last("radio.state")
        self.assertEqual((state["band"], state["frequency"], state["dab"]["label"]), ("dab", "0xF001", "OpenHU Test"))
        self.assertEqual(self.plugin.api.last("radio.slide")["station"], "0xF001")
        self.assertTrue(self.plugin.api.last("radio.slide")["image"].startswith("data:image/png;base64,"))
        await self.wait(lambda: (self.plugin.api.last("media.metadata") or {}).get("cover") == plugin.slide)
        self.assertEqual(self.plugin.api.last("media.metadata")["album"], "DAB+ 12D · OpenHU Test")
        # sound arrives at "pacat": the decoder runs and welle-cli streams
        welle, decoder, pacat = plugin.processes
        self.assertIsNone(decoder.returncode)

        # seek: next service of the list, no slide there
        await plugin.handle_command({"cmd": "seek", "value": 1})
        self.assertEqual(plugin.frequency, "0xF002")
        self.assertEqual(self.plugin.api.last("radio.slide")["image"], "")
        await self.wait(lambda: plugin.rds.get("ps") == "Zweiter Ton")
        await plugin.handle_command({"cmd": "tune", "value": "0xABCD"})
        self.assertIn("Unbekannter DAB-Sender", plugin.error)
        await plugin.handle_command({"cmd": "stop"})
        self.assertFalse(plugin.playing)
        self.assertEqual(plugin.processes, [])

    def test_no_stick(self):
        async def scenario():
            plugin = self.plugin
            with open(os.environ["OPENHU_FAKE_SDR_STATIONS"], "w") as file:
                json.dump(dict(STATIONS, error="no-device"), file)
            plugin.config.update(band="dab", frequency={"fm": 101.3, "am": 1008, "dab": "0xF001"},
                                 dabServices={"0xF001": {"label": "Testton DAB", "channel": "12D"}})
            await plugin.handle_command({"cmd": "play"})
            await self.wait(lambda: not plugin.playing)
            self.assertEqual(plugin.error, "Kein RTL-SDR-Stick gefunden")
            self.assertEqual(plugin.processes, [])
            await plugin.handle_command({"cmd": "scan"})
            await self.wait(lambda: not plugin.scanning)
            self.assertEqual(plugin.error, "Kein RTL-SDR-Stick gefunden")
            self.assertEqual(list(plugin.config["dabServices"]), ["0xF001"])
        asyncio.run(scenario())

    def test_scan_can_be_cancelled(self):
        async def scenario():
            plugin = self.plugin
            plugin.config.update(band="dab", dabChannels=list(__import__("dablib").DAB_CHANNELS),
                                 dabServices={"0x1234": {"label": "Alt", "channel": "5A"}})
            await plugin.handle_command({"cmd": "scan"})
            await asyncio.sleep(1)
            await plugin.handle_command({"cmd": "stop"})
            await self.wait(lambda: not plugin.scanning)
            # cancelled: the old list stays
            self.assertEqual(list(plugin.config["dabServices"]), ["0x1234"])
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
