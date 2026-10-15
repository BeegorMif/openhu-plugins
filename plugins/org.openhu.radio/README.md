# Radio (`org.openhu.radio`)

FM/AM-Radio mit einem RTL-SDR-USB-Stick: `rtl_fm` → `pacat`, RDS über `redsea` (mit `sox`), Sendersuche über
`rtl_power`. Pakete auf der Head-Unit: `rtl-sdr`, `pulseaudio-utils`, für RDS zusätzlich `redsea` und `sox`.

Status `radio.state`, Befehle `radio.command` und Konfiguration: siehe Kopf von [`bin/radio.py`](bin/radio.py).
`radio.state.bands` enthält beide Bänder mit Sendern, Favoriten und den RDS-Namen, die sich das Plugin pro Frequenz
merkt (für Android Auto, openhu#75).

## Simulierter Stick (Test ohne Hardware)

`tools/fake-sdr/` ersetzt `rtl_fm`, `rtl_power` und `redsea`, zum Beispiel in der Entwicklungs-VM. Jeder Sender
in einer Senderliste spielt einen **Internetradio-Stream** (oder eine Datei, oder einen Testton), als würde er über
UKW empfangen:

- Einstellen auf eine Frequenz aus der Liste spielt deren Stream, dazwischen leises Rauschen.
- RDS: Sendername aus der Liste, Radiotext ist der aktuelle Titel aus dem Stream (Icecast-Metadaten).
- Die Sendersuche findet genau die Sender der Liste.
- Bricht der Stream ab, gibt es Rauschen, bis er wieder verbunden ist.
- Fehler zum Testen: `"error": "no-device"` oder `"busy"` in der Senderliste.

Die Oberfläche zeigt dann „Simulierter Stick“, `radio.state` hat `simulated: true`.

**Einschalten** (eins davon):

- `"fakeSdr": true` in `config.json` im Datenverzeichnis des Plugins
  (`~/.openhu/plugin-data/org.openhu.radio/config.json`),
- Befehl `radio.command` `{"cmd": "fakeSdr", "value": true}` (wirkt sofort, wird gespeichert),
- Umgebungsvariable `OPENHU_FAKE_SDR=1` für den Plugin-Prozess.

Ein echter Stick wird dabei nicht angesprochen; ausschalten mit `false`.

**Braucht:** `ffmpeg` für Streams und Dateien (Testton-Sender gehen ohne), `sox` für RDS, `pacat` wie immer.

**Senderliste:** `fake-sdr-stations.json` im Datenverzeichnis des Plugins, sonst die mitgelieferte
[`tools/fake-sdr/stations.json`](tools/fake-sdr/stations.json) (Raum Hannover: NDR, Deutschlandfunk, ffn, Radio 21,
Radio Hannover, Leibniz.FM auf ihren echten UKW-Frequenzen, ein Testton auf 87,6 MHz). Pfad auch über
`OPENHU_FAKE_SDR_STATIONS`.

```json
{
  "fm": [
    {"frequency": 96.2, "name": "NDR 2", "ps": "NDR 2", "url": "https://icecast.ndr.de/ndr/ndr2/niedersachsen/mp3/128/stream.mp3"},
    {"frequency": 87.6, "name": "Testton", "ps": "TESTTON", "tone": 440, "rt": "Simulierter Sender"}
  ],
  "am": [
    {"frequency": 1008, "name": "AM-Test", "tone": 800}
  ],
  "error": null
}
```

| Feld | |
|---|---|
| `frequency` | MHz (FM, 0,1er-Raster) bzw. kHz (AM) |
| `name` | Name, Standard für RDS |
| `ps` | RDS-Sendername, 8 Zeichen (Standard: `name`) |
| `url` | Stream (MP3, AAC, HLS, Icecast, auch `.m3u`/`.pls`) oder lokale Datei (läuft in Schleife) |
| `tone` | statt `url`: Sinuston in Hz, ohne Netzwerk und ohne `ffmpeg` |
| `rt` | fester RDS-Radiotext (Standard: Titel aus dem Stream, sonst `name`) |
| `level` | Pegel für die Sendersuche in dB (Standard -10, Rauschen -40, unter -30 wird der Sender nicht gefunden) |

Die Streams in der Liste sind die öffentlichen Web-Streams der Sender, zum Anhören beim Testen. Eigene Listen
bitte nur mit Streams, die man so nutzen darf.

**Grenzen:** getestet wird alles oberhalb der Hardware (Plugin, Oberfläche, Favoriten, Suchlauf, RDS-Anzeige,
später die Android-Auto-Anbindung). Nicht simuliert: echter Empfang, Verstärkung, `ppm`, AM-Direct-Sampling,
echte RDS-Dekodierung. Dafür einen echten Stick in die VM durchreichen:
`scripts/run-vm.sh --phone 0bda:2838` (openhu-os; auf dem Host vorher `dvb_usb_rtl28xxu` entladen).

## Tests

```
python3 -m unittest discover -s plugins/org.openhu.radio/tests
```

Tests mit `ffmpeg`/`sox` werden übersprungen, wenn die Programme fehlen.
