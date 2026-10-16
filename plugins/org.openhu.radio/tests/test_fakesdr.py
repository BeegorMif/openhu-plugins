import importlib.util
import io
import json
import math
import os
import shutil
import struct
from http.server import BaseHTTPRequestHandler
import subprocess
import socketserver
import sys
import tempfile
import threading
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAKE_SDR = os.path.join(TESTS, "..", "tools", "fake-sdr")
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, FAKE_SDR)
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))
import fakesdr  # noqa: E402
import radiolib  # noqa: E402

STATIONS = {
    "fm": [
        {"frequency": 87.6, "name": "Testton 440 Hz", "ps": "TESTTON", "tone": 440},
        {"frequency": 96.2, "name": "NDR 2", "url": "https://example.invalid/ndr2.mp3"},
        {"frequency": 103.0, "name": "Weak", "tone": 1000, "level": -35},
        {"frequency": 108.0, "name": "Edge", "tone": 600},
    ],
    "am": [{"frequency": 1008, "name": "AM TEST", "tone": 800}],
    "error": None,
}


def rms(data):
    count = len(data) // 2
    samples = struct.unpack("<%dh" % count, data[:count * 2])
    return math.sqrt(sum(sample * sample for sample in samples) / count) / 32767


class FakeSdrTest(unittest.TestCase):
    def test_rtl_fm_arguments_of_the_plugin(self):
        args, rate = radiolib.rtl_fm_command("fm", 96.2, {"gain": 30}, rds=False)
        self.assertEqual(fakesdr.parse_rtl_fm_args(args[1:]),
                         {"band": "fm", "frequency": 96.2, "rate": rate, "mode": "wbfm"})
        args, rate = radiolib.rtl_fm_command("fm", 101.9, {"ppm": 2}, rds=True)
        self.assertEqual(fakesdr.parse_rtl_fm_args(args[1:]),
                         {"band": "fm", "frequency": 101.9, "rate": 171000, "mode": "fm"})
        args, rate = radiolib.rtl_fm_command("am", 1008, {}, rds=False)
        self.assertEqual(fakesdr.parse_rtl_fm_args(args[1:]),
                         {"band": "am", "frequency": 1008, "rate": 48000, "mode": "am"})
        with self.assertRaises(ValueError):
            fakesdr.parse_rtl_fm_args(["-M", "wbfm", "-"])

    def test_find_station(self):
        stations = {"fm": [dict(entry) for entry in STATIONS["fm"]], "am": STATIONS["am"]}
        self.assertEqual(fakesdr.find_station(stations, "fm", 96.2)["name"], "NDR 2")
        self.assertEqual(fakesdr.find_station(stations, "fm", 96.25)["name"], "NDR 2")
        self.assertIsNone(fakesdr.find_station(stations, "fm", 96.3))
        self.assertEqual(fakesdr.find_station(stations, "am", 1010)["name"], "AM TEST")
        self.assertIsNone(fakesdr.find_station(stations, "am", 999))

    def test_rtl_power_output_is_found_by_the_plugin_scan(self):
        low, high, step = fakesdr.parse_power_range("87.5M:108M:100k")
        lines = fakesdr.rtl_power_lines(STATIONS, low, high, step)
        self.assertGreater(len(lines), 5)
        # weak station (-35 dB) stays below the scan threshold, the band edge 108.0 is included
        self.assertEqual(radiolib.parse_rtl_power(lines), [87.6, 96.2, 108.0])

    def test_redsea_line(self):
        line = fakesdr.redsea_line({"name": "NDR 1 Niedersachsen", "pi": "0xd481"}, "Artist - Title")
        self.assertEqual(radiolib.parse_redsea(line), {"pi": "0xD481", "ps": "NDR 1 Ni", "rt": "Artist - Title"})
        line = fakesdr.redsea_line({"name": "Testton", "ps": "TESTTON", "rt": "fixed", "pi": "D3FF"}, "ignored")
        self.assertEqual(radiolib.parse_redsea(line), {"pi": "0xD3FF", "ps": "TESTTON", "rt": "fixed"})
        # without "pi": derived from the name, always the same, D = Germany
        derived = radiolib.parse_redsea(fakesdr.redsea_line({"name": "N-JOY"}))["pi"]
        self.assertRegex(derived, r"^0xD[0-9A-F]{3}$")
        self.assertEqual(fakesdr.station_pi({"name": "N-JOY", "pi": "none"}), derived)
        self.assertEqual(radiolib.parse_redsea(fakesdr.redsea_line({"name": "N-JOY"}))["rt"], "N-JOY")
        self.assertEqual(len(json.loads(fakesdr.redsea_line({"name": "x"}, "y" * 100))["radiotext"]), 64)

    def test_icy_metadata(self):
        def block(text):
            data = text.encode("utf-8")
            data += b"\0" * (-len(data) % 16)
            return bytes([len(data) // 16]) + data

        stream = (b"A" * 16 + block("StreamTitle='Band - Song';StreamUrl='';") + b"B" * 16 + b"\0"
                  + b"C" * 16 + block("StreamTitle='Zweiter Titel';") + b"D" * 5)
        titles = []
        reader = fakesdr.IcyReader(io.BytesIO(stream), 16, titles.append)
        audio = b""
        while True:
            data = reader.read(7)
            if not data:
                break
            audio += data
        self.assertEqual(audio, b"A" * 16 + b"B" * 16 + b"C" * 16 + b"D" * 5)
        self.assertEqual(titles, ["Band - Song", "Zweiter Titel"])
        self.assertEqual(fakesdr.parse_icy_metadata("StreamTitle='Grüße';".encode("latin-1")),
                         "Grüße")
        self.assertIsNone(fakesdr.parse_icy_metadata(b"StreamTitle='';"))

    def test_playlists(self):
        self.assertEqual(fakesdr.playlist_url("#EXTM3U\n#EXTINF:-1,x\nhttp://a/b.mp3\n"), "http://a/b.mp3")
        self.assertEqual(fakesdr.playlist_url("[playlist]\nFile1=https://c/d\nTitle1=x\n"), "https://c/d")
        self.assertIsNone(fakesdr.playlist_url("nothing here"))

    def test_ffmpeg_command(self):
        args = fakesdr.ffmpeg_command("https://x/y.mp3", 171000, "fm", True)
        self.assertIn("-reconnect", args)
        self.assertIn("aemphasis", args[args.index("-af") + 1])
        self.assertEqual(args[-8:], ["-vn", "-ac", "1", "-ar", "171000", "-f", "s16le", "pipe:1"])
        args = fakesdr.ffmpeg_command("/music/test.mp3", 48000, "fm", False)
        self.assertIn("-stream_loop", args)
        self.assertNotIn("-af", args)
        args = fakesdr.ffmpeg_command("", 48000, "am", False, from_stdin=True)
        self.assertIn("pipe:0", args)
        self.assertIn("lowpass", args[args.index("-af") + 1])

    def test_audio_buffers(self):
        buffer = fakesdr.tone(8000, 440)
        self.assertEqual(len(buffer), 16000)
        self.assertAlmostEqual(rms(buffer), 0.3 / math.sqrt(2), places=2)
        self.assertLess(rms(fakesdr.noise(8000)), 0.02)

    def test_bundled_station_list(self):
        stations = fakesdr.load_stations(os.path.join(FAKE_SDR, "stations.json"))
        self.assertIsNone(stations["error"])
        self.assertGreaterEqual(len(stations["fm"]), 5)
        for band in ("fm", "am"):
            frequencies = [station["frequency"] for station in stations[band]]
            self.assertEqual(len(frequencies), len(set(frequencies)))
            for station in stations[band]:
                self.assertEqual(radiolib.clamp_frequency(band, station["frequency"]), station["frequency"])
                self.assertTrue(station.get("url") or station.get("tone"), station)
                self.assertLessEqual(len(station.get("ps", "")), 8)
                if "pi" in station:
                    self.assertEqual(radiolib.normalize_pi(station["pi"]), station["pi"])
        # every FM station is found by the scan
        low, high, step = fakesdr.parse_power_range("87.5M:108M:100k")
        self.assertEqual(radiolib.parse_rtl_power(fakesdr.rtl_power_lines(stations, low, high, step)),
                         [station["frequency"] for station in stations["fm"]])


class ProcessTestCase(unittest.TestCase):
    """Runs the scripts as the plugin does, with their own station and state files."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.stations = os.path.join(self.dir, "stations.json")
        self.write_stations(STATIONS)
        self.env = dict(os.environ, OPENHU_FAKE_SDR_STATIONS=self.stations, XDG_RUNTIME_DIR=self.dir,
                        OPENHU_FAKE_SDR_SCAN_SECONDS="0")
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        shutil.rmtree(self.dir)

    def write_stations(self, stations):
        with open(self.stations, "w") as file:
            json.dump(stations, file)

    def start(self, *args, **kwargs):
        process = subprocess.Popen([os.path.join(FAKE_SDR, args[0])] + list(args[1:]), env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        self.processes.append(process)
        return process

    def read_audio(self, process, seconds, rate):
        size = int(seconds * rate) * 2
        data = b""
        while len(data) < size:
            chunk = process.stdout.read1(size - len(data))
            if not chunk:
                break
            data += chunk
        return data


class FakeSdrProcessTest(ProcessTestCase):
    """Tone stations: no network, no ffmpeg."""

    def test_rtl_fm_tone_station_and_state(self):
        args, rate = radiolib.rtl_fm_command("fm", 87.6, {}, rds=False)
        process = self.start(*args)
        started = time.monotonic()
        audio = self.read_audio(process, 0.5, rate)
        self.assertEqual(len(audio), int(0.5 * rate) * 2)
        self.assertGreater(rms(audio), 0.15)
        # paced to real time: one second of audio is not there much faster than in one second
        self.read_audio(process, 1.0, rate)
        self.assertGreater(time.monotonic() - started, 0.9)

        with open(os.path.join(self.dir, "fake-sdr", "state.json")) as file:
            state = json.load(file)
        self.assertEqual(state["pid"], process.pid)
        self.assertEqual(state["station"]["ps"], "TESTTON")

        process.terminate()
        self.assertEqual(process.wait(5), 0)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "fake-sdr", "state.json")))

    def test_rtl_fm_noise_between_stations(self):
        args, rate = radiolib.rtl_fm_command("fm", 99.9, {}, rds=False)
        process = self.start(*args)
        audio = self.read_audio(process, 0.2, rate)
        self.assertEqual(len(audio), int(0.2 * rate) * 2)
        self.assertLess(rms(audio), 0.02)

    def test_rtl_fm_errors(self):
        for error, message in (("no-device", "No supported devices"), ("busy", "usb_claim_interface")):
            self.write_stations(dict(STATIONS, error=error))
            process = self.start("rtl_fm", "-f", "96.2M", "-")
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1)
            self.assertIn(message, stderr.decode())
            process = self.start("rtl_power", "-f", "87.5M:108M:100k", "-1", "-")
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1)

    def test_redsea_follows_rtl_fm(self):
        args, rate = radiolib.rtl_fm_command("fm", 87.6, {}, rds=True)
        rtl = self.start(*args)
        redsea = self.start("redsea", "-r", "171k", stdin=subprocess.PIPE)
        # the multiplex goes to redsea like in the plugin
        redsea.stdin.write(self.read_audio(rtl, 0.2, rate))
        redsea.stdin.flush()
        line = redsea.stdout.readline().decode()
        self.assertEqual(radiolib.parse_redsea(line),
                         {"pi": fakesdr.station_pi(STATIONS["fm"][0]), "ps": "TESTTON", "rt": "Testton 440 Hz"})
        redsea.stdin.close()
        self.assertEqual(redsea.wait(5), 0)

    def test_rtl_power_scan(self):
        process = self.start("rtl_power", "-f", "87.5M:108M:100k", "-i", "2", "-1", "-")
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(radiolib.parse_rtl_power(stdout.decode().splitlines()), [87.6, 96.2, 108.0])

    @unittest.skipUnless(shutil.which("sox"), "sox not installed")
    def test_rds_multiplex_through_the_plugins_sox(self):
        args, rate = radiolib.rtl_fm_command("fm", 87.6, {}, rds=True)
        multiplex = self.read_audio(self.start(*args), 1.0, rate)
        sox = subprocess.run(radiolib.sox_mpx_to_audio(), input=multiplex, capture_output=True, timeout=30)
        self.assertEqual(sox.returncode, 0, sox.stderr.decode())
        self.assertGreater(len(sox.stdout), 44100)
        self.assertGreater(rms(sox.stdout[len(sox.stdout) // 2:]), 0.1)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_rtl_fm_local_file_with_ffmpeg(self):
        sample = os.path.join(self.dir, "sample.wav")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=2",
                        sample], check=True)
        self.write_stations({"fm": [{"frequency": 96.2, "name": "FILE", "url": sample}], "error": None})
        args, rate = radiolib.rtl_fm_command("fm", 96.2, {}, rds=True)
        process = self.start(*args)
        audio = self.read_audio(process, 2.5, rate)
        # noise while ffmpeg starts, then the file: lavfi sine at 1/8 full scale (RMS about 0.09 with the
        # pre-emphasis); the noise stays below 0.012
        self.assertGreater(rms(audio[-int(0.5 * rate) * 2:]), 0.03)


class IcyHandler(BaseHTTPRequestHandler):
    """Icecast-like stream: audio with a title every 8192 bytes, closes after one pass (a dropped connection)."""
    audio = b""
    connections = 0

    def do_GET(self):
        IcyHandler.connections += 1
        metaint = 8192 if self.headers.get("Icy-MetaData") == "1" else 0
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        if metaint:
            self.send_header("icy-metaint", str(metaint))
        self.end_headers()
        title = ("StreamTitle='Testband - Lied %d';" % IcyHandler.connections).encode()
        title += b"\0" * (-len(title) % 16)
        try:
            for start in range(0, len(self.audio), metaint or len(self.audio)):
                self.wfile.write(self.audio[start:start + (metaint or len(self.audio))])
                if metaint:
                    self.wfile.write(bytes([len(title) // 16]) + title)
        except OSError:
            pass

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FakeSdrStreamTest(ProcessTestCase):
    def test_stream_title_and_reconnect(self):
        sample = os.path.join(self.dir, "sample.mp3")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=2",
                        "-b:a", "64k", sample], check=True)
        with open(sample, "rb") as file:
            IcyHandler.audio = file.read()
        IcyHandler.connections = 0
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), IcyHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:%d/stream.mp3" % server.server_address[1]
        self.write_stations({"fm": [{"frequency": 96.2, "name": "NDR 2", "url": url}], "error": None})

        args, rate = radiolib.rtl_fm_command("fm", 96.2, {}, rds=False)
        process = self.start(*args)
        state_file = os.path.join(self.dir, "fake-sdr", "state.json")
        # the whole file arrives at once (like an Icecast burst), then the server closes the connection:
        # rtl_fm keeps running (noise) and connects again after a few seconds
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and IcyHandler.connections < 2:
            self.read_audio(process, 0.2, rate)
        self.assertGreaterEqual(IcyHandler.connections, 2)
        self.assertIsNone(process.poll())
        with open(state_file) as file:
            self.assertRegex(json.load(file)["title"], r"^Testband - Lied \d$")


@unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets not installed")
class RadioPluginFakeSdrTest(unittest.TestCase):
    def test_switching_puts_the_fake_tools_first(self):
        import radio
        with tempfile.TemporaryDirectory() as data:
            radio.DATA_DIR = data
            plugin = radio.RadioPlugin()
            plugin.config["fakeSdr"] = False
            os.environ.pop("OPENHU_FAKE_SDR", None)
            self.assertFalse(plugin.simulated())
            plugin.config["fakeSdr"] = True
            self.assertTrue(plugin.simulated())
            self.assertEqual(os.path.dirname(plugin.which("rtl_fm")), radio.FAKE_SDR_DIR)
            self.assertEqual(os.path.dirname(plugin.which("redsea")), radio.FAKE_SDR_DIR)
            env = plugin.environment()
            if "OPENHU_FAKE_SDR_STATIONS" not in os.environ:
                self.assertEqual(env["OPENHU_FAKE_SDR_STATIONS"], os.path.join(radio.FAKE_SDR_DIR, "stations.json"))
                with open(os.path.join(data, "fake-sdr-stations.json"), "w") as file:
                    file.write("{}")
                self.assertEqual(plugin.environment()["OPENHU_FAKE_SDR_STATIONS"],
                                 os.path.join(data, "fake-sdr-stations.json"))


if __name__ == "__main__":
    unittest.main()
