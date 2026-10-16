"""DAB/DAB+ helpers without I/O (see tests/test_dablib.py): channels, service ids, welle-cli commands and its JSON.

Reception and decoding is done by welle-cli (Debian package welle.io) in its web server mode on localhost: it tunes
one channel (ensemble), serves the ensemble as /mux.json (services, DLS = "radiotext"), a service as MP3 stream
(/mp3/<sid>) and the last slideshow picture of a service (/slide/<sid>). The plugin decodes the MP3 with mpg123
(or ffmpeg) to PCM for pacat, like rtl_fm's output on FM.
"""

import json

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
DEFAULT_PORT = 7979
NULL_DEVICE = "Null device"


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


def welle_sid(key):
    """welle-cli writes service ids in lower case ("0xd882") and only finds them that way in /mp3/ and /slide/."""
    return key.lower()


def welle_cli_command(channel, port, config):
    """welle-cli in web server mode for one channel. -T: no TII decoding (transmitter ids, CPU)."""
    args = ["welle-cli", "-c", channel, "-w", str(port), "-T"]
    gain = config.get("gain")
    if gain not in (None, "", "auto"):
        args += ["-g", str(gain)]
    return args


def mp3_decoder_command(decoder, rate=48000):
    """MP3 on stdin -> s16le stereo at rate on stdout. mpg123 (small, the OS image) or ffmpeg (dev image)."""
    if decoder == "mpg123":
        return ["mpg123", "-q", "-s", "-r", str(rate), "--stereo", "-e", "s16", "-"]
    return ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
            "-ac", "2", "-ar", str(rate), "-f", "s16le", "pipe:1"]


def label_text(label):
    """welle-cli labels are objects ({"label": "NDR 2", "shortlabel": "NDR 2", ...}), plain strings are fine too."""
    if isinstance(label, dict):
        return str(label.get("label") or "").strip(), str(label.get("shortlabel") or "").strip()
    return str(label or "").strip(), ""


def parse_mux(text):
    """welle-cli /mux.json -> {"ensemble": {"id", "label", "ecc"} or None (no ensemble received),
    "services": {key: {"label", "shortLabel", "audio", "dls", "mot"}}, "noDevice": bool}.
    noDevice: welle-cli found no stick and runs with its "Null device" instead of ending (tested with 2.4)."""
    try:
        data = json.loads(text)
    except ValueError:
        return {"ensemble": None, "services": {}, "noDevice": False}
    if not isinstance(data, dict):
        return {"ensemble": None, "services": {}, "noDevice": False}
    hardware = ((data.get("receiver") or {}).get("hardware") or {}).get("name")
    ensemble = data.get("ensemble") or {}
    ensemble_id = normalize_sid(ensemble.get("id"))
    label, _ = label_text(ensemble.get("label"))
    result = {
        "ensemble": {"id": ensemble_id, "label": label, "ecc": normalize_ecc(ensemble.get("ecc"))}
        if ensemble_id else None,
        "services": {},
        "noDevice": hardware == NULL_DEVICE,
    }
    for service in data.get("services") or []:
        if not isinstance(service, dict):
            continue
        key = normalize_sid(service.get("sid"))
        if not key:
            continue
        label, short = label_text(service.get("label"))
        components = service.get("components") or []
        audio = bool(service.get("url_mp3")) or any(
            isinstance(component, dict) and component.get("transportmode") == "audio" for component in components)
        result["services"][key] = {
            "label": label,
            "shortLabel": short,
            "audio": audio,
            "dls": str((service.get("dls") or {}).get("label") or "").strip(),
            "mot": (service.get("mot") or {}).get("lastchange") or (service.get("mot") or {}).get("time") or 0,
        }
    return result


def normalize_ecc(value):
    try:
        code = int(str(value), 16)
    except (TypeError, ValueError):
        return ""
    return "0x%02X" % code if 0 < code <= 0xFF else ""


def scan_services(channel, mux):
    """Audio services of one channel's parsed mux.json for the station list: {key: {label, shortLabel, channel,
    ensemble, ensembleLabel, ecc}}; services without a label yet are left out."""
    ensemble = mux.get("ensemble")
    if not ensemble:
        return {}
    return {
        key: {"label": service["label"], "shortLabel": service["shortLabel"], "channel": channel,
              "ensemble": ensemble["id"], "ensembleLabel": ensemble["label"], "ecc": ensemble["ecc"]}
        for key, service in mux["services"].items() if service["audio"] and service["label"]
    }


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
