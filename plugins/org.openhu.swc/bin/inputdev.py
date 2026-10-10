"""Linux input devices: device list from /proc and key events from /dev/input/event*."""

import fcntl
import os
import struct

EVENT = struct.Struct("llHHi")  # struct input_event: timeval, type, code, value
EV_KEY = 1
EVIOCGRAB = 0x40044590

# Keys of steering wheel adapters, remotes and multimedia keyboards -> default action
DEFAULT_KEYS = {
    113: "volume.mute", 114: "volume.down", 115: "volume.up",
    163: "media.next", 164: "media.play_pause", 165: "media.previous", 166: "media.pause",
    200: "media.play", 201: "media.pause", 207: "media.play", 407: "media.next", 412: "media.previous",
    169: "call.answer", 582: "voice", 217: "voice",
    172: "ui.home", 102: "ui.home", 158: "ui.back", 1: "ui.back",
    103: "dpad.up", 108: "dpad.down", 105: "dpad.left", 106: "dpad.right", 28: "dpad.enter", 352: "dpad.enter",
}

KEY_NAMES = {
    1: "ESC", 28: "ENTER", 102: "HOME", 103: "UP", 105: "LEFT", 106: "RIGHT", 108: "DOWN",
    113: "MUTE", 114: "VOLUMEDOWN", 115: "VOLUMEUP", 158: "BACK", 163: "NEXTSONG", 164: "PLAYPAUSE",
    165: "PREVIOUSSONG", 166: "STOPCD", 169: "PHONE", 172: "HOMEPAGE", 200: "PLAYCD", 201: "PAUSECD",
    207: "PLAY", 217: "SEARCH", 352: "OK", 407: "NEXT", 412: "PREVIOUS", 582: "VOICECOMMAND",
}


def key_name(code):
    return KEY_NAMES.get(code, "KEY_%d" % code)


def parse_devices(text):
    """/proc/bus/input/devices -> [{"name", "event"}] of devices that have keys."""
    devices = []
    for block in text.strip().split("\n\n"):
        name, event, has_keys = None, None, False
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[len("N: Name="):].strip().strip('"')
            elif line.startswith("H: Handlers="):
                event = next((h for h in line.split("=", 1)[1].split() if h.startswith("event")), None)
            elif line.startswith("B: KEY="):
                has_keys = any(part.strip("0") for part in line.split("=", 1)[1].split())
        if name and event and has_keys:
            devices.append({"name": name, "event": event})
    return devices


def list_devices():
    try:
        with open("/proc/bus/input/devices") as file:
            return parse_devices(file.read())
    except OSError:
        return []


class InputDevice:
    def __init__(self, name, event, grab):
        self.name = name
        self.event = event
        self.fd = os.open("/dev/input/" + event, os.O_RDONLY | os.O_NONBLOCK)
        if grab:
            # exclusive: the desktop/shell does not see these keys a second time
            fcntl.ioctl(self.fd, EVIOCGRAB, 1)

    def read_keys(self):
        """[(code, value)] of pending key events, value 1 = press, 0 = release, 2 = repeat."""
        keys = []
        try:
            data = os.read(self.fd, EVENT.size * 64)
        except BlockingIOError:
            return keys
        for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, _, event_type, code, value = EVENT.unpack_from(data, offset)
            if event_type == EV_KEY:
                keys.append((code, value))
        return keys

    def close(self):
        os.close(self.fd)
