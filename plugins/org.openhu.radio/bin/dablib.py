"""DAB/DAB+ helpers without I/O (see tests/test_dablib.py): channels, service ids, openhu-dab commands and events.

Reception and decoding is done by openhu-dab (native/openhu-dab, shipped in the plugin archive as
bin/<arch>/openhu-dab, built on dab-cmdline's DAB library). It tunes one channel (ensemble) and writes the service's
audio as raw PCM (s16le, stereo, 48 kHz) to stdout, which goes straight to pacat; ensemble, services, DLS and the
slideshow arrive as JSON lines on a separate file descriptor (--events-fd). No network port.
"""

import json
import os
import platform
import re

# Band III channels (ETSI EN 300 401) with their centre frequency in kHz. Germany uses 5A-13F; the "N" channels of
# some countries are left out.
DAB_CHANNELS = {
    "5A": 174928, "5B": 176640, "5C": 178352, "5D": 180064,
    "6A": 181936, "6B": 183648, "6C": 185360, "6D": 187072,
    "7A": 188928, "7B": 190640, "7C": 192352, "7D": 194064,
    "8A": 195936, "8B": 197648, "8C": 199360, "8D": 201072,
    "9A": 202928, "9B": 204640, "9C": 206352, "9D": 208064,
    "10A": 209936, "10B": 211648, "10C": 213360, "10D": 215072,
    "11A": 216928, "11B": 218640, "11C": 220352, "11D": 222064,
    "12A": 223936, "12B": 225648, "12C": 227360, "12D": 229072,
    "13A": 230784, "13B": 232496, "13C": 234208, "13D": 235776, "13E": 237488, "13F": 239200,
}
CHANNEL_ORDER = {channel: index for index, channel in enumerate(DAB_CHANNELS)}
# openhu-dab resamples every service to this rate, so pacat never has to restart
PCM_RATE = 48000

# Debian architecture names (the plugin archive's bin/<arch>/)
MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armhf",
            "armv6l": "armhf"}

# Shared libraries of openhu-dab and redsea -> Debian trixie package (for the message when one is missing)
LIBRARY_PACKAGES = {
    "librtlsdr.so": "librtlsdr0",
    "libfaad.so": "libfaad2",
    "libfftw3f.so": "libfftw3-single3",
    "libsamplerate.so": "libsamplerate0",
    "libliquid.so": "libliquid1",
    "libsndfile.so": "libsndfile1",
    "libusb-1.0.so": "libusb-1.0-0",
}
MISSING_LIBRARY = re.compile(r"error while loading shared libraries: ([^:\s]+)")


def machine_arch(machine=None):
    """Debian architecture of this machine ("amd64", "arm64"); the machine name itself if unknown."""
    machine = (machine or platform.machine()).lower()
    return MACHINES.get(machine, machine)


def native_tool(plugin_dir, name, arch=None):
    """Path of a tool shipped in the plugin archive (bin/<arch>/<name>), None if it is not there."""
    path = os.path.join(plugin_dir, "bin", arch or machine_arch(), name)
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


def missing_library(stderr):
    """The shared library the dynamic loader did not find ("librtlsdr.so.0"), None if that was not the problem."""
    match = MISSING_LIBRARY.search(stderr or "")
    return match.group(1) if match else None


def library_package(library):
    """Debian package of a shared library ("librtlsdr.so.0" -> "librtlsdr0"), "" if unknown."""
    for prefix, package in LIBRARY_PACKAGES.items():
        if (library or "").startswith(prefix):
            return package
    return ""


def normalize_channel(value):
    """"7a" -> "7A", None if it is no Band III channel."""
    channel = str(value or "").strip().upper()
    return channel if channel in DAB_CHANNELS else None


def normalize_sid(value):
    """DAB service id as "0xD882" (16 bit audio services; 32 bit ids of data services keep 8 digits); None if invalid.
    Also the key of a DAB station in the plugin (like "96.2" on FM)."""
    try:
        code = value if isinstance(value, int) and not isinstance(value, bool) else int(str(value).strip(), 16)
    except (TypeError, ValueError):
        return None
    if not 0 < code <= 0xFFFFFFFF:
        return None
    return "0x%04X" % code if code <= 0xFFFF else "0x%08X" % code


def normalize_ecc(value):
    try:
        code = int(str(value), 16)
    except (TypeError, ValueError):
        return ""
    return "0x%02X" % code if 0 < code <= 0xFF else ""


def receiver_options(config):
    """Stick options of openhu-dab from the plugin config: gain (dB or "auto"), ppm, biasTee (antenna power)."""
    args = []
    gain = config.get("gain")
    if gain not in (None, "", "auto"):
        args += ["--gain", str(gain)]
    if config.get("ppm"):
        args += ["--ppm", str(int(config["ppm"]))]
    if config.get("biasTee"):
        args.append("--bias-tee")
    return args


def play_command(tool, channel, sid, config, events_fd, slides_dir=None):
    """openhu-dab playing one service: PCM (s16le, stereo, PCM_RATE) on stdout, events on events_fd."""
    args = [tool, "--channel", channel, "--service", sid, "--rate", str(PCM_RATE), "--events-fd", str(events_fd)]
    if slides_dir:
        args += ["--slides", slides_dir]
    return args + receiver_options(config)


def scan_command(tool, channels, config, events_fd):
    """openhu-dab scanning the channels one after the other (dabSyncSeconds to find a DAB signal on a channel,
    at most dabScanSeconds per channel with a signal)."""
    args = [tool, "--scan", "--channels", ",".join(channels), "--events-fd", str(events_fd)]
    if config.get("dabSyncSeconds"):
        args += ["--sync-seconds", str(config["dabSyncSeconds"])]
    if config.get("dabScanSeconds"):
        args += ["--scan-seconds", str(config["dabScanSeconds"])]
    return args + receiver_options(config)


def parse_event(line):
    """One event line of openhu-dab -> dict with "event", None for anything else."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("event"), str):
        return None
    if "sid" in data:
        data["sid"] = normalize_sid(data["sid"])
    return data


def ensemble_info(event):
    """ensemble event -> {"id", "label", "ecc"} like radio.state.dab."""
    return {"id": normalize_sid(event.get("id")) or "", "label": str(event.get("label") or "").strip(),
            "ecc": normalize_ecc(event.get("ecc"))}


class ScanResult:
    """Collects the events of an openhu-dab scan into the plugin's station list."""

    def __init__(self):
        self.ensembles = {}  # channel -> ensemble info
        self.services = {}  # channel -> {key: service event}

    def add(self, event):
        channel = normalize_channel(event.get("channel"))
        if not channel:
            return
        if event["event"] == "ensemble":
            self.ensembles[channel] = ensemble_info(event)
        elif event["event"] == "service" and event.get("audio") and event.get("sid"):
            self.services.setdefault(channel, {})[event["sid"]] = event

    def found(self):
        """{channel: {key: {label, shortLabel, channel, ensemble, ensembleLabel, ecc}}}; services without a label or
        without an ensemble (lost during the scan) are left out."""
        result = {}
        for channel, services in self.services.items():
            ensemble = self.ensembles.get(channel)
            if not ensemble:
                continue
            entries = {
                key: {"label": str(service.get("label") or "").strip(),
                      "shortLabel": str(service.get("shortLabel") or "").strip(), "channel": channel,
                      "ensemble": ensemble["id"], "ensembleLabel": ensemble["label"], "ecc": ensemble["ecc"]}
                for key, service in services.items() if str(service.get("label") or "").strip()}
            if entries:
                result[channel] = entries
        return result

    def count(self):
        return sum(len(services) for services in self.found().values())


def station_order(services):
    """Station keys in channel order, then by name (the order of the station list and of seek)."""
    return sorted(services, key=lambda key: (CHANNEL_ORDER.get(services[key].get("channel"), 99),
                                             services[key].get("label", "").casefold(), key))


def merge_scan(found):
    """Results of all channels ({channel: services}) -> one services dict. A service received on several channels
    (e.g. a regional ensemble and its neighbour) keeps the first channel."""
    services = {}
    for channel in sorted(found, key=lambda name: CHANNEL_ORDER.get(name, 99)):
        for key, service in found[channel].items():
            services.setdefault(key, service)
    return services


def station_label(service, key):
    """Name of a DAB station for lists: its label, else the service id."""
    return (service or {}).get("label") or key


def channel_label(service):
    """"DAB+ 7A" plus the ensemble ("DAB+ 7A · NDR NDS") for media.metadata.album."""
    service = service or {}
    parts = ["DAB+ %s" % service["channel"] if service.get("channel") else "DAB+"]
    if service.get("ensembleLabel"):
        parts.append(service["ensembleLabel"])
    return " · ".join(parts)
