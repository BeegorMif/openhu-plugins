import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAKE_SDR = os.path.join(TESTS, "..", "tools", "fake-sdr")
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, FAKE_SDR)
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))
import fakesdr  # noqa: E402
import radiolib  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"logo"
JPEG = b"\xff\xd8\xff\xe0" + b"logo"


class FakeSdrLogoTest(unittest.TestCase):
    def test_station_logos(self):
        stations = {"fm": [{"frequency": 96.2, "logo": "logos/a.png"}, {"frequency": 101.9}],
                    "am": [{"frequency": 1008.0, "logo": "/abs/b.jpg"}]}
        self.assertEqual(fakesdr.station_logos(stations, "/data/stations.json"),
                         {"fm": {"96.2": "/data/logos/a.png"}, "am": {"1008": "/abs/b.jpg"}})

    def test_bundled_logos_exist(self):
        path = os.path.join(FAKE_SDR, "stations.json")
        logos = fakesdr.station_logos(fakesdr.load_stations(path), path)
        self.assertEqual(set(logos), {"fm", "am"})
        for band in logos.values():
            for file in band.values():
                with open(file, "rb") as handle:
                    data = handle.read()
                self.assertEqual(radiolib.image_type(data), "image/png", file)
                self.assertLess(len(data), radiolib.MAX_LOGO_BYTES)


class Api:
    """Records what the plugin publishes."""

    def __init__(self):
        self.published = []

    async def publish(self, topic, **data):
        self.published.append((topic, data))

    async def safe(self, coroutine):
        return await coroutine


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class RadioPluginLogoTest(unittest.TestCase):
    def setUp(self):
        import radio
        self.radio = radio
        self.data = tempfile.TemporaryDirectory()
        self.old_data_dir = radio.DATA_DIR
        radio.DATA_DIR = self.data.name
        self.logos = os.path.join(self.data.name, "logos")
        os.makedirs(self.logos)
        os.environ.pop("OPENHU_FAKE_SDR", None)
        self.plugin = radio.RadioPlugin()
        self.plugin.api = Api()
        self.plugin.config.update(fakeSdr=False, stations={"fm": [92.6, 96.2, 101.9], "am": []},
                                  names={"fm": {"92.6": "N-JOY", "96.2": "NDR 2"}, "am": {}},
                                  frequency={"fm": 96.2, "am": 1008})

    def tearDown(self):
        self.radio.DATA_DIR = self.old_data_dir
        self.data.cleanup()

    def write(self, name, data):
        with open(os.path.join(self.logos, name), "wb") as file:
            file.write(data)

    def published_logos(self):
        return [data for topic, data in self.plugin.api.published if topic == "radio.logos"]

    def test_logos_from_the_data_dir(self):
        self.write("96,2.jpg", JPEG)
        self.write("njoy.png", PNG)
        self.write("101.9.png", b"GIF89a")  # neither PNG nor JPEG
        self.write("1008.png", b"\x89PNG\r\n\x1a\n" + b"x" * radiolib.MAX_LOGO_BYTES)  # too big
        self.write("readme.txt", b"text")

        self.assertTrue(asyncio.run(self.plugin.publish_logos()))
        logos = self.published_logos()[-1]
        self.assertEqual(set(logos), {"fm", "am"})
        self.assertEqual(logos["fm"], {"96.2": radiolib.data_url(JPEG), "92.6": radiolib.data_url(PNG)})
        self.assertEqual(logos["am"], {})
        self.assertEqual(self.plugin.current_logo(), radiolib.data_url(JPEG))

        # unchanged: not sent again; after a new connection again
        self.assertFalse(asyncio.run(self.plugin.publish_logos()))
        self.plugin.logos_sent = False
        self.assertTrue(asyncio.run(self.plugin.publish_logos()))

        # a file named after the frequency wins over the name; a removed file is gone
        os.remove(os.path.join(self.logos, "96,2.jpg"))
        self.write("NDR 2.png", PNG)
        self.assertTrue(asyncio.run(self.plugin.publish_logos()))
        self.assertEqual(self.published_logos()[-1]["fm"]["96.2"], radiolib.data_url(PNG))

    def test_cover_while_playing(self):
        self.write("96.2.png", PNG)
        self.plugin.playing = True
        asyncio.run(self.plugin.publish_state())
        topics = [topic for topic, _ in self.plugin.api.published]
        self.assertEqual(topics, ["radio.logos", "media.metadata", "media.status", "radio.state"])
        metadata = self.plugin.api.published[1][1]
        self.assertEqual(metadata["cover"], radiolib.data_url(PNG))
        self.assertEqual(metadata["artist"], "NDR 2")

    def test_simulated_stick_logos(self):
        stations = os.path.join(self.data.name, "fake-sdr-stations.json")
        with open(stations, "w") as file:
            json.dump({"fm": [{"frequency": 96.2, "name": "NDR 2", "tone": 440, "logo": "fake.png"},
                              {"frequency": 92.6, "name": "N-JOY", "tone": 440, "logo": "fake.png"}]}, file)
        with open(os.path.join(self.data.name, "fake.png"), "wb") as file:
            file.write(JPEG)
        self.write("njoy.png", PNG)
        self.plugin.config["fakeSdr"] = True
        environment = os.environ.pop("OPENHU_FAKE_SDR_STATIONS", None)
        try:
            asyncio.run(self.plugin.publish_logos())
        finally:
            if environment is not None:
                os.environ["OPENHU_FAKE_SDR_STATIONS"] = environment
        # the user's file wins over the simulated stick's
        self.assertEqual(self.published_logos()[-1]["fm"],
                         {"96.2": radiolib.data_url(JPEG), "92.6": radiolib.data_url(PNG)})


if __name__ == "__main__":
    unittest.main()
