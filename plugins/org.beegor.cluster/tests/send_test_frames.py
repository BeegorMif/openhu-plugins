
import socket
import struct
import time
import signal
import sys
import subprocess


IFACE = "vcan0"

PERIOD = 0.1  # seconds between frames

# All unique standard CAN IDs from signals, buttons, and controls.
CAN_IDS = [
    0x0A5, 0x0F2, 0x0FA, 0x130, 0x193, 0x19E,
    0x1A1, 0x1D6, 0x1E3, 0x1EE, 0x1F4, 0x1F6,
    0x200, 0x202, 0x21A, 0x246, 0x26E, 0x2A6,
    0x2CA, 0x2D6, 0x2E6, 0x301, 0x302, 0x32E,
    0x330, 0x349, 0x34A, 0x356, 0x362, 0x366,
    0x393, 0x3A7, 0x3B4, 0x3F9,
]

# Synthetic 8-byte payloads, keyed by CAN ID.
# Replace these with known-good payloads when available.
PAYLOADS = {
    can_id: bytes([
        (can_id >> 0) & 0xFF,
        (can_id >> 1) & 0xFF,
        (can_id >> 2) & 0xFF,
        (can_id >> 3) & 0xFF,
        0x11, 0x22, 0x33, 0x44,
    ])
    for can_id in CAN_IDS
}

# A few useful overrides for readable decoder smoke tests.
PAYLOADS[0x0F2] = bytes.fromhex("01 00 02 04 00 00 00 00")
PAYLOADS[0x0FA] = bytes.fromhex("11 22 00 00 00 00 00 00")
PAYLOADS[0x130] = bytes.fromhex("05 00 00 00 00 00 00 00")
PAYLOADS[0x1D6] = bytes.fromhex("00 10 00 00 00 00 00 00")
PAYLOADS[0x1E3] = bytes.fromhex("12 34 00 00 00 00 00 00")
PAYLOADS[0x1EE] = bytes.fromhex("3F 00 00 00 00 00 00 00")
PAYLOADS[0x1F6] = bytes.fromhex("31 03 00 00 00 00 00 00")
PAYLOADS[0x200] = bytes.fromhex("01 00 1F 0F 00 00 00 00")
PAYLOADS[0x21A] = bytes.fromhex("C7 01 00 00 00 00 00 00")
PAYLOADS[0x2CA] = bytes.fromhex("78 00 00 00 00 00 00 00")
PAYLOADS[0x2E6] = bytes.fromhex("00 00 00 00 00 06 00 4A")
PAYLOADS[0x34A] = bytes.fromhex("00 00 00 00 00 00 00 00")
PAYLOADS[0x3A7] = bytes.fromhex("00 00 04 04 00 00 00 00")
PAYLOADS[0x3F9] = bytes.fromhex("00 03 00 00 78 7D 02 00")

# Linux SocketCAN classic CAN frame:
# can_id: unsigned 32-bit, DLC: 1 byte, data: 8 bytes.
CAN_FRAME = struct.Struct("=IB3x8s")



def run_ip(*args, check=True):
    """Run an ip command and report errors clearly."""
    result = subprocess.run(
        ["ip", *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: ip {' '.join(args)}\n"
            f"{result.stderr.strip()}"
        )
    return result


def ensure_vcan():
    """Create vcan0 if missing, bring it up, and verify it."""
    # Check that the vcan kernel module is available.
    subprocess.run(
        ["modprobe", "vcan"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Check whether the interface already exists.
    result = run_ip("link", "show", "dev", IFACE, check=False)

    if result.returncode != 0:
        print(f"{IFACE} does not exist; creating it...")
        run_ip("link", "add", "dev", IFACE, "type", "vcan")

    # Bring it up, including when it already exists but is down.
    result = run_ip("link", "set", "dev", IFACE, "up", check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not bring up {IFACE}.\n"
            f"{result.stderr.strip()}\n"
            "Try running the script with sudo."
        )

    # Verify that the interface exists and is up.
    result = run_ip("link", "show", "dev", IFACE)
    if "UP" not in result.stdout.split("<", 1)[-1].split(">", 1)[0].split(","):
        raise RuntimeError(f"{IFACE} exists but is not UP")

    # Verify SocketCAN can bind to it.
    probe = socket.socket(
        socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW
    )
    try:
        probe.bind((IFACE,))
    finally:
        probe.close()

    print(f"{IFACE} exists, is UP, and accepts SocketCAN sockets.")


def main():
    ensure_vcan()

    can_sock = socket.socket(
        socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW
    )
    can_sock.bind((IFACE,))

    sent = 0
    print(f"Sending {len(CAN_IDS)} unique CAN IDs on {IFACE}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            for can_id in CAN_IDS:
                payload = PAYLOADS[can_id]
                frame = CAN_FRAME.pack(can_id, len(payload), payload)
                can_sock.send(frame)
                sent += 1

                print(
                    f"ID=0x{can_id:03X} "
                    f"DLC=8 DATA={payload.hex(' ').upper()}"
                )
                time.sleep(PERIOD)

    except KeyboardInterrupt:
        print(f"\nStopped. Frames sent: {sent}")
    finally:
        can_sock.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
