# CAN-Bus

Liest einen CAN-Bus über SocketCAN (z. B. MCP2515-HAT am Raspberry Pi, USB-CAN-Adapter wie CANable)
und übersetzt ihn mit einem Fahrzeugprofil:

- `signals` → Topics wie `vehicle.speed` {kmh}, `vehicle.gear` {reverse}, `vehicle.lights` {headlights}
- `buttons` → Aktionen (`media.next`, `volume.up`, … siehe `input.actions`), mit Drücken/Loslassen
- `triggers` → Aktion oder API-Methode bei einer Wertänderung (Rückwärtsgang → `camera.show`, Licht → `daynight.set`)

Eigene Profile: `<data>/plugin-data/org.openauto.can/profiles/<name>.json`, dann auf der Plugin-Seite wählen.
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

(`cansend` aus `can-utils`, im Container vorhanden: `docker exec openauto cansend vcan0 300#04`.)
