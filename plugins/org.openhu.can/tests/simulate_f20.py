#!/usr/bin/env python3
"""Send fixed BMW F20 test frames on a SocketCAN interface. usage: simulate.py IFACE [HZ]"""
""" python3 /var/lib/openhu/.openhu/plugins/org.openhu.can/tests/simulate.py vcan0"""
import math, socket, struct, subprocess, sys, time

iface = sys.argv[1]
rate = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

def ensure_vcan(name):
    """Create and bring up a virtual CAN interface if it isn't there yet (needs root)."""
    if not name.startswith("vcan"):
        return  # a real interface: leave it alone
    try:
        if subprocess.run(["ip", "link", "show", name], capture_output=True).returncode != 0:
            subprocess.run(["modprobe", "vcan"], check=True)
            subprocess.run(["ip", "link", "add", "dev", name, "type", "vcan"], check=True)
        subprocess.run(["ip", "link", "set", "up", name], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.exit(f"could not set up {name} (run as root; kernel needs CONFIG_CAN_VCAN): {e}")

ensure_vcan(iface)

# id: 8 data bytes -> value they should decode to
STATIC = {
    0x2CA: "69 00 00 00 00 00 00 00",  # outside temp 12.5 C   (0x69=105, 105*0.5-40)
    0x2E6: "00 00 00 00 00 03 00 2B",  # fan speed 3, temperature 21.5 C (0x2B=43, *0.5)
    0x202: "80 00 00 00 00 00 00 00",  # brightness raw 128
    0x3B4: "00 00 01 00 00 00 00 00",  # engine status byte 1
    0x330: "00 00 00 07 00 00 00 00",  # average fuel 7
    0x349: "80 0C 40 0B 00 00 00 00",  # left 20.0 (0x0C80=3200*0.00625), right 18.0 (0x0B40=2880)
}

s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
s.bind((iface,))

def send(cid, data):
    s.send(struct.pack("=IB3x8s", cid, 8, bytes(data)))

start = time.monotonic()
while True:
    t = time.monotonic() - start
    for cid, hexdata in STATIC.items():
        send(cid, bytes.fromhex(hexdata))

    # Exercise the BMW F20 profile's actual ignition signal: byte 0 bit 0 is
    # terminal R and bit 2 is terminal 15. Alternate on/off every 20 seconds;
    # choose a shutdown delay longer than 20 s to observe blackout then cancel.
    ignition = 0x05 if int(t // 20) % 2 == 0 else 0x00
    send(0x130, [ignition, 0, 0, 0, 0, 0, 0, 0])

    mph = 35 + 35 * math.sin(t / 8)                  # sweeps 0..70
    send(0x1A1, [0, 0, *struct.pack("<H", int(mph / 0.01)), 0, 0, 0, 0])

    lights = 0                                       # 0x21A byte 0: dip 0, main 1, side 2, brake 7
    lights |= 0x01 if int(t // 10) % 2 else 0
    lights |= 0x02 if int(t // 20) % 2 else 0
    lights |= 0x04 if int(t // 10) % 2 else 0
    lights |= 0x80 if int(t // 3) % 2 == 0 else 0
    reverse = 0x01 if int(t // 15) % 3 == 2 else 0   # byte 1 bit 0
    send(0x21A, [lights, reverse, 0, 0, 0, 0, 0, 0])

    send(0x3A7, [0, 0, 0, 0, 0, 0, 0x04 if int(t // 12) % 2 else 0, 0])  # dtcOff (byte 6 bit 2)
    send(0x3F9, [0, 0, 0, 0, 0, 0, 0x02 if int(t // 12) % 2 else 0, 0])  # stop/start (byte 6 bit 1)
    time.sleep(1 / rate)
