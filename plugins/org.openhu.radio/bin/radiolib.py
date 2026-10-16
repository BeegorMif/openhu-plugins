"""Radio helpers without I/O (see tests/test_radiolib.py): bands, commands, scan, RDS parsing and station logos."""

import base64
import json
import os
import statistics

BANDS = {
    # MHz for FM, kHz for AM
    "fm": {"min": 87.5, "max": 108.0, "step": 0.1, "unit": "MHz", "default": 101.3},
    "am": {"min": 531, "max": 1602, "step": 9, "unit": "kHz", "default": 1008},
}


def clamp_frequency(band, frequency):
    spec = BANDS[band]
    frequency = min(spec["max"], max(spec["min"], float(frequency)))
    # snap to the channel raster
    steps = round((frequency - spec["min"]) / spec["step"])
    value = spec["min"] + steps * spec["step"]
    return round(value, 1) if band == "fm" else int(round(value))


def step_frequency(band, frequency, direction):
    spec = BANDS[band]
    value = frequency + spec["step"] * (1 if direction > 0 else -1)
    # wrap around at the band edges
    if value > spec["max"] + 1e-6:
        value = spec["min"]
    elif value < spec["min"] - 1e-6:
        value = spec["max"]
    return clamp_frequency(band, value)


def rtl_fm_command(band, frequency, config, rds):
    """rtl_fm arguments; output is raw signed 16 bit mono at the returned sample rate."""
    args = ["rtl_fm"]
    if config.get("gain") not in (None, "", "auto"):
        args += ["-g", str(config["gain"])]
    if config.get("ppm"):
        args += ["-p", str(config["ppm"])]
    if band == "fm" and rds:
        # FM multiplex for redsea, audio is filtered from it
        return args + ["-M", "fm", "-l", "0", "-A", "std", "-s", "171k", "-F", "9", "-f", "%.1fM" % frequency, "-"], 171000
    if band == "fm":
        return args + ["-M", "wbfm", "-f", "%.1fM" % frequency, "-r", "48000", "-"], 48000
    return args + ["-M", "am", "-s", "12k", "-r", "48000"] + list(config.get("amOptions", ["-E", "direct2"])) + \
        ["-f", "%dk" % frequency, "-"], 48000


def sox_mpx_to_audio():
    """FM multiplex (171 kHz) -> mono audio 44.1 kHz with 15 kHz low pass and 50 us de-emphasis.
    deemph only works at 44.1/48 kHz, so the rate conversion has to come before it."""
    return ["sox", "-t", "raw", "-r", "171k", "-e", "signed", "-b", "16", "-c", "1", "-",
            "-t", "raw", "-r", "44100", "-e", "signed", "-b", "16", "-c", "1", "-",
            "sinc", "-15k", "rate", "44100", "deemph"]


def pacat_command(rate):
    return ["pacat", "--raw", "--format=s16le", "--rate=%d" % rate, "--channels=1",
            "--client-name=OpenHU", "--stream-name=Radio"]


def start_needed(playing, running):
    """play: start only if the radio does not play already. Android Auto sends "unmute" (-> play) when it connects;
    restarting the processes then made the running radio stutter."""
    return not (playing and running)


def frequency_key(band, frequency):
    """Key of a frequency in the remembered station names: "96.2" (FM) / "1008" (AM)."""
    return "%.1f" % frequency if band == "fm" else "%d" % round(frequency)


def remember_name(names, band, frequency, ps):
    """Stores the RDS name of a frequency in names ({band: {key: name}}); True if it changed."""
    ps = (ps or "").strip()
    if not ps:
        return False
    band_names = names.setdefault(band, {})
    key = frequency_key(band, frequency)
    if band_names.get(key) == ps:
        return False
    band_names[key] = ps
    return True


def band_summary(config):
    """Both bands for radio.state "bands": range, stations, presets and remembered names (e.g. for Android Auto,
    which lists the stations of all bands)."""
    result = {}
    for band, spec in BANDS.items():
        result[band] = {
            "min": spec["min"],
            "max": spec["max"],
            "step": spec["step"],
            "unit": spec["unit"],
            "stations": config.get("stations", {}).get(band, []),
            "presets": config.get("presets", {}).get(band, []),
            "names": config.get("names", {}).get(band, {}),
        }
    return result


def frequency_label(band, frequency):
    """"UKW 96,2 MHz" / "MW 1008 kHz" """
    if band == "fm":
        return "UKW %s MHz" % ("%.1f" % frequency).replace(".", ",")
    return "MW %d kHz" % round(frequency)


def media_metadata(band, frequency, rds, names, cover=""):
    """media.metadata of the station that plays (home page, Bluetooth car radio, API): radiotext as the title, the
    station name as the artist, the station logo (data URL) as the cover."""
    name = (rds.get("ps") or "").strip() or names.get(band, {}).get(frequency_key(band, frequency), "")
    label = frequency_label(band, frequency)
    return {
        "title": (rds.get("rt") or "").strip() or name or label,
        "artist": name or label,
        "album": label,
        "playlist": "",
        "duration": 0,
        "cover": cover or "",
        "source": "radio",
    }


# --- station logos ----------------------------------------------------------------------
# Files the user puts into logos/ in the plugin's data dir (none are bundled: the logos are the stations' trademarks),
# named after the frequency ("96.2.png", "1008.jpg") or the station name ("NDR 2.png"). Nothing from the internet.

LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg")
# The logos travel as data URLs over the API (radio.logos, media.metadata.cover); OpenHU scales them down for
# Android Auto. Bigger files are skipped: 256x256 is plenty.
MAX_LOGO_BYTES = 512 * 1024


def image_type(data):
    """MIME type of PNG/JPEG bytes, None for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def data_url(data):
    """PNG/JPEG bytes -> "data:image/png;base64,...", None for other files."""
    kind = image_type(data)
    return "data:%s;base64,%s" % (kind, base64.b64encode(data).decode("ascii")) if kind else None


def name_key(name):
    """Station name for matching logo files: case, spaces and punctuation do not count ("NDR 2" = "ndr2.png")."""
    return "".join(char for char in (name or "").casefold() if char.isalnum())


def logo_index(files):
    """File names in logos/ -> {"fm": {"96.2": file}, "am": {"1008": file}, "name": {"ndr2": file}}.
    A name that is a frequency of a band ("96.2", "96,2", "1008") is that frequency, everything else a station name."""
    index = {band: {} for band in BANDS}
    index["name"] = {}
    for file in sorted(files):
        stem, extension = os.path.splitext(file)
        if extension.lower() not in LOGO_EXTENSIONS or not stem.strip():
            continue
        try:
            value = float(stem.strip().replace(",", "."))
        except ValueError:
            value = None
        band = next((band for band, spec in BANDS.items()
                     if value is not None and spec["min"] <= value <= spec["max"]), None)
        if band:
            index[band].setdefault(frequency_key(band, value), file)
        elif name_key(stem):
            index["name"].setdefault(name_key(stem), file)
    return index


def find_logo(index, band, key, name=""):
    """Logo file of a station: named after its frequency key, else after its (remembered RDS) name; None if none."""
    return index.get(band, {}).get(key) or index["name"].get(name_key(name))


def logo_keys(config, band, frequency=None):
    """Frequency keys of a band that can have a logo: scanned stations, presets, remembered names, current station."""
    frequencies = list(config.get("stations", {}).get(band, [])) + list(config.get("presets", {}).get(band, []))
    if frequency is not None:
        frequencies.append(frequency)
    keys = {frequency_key(band, value) for value in frequencies}
    keys.update(config.get("names", {}).get(band, {}))
    return sorted(keys)


# Media keys while the radio is the current media source (OpenHU sends them to the source, not to the phone, then)
MEDIA_KEY_COMMANDS = {
    "media.next": {"cmd": "seek", "value": 1},
    "media.previous": {"cmd": "seek", "value": -1},
    "media.play_pause": {"cmd": "toggle"},
    "media.play": {"cmd": "play"},
    "media.pause": {"cmd": "stop"},
}


def action_command(action, radio_is_source):
    """radio.command for an input action, None if the radio does not handle it."""
    if action == "radio.toggle":
        return {"cmd": "toggle"}
    if action in ("radio.next", "radio.previous"):
        return {"cmd": "seek", "value": 1 if action == "radio.next" else -1}
    if radio_is_source and action in MEDIA_KEY_COMMANDS:
        return dict(MEDIA_KEY_COMMANDS[action])
    return None


def parse_rtl_power(lines, threshold_db=10.0):
    """rtl_power CSV -> frequencies (MHz, 0.1 raster) of stations clearly above the noise floor."""
    bins = {}
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            low, step = float(parts[2]), float(parts[4])
            values = [float(value) for value in parts[6:]]
        except ValueError:
            continue
        for index, value in enumerate(values):
            frequency = round((low + step * index) / 1e6, 1)
            bins[frequency] = max(value, bins.get(frequency, value))
    if not bins:
        return []

    floor = statistics.median(bins.values())
    frequencies = sorted(bins)
    stations = []
    for index, frequency in enumerate(frequencies):
        level = bins[frequency]
        neighbours = [bins[frequencies[j]] for j in (index - 1, index + 1) if 0 <= j < len(frequencies)]
        if level >= floor + threshold_db and all(level >= other for other in neighbours):
            stations.append(frequency)
    return stations


def parse_redsea(line):
    """One redsea JSON line -> {"ps": ..., "rt": ...} with the fields it contains."""
    try:
        data = json.loads(line)
    except ValueError:
        return {}
    result = {}
    if data.get("ps"):
        result["ps"] = data["ps"].strip()
    if data.get("radiotext"):
        result["rt"] = data["radiotext"].strip()
    return result
