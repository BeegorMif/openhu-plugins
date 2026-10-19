"""CAN frame and vehicle profile decoding (no I/O, see tests/test_canbus.py).

A profile describes a car, see profiles/example.json:

    signals   value in a frame -> EventBus topic field   ("speed" -> can.speed.kmh, can.gear.reverse, ...)
    buttons   bits in a frame  -> action while pressed     (steering wheel buttons)
    triggers  signal value     -> action or API method     (reverse gear -> camera, lights -> night mode)

The plugin only decodes: its values go to can.<topic>. The vehicle plugin (org.openhu.vehicle) maps them to the
vehicle.* topics that OpenHU passes to Android Auto (openhu#123, openhu-plugins#29).
"""

import struct

FRAME = struct.Struct("=IB3x8s")

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF


def parse_frame(raw):
    """struct can_frame -> (id, data); None for remote and error frames."""
    can_id, length, data = FRAME.unpack(raw[:FRAME.size])
    if can_id & (CAN_RTR_FLAG | CAN_ERR_FLAG):
        return None
    can_id &= CAN_EFF_MASK if can_id & CAN_EFF_FLAG else CAN_SFF_MASK
    return can_id, data[:min(length, 8)]


# topics of the plugin itself, not available to profiles
RESERVED = {"state", "monitor", "command", "signals"}


def data_topic(topic):
    """Profile topic -> EventBus topic: "speed" -> "can.speed". Profiles from before openhu-plugins#29 name
    "vehicle.speed": read as "can.speed" too. None for an empty or reserved name."""
    name = str(topic or "")
    for prefix in ("vehicle.", "can."):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if not name or name.split(".")[0] in RESERVED:
        return None
    return "can." + name


def parse_number(value):
    """123, "123", "0x7B" -> 123"""
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def extract(data, signal):
    """Value of a signal: byte, bit (0 = lowest), length in bits, endian, signed, scale, offset, map."""
    byte = signal.get("byte", 0)
    bit = signal.get("bit", 0)
    length = signal.get("length", 8)

    if bit == 0 and length % 8 == 0:
        chunk = data[byte:byte + length // 8]
        if len(chunk) < length // 8:
            return None
        raw = int.from_bytes(chunk, signal.get("endian", "big"))
    else:
        chunk = data[byte:byte + (bit + length + 7) // 8]
        if len(chunk) < (bit + length + 7) // 8:
            return None
        raw = (int.from_bytes(chunk, "little") >> bit) & ((1 << length) - 1)

    if signal.get("signed") and raw & (1 << (length - 1)):
        raw -= 1 << length

    if "map" in signal:
        return signal["map"].get(str(raw), raw)
    if length == 1 and "scale" not in signal and "offset" not in signal:
        return bool(raw)

    value = raw * signal.get("scale", 1) + signal.get("offset", 0)
    if isinstance(value, float):
        value = round(value, signal.get("decimals", 2))
    return value


class Profile:
    def __init__(self, spec):
        self.name = spec.get("name", "")
        self.signals = {}
        self.buttons = {}
        self.warnings = []
        for signal in spec.get("signals", []):
            topic = self._topic(signal.get("topic"))
            if topic is not None:
                self.signals.setdefault(parse_number(signal["id"]), []).append(dict(signal, topic=topic))
        for button in spec.get("buttons", []):
            button = dict(button)
            button["mask"] = parse_number(button.get("mask", 0xFF))
            button["value"] = parse_number(button.get("value", button["mask"]))
            self.buttons.setdefault(parse_number(button["id"]), []).append(button)
        self.triggers = [dict(trigger, topic=self._topic(trigger.get("topic"))) for trigger in spec.get("triggers", [])]
        self.values = {}      # topic -> {field: value}
        self._pressed = set()  # ids of pressed buttons

    def _topic(self, topic):
        result = data_topic(topic)
        if result is None:
            self.warnings.append("topic %r not allowed (empty or one of %s), ignored" % (topic, ", ".join(sorted(RESERVED))))
        elif str(topic).startswith("vehicle."):
            self.warnings.append("topic %s is read as %s, write %r in the profile" % (topic, result, result[4:]))
        return result

    @property
    def ids(self):
        return set(self.signals) | set(self.buttons)

    def feed(self, can_id, data):
        """Returns (changed, actions, commands):
        changed   {topic: all current fields} for topics with a changed field
        actions   [(action, "press"|"release")] for buttons
        commands  [{"action": ...} or {"method": ..., "params": ...}] from triggers
        """
        changed, actions, commands = {}, [], []

        for signal in self.signals.get(can_id, []):
            value = extract(data, signal)
            if value is None:
                continue
            fields = self.values.setdefault(signal["topic"], {})
            old = fields.get(signal["field"])
            if old != value:
                fields[signal["field"]] = value
                changed[signal["topic"]] = dict(fields)
                commands.extend(self._triggers(signal["topic"], signal["field"], old, value))

        for button in self.buttons.get(can_id, []):
            byte = button.get("byte", 0)
            if byte >= len(data):
                continue
            pressed = (data[byte] & button["mask"]) == button["value"]
            key = id(button)
            if pressed and key not in self._pressed:
                self._pressed.add(key)
                actions.append((button["action"], "press"))
            elif not pressed and key in self._pressed:
                self._pressed.discard(key)
                actions.append((button["action"], "release"))

        return changed, actions, commands

    def _triggers(self, topic, field, old, new):
        commands = []
        for trigger in self.triggers:
            if trigger.get("topic") != topic or trigger.get("field") != field:
                continue
            expected = trigger.get("equals")
            was, now = old == expected, new == expected
            # first value always fires, afterwards only on a change of the condition
            if old is not None and was == now:
                continue
            command = trigger.get("then") if now else trigger.get("else")
            if command:
                commands.append(command)
        return commands
