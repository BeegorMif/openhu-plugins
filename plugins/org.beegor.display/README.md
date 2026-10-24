# Display control

Uses `ddcutil` and DDC/CI to set monitor brightness from a raw CAN dimmer byte. The status bar shortcut opens
a completely black page; tap the small gear button to open display settings, configure the signal, or adjust
brightness manually. The black page leaves the monitor powered on. **Extra dim the whole interface** adds a
translucent black layer over the shell, including the dock, status bar, and black page; it does not block touch.

By default the plugin watches `can.display` field `dimByte`. Add a matching numeric signal to the selected
profile in `org.openhu.can`; for example:

```json
{"id": "0x202", "topic": "display", "field": "dimByte", "byte": 0, "length": 8}
```

The byte is clamped to 0–255 and converted to brightness with `round((dimByte / 255) * 100)`. Configure another
topic/field in display settings. For manual control, disable **Use CAN brightness** before moving the slider.
If you have multiple monitors, set the numeric `ddcutil` display number there; leave it blank for automatic
selection. The head unit needs `ddcutil` installed and DDC/CI enabled in the monitor's settings.

The monitor must support DDC/CI VCP code `10` for brightness adjustment.

## Ignition power-off

For the BMW F20 profile, `0x130` publishes `terminalR` and `terminal15` on `can.ignition`. Enable **Black screen and
power off after ignition off** in the display plugin and set the delay (5 minutes by default). After the plugin has
seen either terminal active, both terminals becoming false covers the whole OpenHU interface with a touch-blocking
black overlay and starts the countdown. If either terminal becomes active again before the deadline, the countdown is
cancelled and the overlay is removed. When it expires, the plugin requests system power-off through `loginctl`; the
OpenHU OS polkit rule permits this for the `openhu` user. CAN `available: false` events do not count as ignition-off.

The option is off by default. The `can.ignition` profile topic must contain both boolean fields `terminalR` and
`terminal15`; the plugin reads the current topic on connect as well as live updates.
