import json
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "tools", "fake-sdr"))
import dablib  # noqa: E402
import fakesdr  # noqa: E402
import radiolib  # noqa: E402

# Shortened /mux.json of welle-cli 2.4 (format of its jsonconvert.cpp): labels are objects, ids lower case hex
MUX = {
    "ensemble": {"id": "0x1188", "ecc": "0xe0", "label": {"label": "NDR NDS", "shortlabel": "NDR NDS"}},
    "services": [
        {"sid": "0xd882", "label": {"label": "NDR 2 NDS       ", "shortlabel": "NDR 2"}, "url_mp3": "/mp3/0xd882",
         "components": [{"transportmode": "audio", "ascty": "DAB+"}],
         "dls": {"label": "Dreamer - Ozzy Osbourne", "time": 1, "lastchange": 1},
         "mot": {"time": 5, "lastchange": 5}},
        {"sid": "0xd383", "label": {"label": "NDR Kultur", "shortlabel": "NDR Kult"}, "url_mp3": None,
         "components": [{"transportmode": "audio", "ascty": "DAB+"}], "dls": {"label": ""}, "mot": {"time": 0}},
        {"sid": "0xe0d03188", "label": {"label": "NDR EPG", "shortlabel": "NDR EPG"}, "url_mp3": None,
         "components": [{"transportmode": "packetdata"}]},
        {"sid": "0xd385", "label": {"label": "", "shortlabel": ""}, "url_mp3": "/mp3/0xd385"},
    ],
}


class DabLibTest(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(dablib.normalize_sid("0xd882"), "0xD882")
        self.assertEqual(dablib.normalize_sid("D882"), "0xD882")
        self.assertEqual(dablib.normalize_sid(0xD882), "0xD882")
        self.assertEqual(dablib.normalize_sid("0xe0d03188"), "0xE0D03188")
        for bad in (None, "", "xyz", 0, True, -1, 0x100000000):
            self.assertIsNone(dablib.normalize_sid(bad), bad)
        self.assertEqual(dablib.welle_sid("0xD882"), "0xd882")
        self.assertEqual(dablib.normalize_channel("7a"), "7A")
        self.assertIsNone(dablib.normalize_channel("14A"))

    def test_channels(self):
        self.assertEqual(len(dablib.DAB_CHANNELS), 38)
        self.assertEqual(list(dablib.DAB_CHANNELS)[0], "5A")
        self.assertEqual(list(dablib.DAB_CHANNELS)[-1], "13F")
        # Hannover: DR Deutschland 5C, NDR 7A, private 8C (centre frequencies from DABLIST)
        self.assertEqual((dablib.DAB_CHANNELS["5C"], dablib.DAB_CHANNELS["7A"], dablib.DAB_CHANNELS["8C"]),
                         (178352, 188928, 199360))

    def test_commands(self):
        self.assertEqual(dablib.welle_cli_command("7A", 7979, {"gain": "auto"}),
                         ["welle-cli", "-c", "7A", "-w", "7979", "-T"])
        self.assertEqual(dablib.welle_cli_command("5C", 8000, {"gain": 30})[-2:], ["-g", "30"])
        self.assertEqual(dablib.mp3_decoder_command("mpg123")[:3], ["mpg123", "-q", "-s"])
        ffmpeg = dablib.mp3_decoder_command("ffmpeg")
        self.assertEqual(ffmpeg[0], "ffmpeg")
        self.assertIn("s16le", ffmpeg)
        self.assertEqual(radiolib.pacat_command(48000, 2)[3:5], ["--rate=48000", "--channels=2"])

    def test_parse_mux(self):
        mux = dablib.parse_mux(json.dumps(MUX))
        self.assertEqual(mux["ensemble"], {"id": "0x1188", "label": "NDR NDS", "ecc": "0xE0"})
        ndr2 = mux["services"]["0xD882"]
        self.assertEqual((ndr2["label"], ndr2["shortLabel"], ndr2["audio"], ndr2["dls"], ndr2["mot"]),
                         ("NDR 2 NDS", "NDR 2", True, "Dreamer - Ozzy Osbourne", 5))
        # audio by its component also without url_mp3; data services are no audio
        self.assertTrue(mux["services"]["0xD383"]["audio"])
        self.assertFalse(mux["services"]["0xE0D03188"]["audio"])
        # before the sync: no ensemble
        empty = dablib.parse_mux(json.dumps({"ensemble": {"id": "0x0000", "label": {"label": ""}}, "services": []}))
        self.assertEqual(empty, {"ensemble": None, "services": {}, "noDevice": False})
        self.assertEqual(dablib.parse_mux("garbage"), {"ensemble": None, "services": {}, "noDevice": False})
        self.assertEqual(dablib.parse_mux("[]"), {"ensemble": None, "services": {}, "noDevice": False})
        # real welle-cli 2.4 without a stick (Debian trixie): it keeps running with a "Null device"
        nostick = ('{"ensemble":{"ecc":"0x00","id":"0x0000","label":{"fig2charset":"Undefined","fig2label":"",'
                   '"fig2rfu":false,"label":"","shortlabel":""}},"messages":[],"receiver":{"hardware":{"gain":0.0,'
                   '"name":"Null device"},"software":{"name":"welle.io","version":"2.4+ds"}},"services":[]}')
        self.assertEqual(dablib.parse_mux(nostick), {"ensemble": None, "services": {}, "noDevice": True})

    def test_scan(self):
        found_7a = dablib.scan_services("7A", dablib.parse_mux(json.dumps(MUX)))
        # audio services with a label
        self.assertEqual(set(found_7a), {"0xD882", "0xD383"})
        self.assertEqual(found_7a["0xD882"], {"label": "NDR 2 NDS", "shortLabel": "NDR 2", "channel": "7A",
                                              "ensemble": "0x1188", "ensembleLabel": "NDR NDS", "ecc": "0xE0"})
        self.assertEqual(dablib.scan_services("5A", {"ensemble": None, "services": {}}), {})
        found_5c = {"0xD210": dict(found_7a["0xD882"], label="Dlf", channel="5C"),
                    "0xD882": dict(found_7a["0xD882"], channel="5C", label="NDR 2 elsewhere")}
        services = dablib.merge_scan({"7A": found_7a, "5C": found_5c})
        # the first channel wins
        self.assertEqual(services["0xD882"]["channel"], "5C")
        self.assertEqual(dablib.station_order(services), ["0xD210", "0xD882", "0xD383"])
        self.assertEqual(dablib.channel_label(services["0xD383"]), "DAB+ 7A · NDR NDS")
        self.assertEqual(dablib.channel_label(None), "DAB+")

    def test_radiolib_with_dab(self):
        self.assertEqual(radiolib.frequency_key("dab", "0xd882"), "0xD882")
        self.assertEqual(radiolib.clamp_frequency("dab", "d882"), "0xD882")
        self.assertIsNone(radiolib.clamp_frequency("dab", "nonsense"))
        config = {"stations": {"dab": ["0xD882"]}, "presets": {"dab": ["0xD882"]},
                  "names": {"dab": {"0xD882": "NDR 2 NDS"}},
                  "dabServices": {"0xD882": {"label": "NDR 2 NDS", "channel": "7A", "ensembleLabel": "NDR NDS"}}}
        bands = radiolib.band_summary(config)
        self.assertEqual(bands["dab"]["stations"], ["0xD882"])
        self.assertEqual(bands["dab"]["services"]["0xD882"]["channel"], "7A")
        self.assertEqual(len(bands["dab"]["channels"]), 38)
        self.assertNotIn("min", bands["dab"])
        metadata = radiolib.media_metadata("dab", "0xD882", {"ps": "NDR 2 NDS", "rt": "Song"}, config["names"],
                                           "data:image/jpeg;base64,AA==", config["dabServices"])
        self.assertEqual((metadata["title"], metadata["artist"], metadata["album"], metadata["cover"]),
                         ("Song", "NDR 2 NDS", "DAB+ 7A · NDR NDS", "data:image/jpeg;base64,AA=="))
        # logos named after the service id or the label
        index = radiolib.logo_index(["0xd882.png", "NDR Kultur.png", "96.2.png"])
        self.assertEqual(index["dab"], {"0xD882": "0xd882.png"})
        self.assertEqual(radiolib.find_logo(index, "dab", "0xD383", "NDR Kultur"), "NDR Kultur.png")
        self.assertEqual(radiolib.logo_keys(config, "dab", "0xD383"), ["0xD383", "0xD882"])


class FakeWelleTest(unittest.TestCase):
    def test_fake_mux_is_read_like_welle_cli(self):
        stations = {"dab": [{"channel": "7A", "ensemble": "0x1188", "label": "NDR NDS", "services": [
            {"sid": "0xD882", "label": "NDR 2 NDS", "shortLabel": "NDR 2"}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "stations.json")
            with open(path, "w") as file:
                json.dump(stations, file)
            loaded = fakesdr.load_stations(path)
        ensemble = fakesdr.find_ensemble(loaded, "7a")
        mux = dablib.parse_mux(json.dumps(fakesdr.welle_mux(ensemble, {"0xD882": {"dls": "Song", "mot": 7}}, 1)))
        self.assertEqual(mux["ensemble"]["id"], "0x1188")
        self.assertEqual((mux["services"]["0xD882"]["dls"], mux["services"]["0xD882"]["mot"]), ("Song", 7))
        self.assertIsNone(dablib.parse_mux(json.dumps(fakesdr.welle_mux(None, {}, 1)))["ensemble"])

    def test_bundled_ensembles(self):
        path = os.path.join(TESTS, "..", "tools", "fake-sdr", "stations.json")
        stations = fakesdr.load_stations(path)
        channels = [ensemble["channel"] for ensemble in stations["dab"]]
        self.assertEqual(channels, ["5C", "7A", "8C", "12D"])
        sids = [service["sid"] for ensemble in stations["dab"] for service in ensemble["services"]]
        self.assertEqual(len(sids), len(set(sids)))
        for ensemble in stations["dab"]:
            self.assertIn(ensemble["channel"], dablib.DAB_CHANNELS)
            for service in ensemble["services"]:
                self.assertTrue(service.get("url") or service.get("tone"), service)
                self.assertLessEqual(len(service.get("label", "")), 16)
                for slide in service.get("slides", []):
                    with open(os.path.join(os.path.dirname(path), slide), "rb") as file:
                        self.assertEqual(radiolib.image_type(file.read()), "image/png")
        self.assertIn("0xF001", fakesdr.station_logos(stations, path)["dab"])


if __name__ == "__main__":
    unittest.main()
