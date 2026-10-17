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

# Events of one channel as openhu-dab writes them (native/openhu-dab/openhu-dab.cpp)
EVENTS_7A = [
    '{"event":"tuned","channel":"7A","frequency":188928}',
    '{"event":"sync","channel":"7A","synced":true}',
    '{"event":"service","channel":"7A","sid":"0xD882","label":"NDR 2 NDS","shortLabel":"NDR 2","audio":true,'
    '"dabPlus":true,"bitrate":96}',
    '{"event":"ensemble","channel":"7A","id":"0x1188","label":"NDR NDS","ecc":"0xE0"}',
    '{"event":"service","channel":"7A","sid":"0xd383","label":"NDR Kultur","shortLabel":"NDR Kult","audio":true}',
    '{"event":"service","channel":"7A","sid":"0xE0D03188","label":"NDR EPG","audio":false}',
    'some debug output of the DAB library',
    '{"event":"channel","channel":"7A","ensemble":true,"services":3}',
]


class DabLibTest(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(dablib.normalize_sid("0xd882"), "0xD882")
        self.assertEqual(dablib.normalize_sid("D882"), "0xD882")
        self.assertEqual(dablib.normalize_sid(0xD882), "0xD882")
        self.assertEqual(dablib.normalize_sid("0xe0d03188"), "0xE0D03188")
        for bad in (None, "", "xyz", 0, True, -1, 0x100000000):
            self.assertIsNone(dablib.normalize_sid(bad), bad)
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
        tool = "/plugin/bin/amd64/openhu-dab"
        self.assertEqual(dablib.play_command(tool, "7A", "0xD882", {"gain": "auto"}, 5, "/run/slides"),
                         [tool, "--channel", "7A", "--service", "0xD882", "--rate", "48000", "--events-fd", "5",
                          "--slides", "/run/slides"])
        args = dablib.play_command(tool, "5C", "0xD210", {"gain": 30, "ppm": 12, "biasTee": True}, 3)
        self.assertEqual(args[-5:], ["--gain", "30", "--ppm", "12", "--bias-tee"])
        self.assertNotIn("--slides", args)
        self.assertEqual(dablib.scan_command(tool, ["5C", "7A"], {"dabSyncSeconds": 2, "dabScanSeconds": 8}, 4),
                         [tool, "--scan", "--channels", "5C,7A", "--events-fd", "4", "--sync-seconds", "2",
                          "--scan-seconds", "8"])
        self.assertEqual(radiolib.pacat_command(48000, 2)[3:5], ["--rate=48000", "--channels=2"])

    def test_events(self):
        self.assertEqual(dablib.parse_event(b'{"event":"dls","sid":"0xd882","text":"Song"}'),
                         {"event": "dls", "sid": "0xD882", "text": "Song"})
        for line in ("", "debug output", "[1, 2]", '{"no":"event"}', '{"event": 3}'):
            self.assertIsNone(dablib.parse_event(line), line)
        self.assertEqual(dablib.ensemble_info({"id": "0x1188", "label": " NDR NDS ", "ecc": "0xe0"}),
                         {"id": "0x1188", "label": "NDR NDS", "ecc": "0xE0"})
        self.assertEqual(dablib.ensemble_info({"id": "0x1188", "label": "X", "ecc": ""})["ecc"], "")

    def test_tools(self):
        self.assertEqual(dablib.machine_arch("x86_64"), "amd64")
        self.assertEqual(dablib.machine_arch("aarch64"), "arm64")
        self.assertEqual(dablib.machine_arch("riscv64"), "riscv64")
        stderr = ("/home/openhu/.openhu/plugins/org.openhu.radio/bin/arm64/openhu-dab: error while loading shared "
                  "libraries: librtlsdr.so.0: cannot open shared object file: No such file or directory")
        self.assertEqual(dablib.missing_library(stderr), "librtlsdr.so.0")
        self.assertIsNone(dablib.missing_library("No supported devices found."))
        self.assertEqual(dablib.library_package("libfaad.so.2"), "libfaad2")
        self.assertEqual(dablib.library_package("libliquid.so.1"), "libliquid1")
        self.assertEqual(dablib.library_package("libunknown.so.1"), "")
        with tempfile.TemporaryDirectory() as plugin:
            self.assertIsNone(dablib.native_tool(plugin, "openhu-dab", "arm64"))
            os.makedirs(os.path.join(plugin, "bin", "arm64"))
            path = os.path.join(plugin, "bin", "arm64", "openhu-dab")
            with open(path, "w") as file:
                file.write("#!/bin/sh\n")
            self.assertIsNone(dablib.native_tool(plugin, "openhu-dab", "arm64"))  # not executable
            os.chmod(path, 0o755)
            self.assertEqual(dablib.native_tool(plugin, "openhu-dab", "arm64"), path)
            self.assertIsNone(dablib.native_tool(plugin, "openhu-dab", "amd64"))

    def test_scan(self):
        result = dablib.ScanResult()
        for line in EVENTS_7A:
            event = dablib.parse_event(line)
            if event:
                result.add(event)
        found_7a = result.found()["7A"]
        # audio services with a label; the label may come before the ensemble
        self.assertEqual(set(found_7a), {"0xD882", "0xD383"})
        self.assertEqual(found_7a["0xD882"], {"label": "NDR 2 NDS", "shortLabel": "NDR 2", "channel": "7A",
                                              "ensemble": "0x1188", "ensembleLabel": "NDR NDS", "ecc": "0xE0"})
        self.assertEqual(result.count(), 2)
        # services without an ensemble (lost during the scan) do not count
        result.add({"event": "service", "channel": "9A", "sid": "0xD001", "label": "Lost", "audio": True})
        self.assertNotIn("9A", result.found())
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


class FakeStationsTest(unittest.TestCase):
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
