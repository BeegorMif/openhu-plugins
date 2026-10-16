"""Simulated RTL-SDR stick for testing the radio plugin without hardware (dev VM, desktop).

Stands in for rtl_fm, rtl_power and redsea (the scripts next to this file): the radio plugin only starts these
programs via PATH, so putting this directory first in PATH is all it takes (radio.py does that when "fakeSdr" is on).

Stations come from a JSON file (OPENHU_FAKE_SDR_STATIONS, default stations.json next to this file):

    {"fm": [{"frequency": 96.2, "name": "NDR 2", "url": "https://.../stream.mp3"},
            {"frequency": 87.6, "name": "TESTTON", "tone": 440}],
     "am": [{"frequency": 1008, "name": "AM TEST", "tone": 800}],
     "error": null}

    url     internet radio stream or local file, decoded with ffmpeg (mp3, aac, HLS, Icecast, ...)
    tone    sine tone in Hz instead of a url (no network, no ffmpeg needed)
    ps      RDS station name, 8 characters (default: the first 8 characters of name)
    pi      RDS PI code, "0xD382" (default: derived from the name, D = Germany); the same PI on two frequencies is
            one programme on two transmitters (tunePi picks the stronger one by level)
    rt      fixed RDS radiotext (default: the current title from the stream's ICY metadata, else the name)
    level   signal level for rtl_power in dB (default -10, noise floor about -40; below -30 the scan skips it)
    logo    station logo, a local PNG/JPEG file (relative to the station list); the radio plugin shows it like a file
            in its logos/ folder (which wins). Only own pictures: the stations' logos are their trademarks.
    error   "no-device" or "busy": rtl_fm and rtl_power fail like the real ones

rtl_fm writes the tuned station to a state file (XDG_RUNTIME_DIR/fake-sdr/state.json), redsea reads it.
"""

import json
import math
import os
import random
import re
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

# Same messages as the real tools, the radio plugin looks for "No supported devices"
ERRORS = {
    "no-device": "No supported devices found.",
    "busy": "usb_claim_interface error -6\nFailed to open rtlsdr device #0.",
}
TOLERANCE = {"fm": 0.05, "am": 4}  # MHz / kHz
DEFAULT_LEVEL = -10.0
NOISE_FLOOR = -40.0


# --- stations ---------------------------------------------------------------------

def stations_path():
    return os.environ.get("OPENHU_FAKE_SDR_STATIONS") or os.path.join(HERE, "stations.json")


def load_stations(path=None):
    """Station file -> {"fm": [...], "am": [...], "error": None|str}; entries without a number are dropped."""
    with open(path or stations_path(), encoding="utf-8") as file:
        data = json.load(file)
    result = {"error": data.get("error")}
    for band in ("fm", "am"):
        stations = []
        for entry in data.get(band, []):
            try:
                frequency = float(entry["frequency"])
            except (KeyError, TypeError, ValueError):
                continue
            stations.append(dict(entry, frequency=frequency))
        result[band] = sorted(stations, key=lambda station: station["frequency"])
    return result


def find_station(stations, band, frequency):
    """Station at frequency (MHz for FM, kHz for AM) within the channel tolerance, else None."""
    for station in stations.get(band, []):
        if abs(station["frequency"] - frequency) <= TOLERANCE[band] + 1e-9:
            return station
    return None


def station_logos(stations, path=None):
    """Logo files of the stations: {"fm": {"96.2": absolute path}, "am": {"1008": ...}} (keys like the radio
    plugin's frequency keys), relative paths are relative to the station list."""
    base = os.path.dirname(os.path.abspath(path or stations_path()))
    result = {}
    for band in ("fm", "am"):
        for station in stations.get(band, []):
            logo = station.get("logo")
            if not logo:
                continue
            key = "%.1f" % station["frequency"] if band == "fm" else "%d" % round(station["frequency"])
            result.setdefault(band, {})[key] = os.path.join(base, os.path.expanduser(str(logo)))
    return result


# --- command lines ----------------------------------------------------------------

def parse_frequency(text):
    """"101.3M" / "1008k" / "100000" -> Hz"""
    match = re.fullmatch(r"\s*([0-9.]+)\s*([kKmMgG]?)\s*", str(text))
    if not match:
        raise ValueError("bad frequency: %r" % text)
    factor = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[match.group(2).lower()]
    return float(match.group(1)) * factor


def parse_rtl_fm_args(argv):
    """rtl_fm arguments -> {"band", "frequency" (MHz/kHz), "rate", "mode"}; unknown options are ignored."""
    options = {"-M": "fm", "-s": "24000"}
    takes_value = {"-f", "-M", "-s", "-r", "-g", "-p", "-l", "-A", "-F", "-E", "-d", "-o", "-t", "-C"}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in takes_value and index + 1 < len(argv):
            # several -E are allowed, the rest is "last one wins"
            options[arg] = argv[index + 1]
            index += 2
        else:
            index += 1
    if "-f" not in options:
        raise ValueError("no frequency (-f)")
    hz = parse_frequency(options["-f"])
    mode = options["-M"]
    rate = int(parse_frequency(options.get("-r") or options["-s"]))
    if mode == "am":
        return {"band": "am", "frequency": round(hz / 1e3), "rate": rate, "mode": mode}
    return {"band": "fm", "frequency": round(hz / 1e6, 2), "rate": rate, "mode": mode}


def parse_power_range(text):
    """rtl_power -f "87.5M:108M:100k" -> (low Hz, high Hz, step Hz)"""
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError("bad range: %r" % text)
    return tuple(parse_frequency(part) for part in parts)


# --- rtl_power output --------------------------------------------------------------

def rtl_power_lines(stations, low, high, step, timestamp=("2026-01-01", "00:00:00"), rng=None, hop=2e6):
    """CSV like rtl_power: date, time, Hz low, Hz high, Hz step, samples, dB, dB, ... (one line per hop)."""
    rng = rng or random.Random(0)
    levels = {}
    for station in stations.get("fm", []):
        center = round(station["frequency"] * 1e6 / step)
        level = float(station.get("level", DEFAULT_LEVEL))
        levels[center] = max(level, levels.get(center, level))
        # a little energy in the neighbouring bins, like a real carrier
        for side in (center - 1, center + 1):
            spill = max(NOISE_FLOOR, level - 15)
            levels[side] = max(spill, levels.get(side, spill))

    count = int(round((high - low) / step)) + 1
    lines = []
    start = 0
    per_hop = max(1, int(round(hop / step)))
    while start < count:
        bins = range(start, min(count, start + per_hop))
        values = []
        for index in bins:
            key = round((low + index * step) / step)
            values.append(levels.get(key, NOISE_FLOOR) + rng.uniform(-1.5, 1.5))
        hop_low = low + bins[0] * step
        hop_high = low + bins[-1] * step + step
        lines.append(", ".join([timestamp[0], timestamp[1], "%d" % hop_low, "%d" % hop_high, "%.2f" % step, "16"]
                               + ["%.2f" % value for value in values]))
        start += per_hop
    return lines


# --- RDS (redsea output) --------------------------------------------------------------

def redsea_line(station, title=None):
    """One redsea-style JSON line for the station: pi, ps (8 characters) and radiotext (64 characters)."""
    name = str(station.get("name") or "")
    ps = str(station.get("ps") or name)
    text = station.get("rt") or title or name
    return json.dumps({"pi": station_pi(station), "ps": ps[:8].ljust(8), "radiotext": str(text)[:64]},
                      ensure_ascii=False)


def station_pi(station):
    """PI code of a station as redsea prints it ("0xD382"): "pi" from the list, else derived from the name."""
    try:
        return "0x%04X" % (int(str(station["pi"]), 16) & 0xFFFF)
    except (KeyError, TypeError, ValueError):
        name = str(station.get("name") or "")
        return "0x%04X" % (0xD000 | (zlib.crc32(name.encode()) & 0x0FFF))  # D = Germany


# --- ICY metadata (Icecast/Shoutcast titles) ---------------------------------------------

def parse_icy_metadata(block):
    """b"StreamTitle='Artist - Title';StreamUrl='';" -> "Artist - Title" (None if there is no title)"""
    text = block.rstrip(b"\0")
    try:
        text = text.decode("utf-8")
    except UnicodeDecodeError:
        text = text.decode("latin-1")
    match = re.search(r"StreamTitle='(.*?)';", text, re.S)
    if not match:
        return None
    return match.group(1).strip() or None


class IcyReader:
    """Strips ICY metadata blocks (every metaint bytes) from a stream, on_title(title) for each new title."""

    def __init__(self, raw, metaint, on_title):
        self.raw = raw
        self.metaint = metaint
        self.on_title = on_title
        self.left = metaint
        self.title = None

    def _read_exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.raw.read(size - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def read(self, size):
        """Up to size audio bytes, b"" at the end of the stream."""
        if self.left == 0:
            length = self._read_exact(1)
            if not length:
                return b""
            block = self._read_exact(length[0] * 16)
            if block:
                title = parse_icy_metadata(block)
                if title and title != self.title:
                    self.title = title
                    self.on_title(title)
            self.left = self.metaint
        data = self.raw.read(min(size, self.left))
        self.left -= len(data)
        return data


def playlist_url(text):
    """First stream URL of an m3u or pls playlist, else None."""
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:
            line = line.split("=", 1)[1].strip()
        if re.match(r"https?://", line):
            return line
    return None


# --- audio ------------------------------------------------------------------------------

def tone(rate, frequency, amplitude=0.3, seconds=1):
    """Sine as s16le mono; whole seconds and an integer frequency, so the buffer loops without a click."""
    count = int(rate * seconds)
    scale = 32767 * amplitude
    return struct.pack("<%dh" % count, *(int(scale * math.sin(2 * math.pi * frequency * i / rate))
                                         for i in range(count)))


def noise(rate, amplitude=0.02, seconds=1, seed=1):
    """Quiet white noise as s16le mono, like a receiver between stations."""
    rng = random.Random(seed)
    count = int(rate * seconds)
    scale = 32767 * amplitude
    return struct.pack("<%dh" % count, *(int(rng.uniform(-scale, scale)) for _ in range(count)))


def ffmpeg_command(source, rate, band, rds, from_stdin=False):
    """ffmpeg arguments: source -> s16le mono at rate on stdout (AM band limited, FM multiplex pre-emphasised)."""
    args = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error"]
    if from_stdin:
        args += ["-i", "pipe:0"]
    elif re.match(r"[a-z]+://", source):
        args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", source]
    else:
        # local file: real time and endless, like a live station
        args += ["-re", "-stream_loop", "-1", "-i", source]
    filters = []
    if band == "am":
        filters.append("highpass=f=100,lowpass=f=4500")
    elif rds:
        # the plugin's sox applies the 50 us de-emphasis to the multiplex: emphasise first so the sound stays bright
        # (measured with NDR 2: peaks at -5 dBFS, no clipping, same loudness as without RDS)
        filters.append("aemphasis=type=50fm:mode=production")
    if filters:
        args += ["-af", ",".join(filters)]
    return args + ["-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]


# --- state shared between rtl_fm and redsea ----------------------------------------------

def state_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(tempfile.gettempdir(), "fake-sdr-%d" % os.getuid())
    return os.path.join(base, "fake-sdr", "state.json")


def write_state(state):
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def read_state():
    try:
        with open(state_path(), encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def clear_state(pid):
    """Removes the state file if it still belongs to this rtl_fm (a newer one may have replaced it)."""
    if read_state().get("pid") == pid:
        try:
            os.remove(state_path())
        except OSError:
            pass


def process_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fail(error):
    print(ERRORS.get(error, error), file=sys.stderr)
    sys.exit(1)
