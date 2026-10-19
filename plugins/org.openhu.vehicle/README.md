# Vehicle data

Passes the vehicle data that the CAN plugin (`org.openhu.can`) decodes on to OpenHU's `vehicle.*` topics, which
OpenHU gives to Android Auto as sensors (openhu-plugins#29).

Only plugins that declare it in their manifest (`androidAuto`) feed Android Auto (openhu#123). The CAN plugin only
decodes; this plugin declares the sensors (speed, parking brake, gear, fuel, odometer, rpm, climate, compass,
driving status, vehicle info) and copies the values 1:1:

| CAN plugin | becomes |
|---|---|
| `can.speed`, `can.parkingBrake`, `can.gear`, `can.fuel`, `can.odometer`, `can.engine`, `can.climate`, `can.compass`, `can.drivingStatus`, `can.info`, `can.lights` | `vehicle.<same name>` with the same fields |

So the CAN profile uses the topic and field names of the `vehicle.*` topics (`"topic": "speed", "field": "kmh"`,
see OpenHU's docs/api.md). Other `can.*` values stay with the CAN plugin.

The values become `{"available": false}` when the CAN plugin reports its bus as gone (`can.state` with
`connected: false`), when no frames arrive (the CAN plugin marks its values) or when the CAN plugin stops reporting
(no `can.state` for 5 seconds).

While Android Auto is connected, this plugin cannot be enabled, disabled, updated or removed: what OpenHU announces
to the phone is fixed for a connection.

## Car controls

The plugin provides the car controls of Android Auto's climate rail (openhu#121, OpenHU docs/api.md "Car controls"):
`can.controls` of the CAN plugin becomes `vehicle.controls`, changes on the phone (`vehicle.control.set`) go to the CAN
plugin as `can.control.set`, its `can.control.result` comes back as `vehicle.control.result`. The rail needs a video
resolution above 720p.

Without a car, a demo climate (temperatures, seat and steering wheel heating, A/C, fan, recirculation, defrost) takes
every change:

```sh
openhu-cli api bus.emit '{"topic": "vehicle.command", "data": {"cmd": "demoControls", "value": true}}'
```

It is kept in the plugin's config and shows in Android Auto from the next connection (`false` switches it off).
