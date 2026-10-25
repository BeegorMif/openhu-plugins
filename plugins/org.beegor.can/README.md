# CAN bus

Reads a CAN bus via SocketCAN (e.g. an MCP2515 HAT on a Raspberry Pi, USB-CAN adapters such as CANable)
and translates it with a vehicle profile:

- `signals` → topics `can.<topic>`: `"topic": "speed"` → `can.speed` {kmh}, `can.gear` {reverse}, `can.lights`
  {headlights}. Field names as in OpenHU's `vehicle.*` topics (docs/api.md), so the "Vehicle data" plugin
  (`org.openhu.vehicle`) can pass them on as `vehicle.*` to OpenHU and Android Auto. The CAN plugin itself delivers
  nothing to Android Auto (openhu#123). Old profiles with `vehicle.speed` are read as `can.speed` (warning in the
  log); `state`, `monitor`, `command` and `signals` are reserved for the plugin.
- If no frames arrive for 3 s (bus quiet, ignition off), the topics become `{"available": false}` until frames
  arrive again.
- `buttons` → actions (`media.next`, `volume.up`, … see `input.actions`), with press/release
- `triggers` → action or API method on a value change (reverse gear → `camera.show`, lights → `daynight.set`)
- `controls` → climate controls for Android Auto (openhu#121), via the "Vehicle data" plugin: `read` reads the
  current value like a signal, `write` sends a change from the phone as a frame (template `data` as hex, the value
  at `byte`/`bit`/`length` with `scale`/`offset`/`map` as when reading). Names, ranges and `min`/`max`/`step` as for
  `vehicle.controls` in OpenHU's docs/api.md; `driverSide` (`left`/`right`) and `units` (`celsius`/`fahrenheit`) at
  the top level. At most one frame per control every 100 ms, only when operated; `"whileDriving": false` rejects
  changes while driving. Without `read`, the written value counts as set.

Own profiles: `<data>/plugin-data/org.openhu.can/profiles/<name>.json`, then select them on the plugin page.
The CAN monitor on the plugin page shows all received IDs – press a key or shift into a gear and see which bytes
change.

The BMW F20 profile decodes ignition from CAN ID `0x130` into `can.ignition` fields `terminalR` (byte 0 bit 0) and
`terminal15` (byte 0 bit 2). The display plugin uses both fields; both false means ignition off. The F20 simulator
alternates these bits every 20 seconds so the blackout and cancellation path can be checked without a car.

Signal: `id`, `byte`, `bit` (0 = lowest), `length` (bits), `endian` (`big`/`little`), `signed`,
`scale`, `offset`, `map` ({"raw value": "text"}). Button: `id`, `byte`, `mask`, `value` (default = mask), `action`.

## Test without a car (vcan0)

On the host (the container uses its network):

```
sudo modprobe vcan
sudo ip link add vcan0 type vcan
sudo ip link set vcan0 up
```

Enter the interface `vcan0` on the plugin page (Enter), profile `example`, then e.g.:

```
cansend vcan0 100#1388  # 50 km/h
cansend vcan0 200#01    # reverse gear -> camera
cansend vcan0 200#00    # camera off
cansend vcan0 300#04    # "next track" pressed
cansend vcan0 300#00    # ... released
```

(`cansend` from `can-utils`, available in the container: `docker exec openhu cansend vcan0 300#04`.)
