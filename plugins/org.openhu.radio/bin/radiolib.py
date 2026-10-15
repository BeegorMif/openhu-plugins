"""Radio helpers without I/O (see tests/test_radiolib.py): bands, commands, scan and RDS parsing."""

import json
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
