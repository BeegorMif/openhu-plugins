# CAN-Bus

Liest einen CAN-Bus über SocketCAN (z. B. MCP2515-HAT am Raspberry Pi, USB-CAN-Adapter wie CANable)
und übersetzt ihn mit einem Fahrzeugprofil:

- `signals` → Topics `can.<topic>`: `"topic": "speed"` → `can.speed` {kmh}, `can.gear` {reverse}, `can.lights`
  {headlights}. Feldnamen wie bei den `vehicle.*`-Topics von OpenHU (docs/api.md), dann reicht das Plugin
  „Fahrzeugdaten“ (`org.openhu.vehicle`) sie als `vehicle.*` an OpenHU und Android Auto weiter. Das CAN-Plugin selbst
  liefert nichts an Android Auto (openhu#123). Alte Profile mit `vehicle.speed` werden als `can.speed` gelesen
  (Warnung im Log); `state`, `monitor`, `command` und `signals` sind dem Plugin vorbehalten.
- Kommen 3 s lang keine Frames (Bus still, Zündung aus), werden die Topics `{"available": false}`, bis wieder Frames
  kommen.
- `buttons` → Aktionen (`media.next`, `volume.up`, … siehe `input.actions`), mit Drücken/Loslassen
- `triggers` → Aktion oder API-Methode bei einer Wertänderung (Rückwärtsgang → `camera.show`, Licht → `daynight.set`)
- `controls` → Klima-Bedienelemente für Android Auto (openhu#121), über das Plugin „Fahrzeugdaten“: `read` liest den
  aktuellen Wert wie ein Signal, `write` schickt eine Änderung vom Handy als Frame (Vorlage `data` als Hex, der Wert
  an `byte`/`bit`/`length` mit `scale`/`offset`/`map` wie beim Lesen). Namen, Bereiche und `min`/`max`/`step` wie bei
  `vehicle.controls` in OpenHUs docs/api.md; `driverSide` (`left`/`right`) und `units` (`celsius`/`fahrenheit`) auf
  oberster Ebene. Höchstens ein Frame pro Bedienelement alle 100 ms, nur auf Bedienung hin; `"whileDriving": false`
  lehnt Änderungen während der Fahrt ab. Ohne `read` gilt der geschriebene Wert als gesetzt.

Eigene Profile: `<data>/plugin-data/org.openhu.can/profiles/<name>.json`, dann auf der Plugin-Seite wählen.
Der CAN-Monitor auf der Plugin-Seite zeigt alle empfangenen IDs – Taste drücken bzw. Gang einlegen und
schauen, welche Bytes sich ändern.

Signal: `id`, `byte`, `bit` (0 = niedrigstes), `length` (Bits), `endian` (`big`/`little`), `signed`,
`scale`, `offset`, `map` ({"Rohwert": "Text"}). Taste: `id`, `byte`, `mask`, `value` (Standard = mask), `action`.

## Test ohne Auto (vcan0)

Auf dem Host (der Container nutzt dessen Netzwerk):

```
sudo modprobe vcan
sudo ip link add vcan0 type vcan
sudo ip link set vcan0 up
```

Auf der Plugin-Seite Interface `vcan0` eintragen (Enter), Profil `example`, dann z. B.:

```
cansend vcan0 100#1388  # 50 km/h
cansend vcan0 200#01    # Rückwärtsgang -> Kamera
cansend vcan0 200#00    # Kamera aus
cansend vcan0 300#04    # "Nächster Titel" gedrückt
cansend vcan0 300#00    # ... losgelassen
```

(`cansend` aus `can-utils`, im Container vorhanden: `docker exec openhu cansend vcan0 300#04`.)
