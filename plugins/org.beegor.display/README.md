# Display control

Uses `ddcutil` and DDC/CI to set monitor brightness from a raw CAN dimmer byte. The status bar shortcut opens
a completely black page; tap the small gear button to open display settings, configure the signal, or adjust
brightness manually. The black page leaves the monitor powered on.

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
