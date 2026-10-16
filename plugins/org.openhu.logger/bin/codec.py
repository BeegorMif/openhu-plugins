"""Compact blocks of samples of one key: delta-encoded timestamps and values, zlib-compressed (standard library only).

Layout before compression:
    version (1 byte) | count (varint) | count-1 time deltas in ms (zigzag varints; the first time is the row's t0)
    | value kind (1 byte) | values
Value kinds:
    0..9   decimal: every value is an integer times 10^-k (CAN signals are raw integers times a scale such as 0.01,
           0.5, 0.125), stored as zigzag varint deltas of those integers. Exact to 12 significant digits: a value
           such as 50.370000000000005 (raw * 0.01 in floating point) comes back as 50.37
    255    anything else: float64, byte-shuffled (all first bytes, then all second bytes, ...), which compresses
           well for slowly changing values
"""

import struct
import zlib

VERSION = 1
FLOAT = 255
MAX_DECIMALS = 9
MAX_EXACT = 2 ** 53
TOLERANCE = 1e-12


def _put_varint(out, value):
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)


def _zigzag(value):
    return value * 2 if value >= 0 else -value * 2 - 1


def _unzigzag(value):
    return value >> 1 if not value & 1 else -((value + 1) >> 1)


def _decimals(values):
    """Smallest k with every value an integer times 10^-k, or None."""
    if not all(abs(value) < 1e15 for value in values):  # also NaN and infinity
        return None
    for k in range(MAX_DECIMALS + 1):
        scale = 10 ** k
        ok = True
        for value in values:
            rounded = round(value * scale)
            # decoding (integer / 10^k) gives back the value, up to floating point noise
            if abs(rounded) >= MAX_EXACT or abs((rounded / scale if k else float(rounded)) - value) \
                    > TOLERANCE * abs(value):
                ok = False
                break
        if ok:
            return k
    return None


def encode(times, values, level=6):
    """times (int ms, ascending as recorded), values (numbers) -> bytes"""
    out = bytearray([VERSION])
    _put_varint(out, len(times))
    previous = times[0] if times else 0
    for t in times[1:]:
        _put_varint(out, _zigzag(int(t) - previous))
        previous = int(t)
    k = _decimals(values)
    if k is None:
        out.append(FLOAT)
        raw = struct.pack("<%dd" % len(values), *values)
        for byte in range(8):
            out += raw[byte::8]
    else:
        out.append(k)
        scale = 10 ** k
        previous = 0
        for value in values:
            integer = int(round(value * scale))
            _put_varint(out, _zigzag(integer - previous))
            previous = integer
    return zlib.compress(bytes(out), level)


def decode(t0, blob):
    """-> (times, values)"""
    data = zlib.decompress(blob)
    if data[0] != VERSION:
        raise ValueError("unknown block version %d" % data[0])
    position = 1

    def varint():
        nonlocal position
        result = shift = 0
        while True:
            byte = data[position]
            position += 1
            result |= (byte & 0x7F) << shift
            if byte < 0x80:
                return result
            shift += 7

    count = varint()
    times = [t0] if count else []
    t = t0
    for _ in range(count - 1):
        t += _unzigzag(varint())
        times.append(t)
    kind = data[position]
    position += 1
    if kind == FLOAT:
        raw = data[position:position + 8 * count]
        unshuffled = bytearray(8 * count)
        for byte in range(8):
            unshuffled[byte::8] = raw[byte * count:(byte + 1) * count]
        values = list(struct.unpack("<%dd" % count, bytes(unshuffled)))
    else:
        scale = 10 ** kind
        values = []
        integer = 0
        for _ in range(count):
            integer += _unzigzag(varint())
            values.append(integer / scale if kind else float(integer))
    return times, values
