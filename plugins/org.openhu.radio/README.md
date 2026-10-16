# Radio (`org.openhu.radio`)

FM/AM/DAB+-Radio mit einem RTL-SDR-USB-Stick: `rtl_fm` → `pacat`, RDS über `redsea` (mit `sox`), Sendersuche über
`rtl_power`; DAB+ über `welle-cli`. Pakete auf der Head-Unit: `rtl-sdr`, `pulseaudio-utils`, für RDS zusätzlich
`redsea` und `sox`, für DAB+ `welle.io` (enthält `welle-cli`) und `mpg123`.

Status `radio.state`, Befehle `radio.command` und Konfiguration: siehe Kopf von [`bin/radio.py`](bin/radio.py).
`radio.state.bands` enthält beide Bänder mit Sendern, Favoriten und den RDS-Namen und PI-Codes, die sich das Plugin
pro Frequenz merkt (für Android Auto, openhu#75).

**RDS-PI:** Der PI-Code kennzeichnet ein Programm unabhängig von der Frequenz (NDR 2 ist `0xD382` auf 96,2 MHz in
Hannover wie auf 97,8 MHz in Lingen). Das Plugin zeigt ihn in `radio.state.rds.pi`, merkt ihn sich pro Frequenz
(`bands.fm.pis`) und stellt mit `{"cmd": "tunePi", "value": "0xD382"}` die stärkste bekannte Frequenz des Programms
ein (Pegel aus dem letzten Suchlauf); kennt es keine, steht ein Fehler in `radio.state.error`. Android Auto kann
Sender so über den PI wählen.

## DAB+

Das Band `dab` (Knopf „DAB+“): ein Sender ist ein Dienst in einem Ensemble (Multiplex) auf einem Kanal 5A–13F, sein
Schlüssel die Service-ID (`"0xD882"`) statt einer Frequenz (`frequency`, `stations`, `presets`, `tune`).

- **Empfang:** `welle-cli -c <Kanal> -w 7979 -T` (Web-Server-Modus, das Plugin fragt nur `127.0.0.1` ab). Ton:
  `/mp3/<sid>` → `mpg123` (oder `ffmpeg`) → `pacat`, 48 kHz Stereo. Ein Stick: der Bandwechsel beendet FM/AM bzw.
  `welle-cli`.
- **Metadaten:** Dienstname als `rds.ps`, DLS (Dynamic Label) als `rds.rt`, Ensemble in `radio.state.dab`.
- **Slideshow (MOT SLS):** das Bild aus der Sendung im Thema `radio.slide` (`{band, station, image}`, Data-URL) und
  als `media.metadata.cover` (sonst das Senderlogo). Nur Bilder, die der Sender selbst ausstrahlt.
- **Sendersuche:** alle Kanäle nacheinander (`POST /channel`), je bis zu `dabScanSeconds` (5 s) bis zum Ensemble,
  dauert einige Minuten; Fortschritt in `radio.state.scan`, „Abbrechen“ (`stop`) behält die alte Liste.
  `dabChannels` in `config.json` beschränkt die Suche auf bestimmte Kanäle (z. B. `["5C", "7A", "8C"]` in Hannover).
- **Kein Stick:** `welle-cli` 2.4 beendet sich dann nicht, sondern läuft mit einem „Null device“ weiter; das Plugin
  erkennt das an `/mux.json` und meldet „Kein RTL-SDR-Stick gefunden“.

Der echte DAB-Empfang ist noch nicht mit einem Stick getestet (nur der simulierte Stick); offen ist auch, wie viel
CPU `welle-cli` auf einem Raspberry Pi 4 neben OpenHU braucht. Achtung: `welle-cli` lauscht auf allen
Netzwerkschnittstellen (Port `dabPort`, ohne Passwort, erlaubt auch das Umschalten des Kanals).

## Senderlogos

Das Plugin bringt keine Logos mit (sie sind Marken der Sender) und lädt nichts aus dem Internet. Eigene Bilder
kommen in den Ordner `logos/` im Datenverzeichnis des Plugins (`~/.openhu/plugin-data/org.openhu.radio/logos/`,
legt das Plugin beim Start an):

| Dateiname | gilt für |
|---|---|
| `96.2.png`, `96,2.jpg` | UKW 96,2 MHz |
| `1008.png` | MW 1008 kHz |
| `NDR 2.png`, `ndr2.jpg` | den Sender, dessen RDS-Name (DAB: Dienstname) sich das Plugin gemerkt hat (Groß-/Kleinschreibung, Leer- und Satzzeichen zählen nicht) |
| `0xD882.png` | den DAB-Dienst mit dieser Service-ID |

Die Frequenz hat Vorrang vor dem Namen. PNG oder JPEG, höchstens 512 KB (256×256 Pixel reichen; OpenHU verkleinert
sie für Android Auto auf 128×128). Neue oder geänderte Dateien erkennt das Plugin nach spätestens 10 Sekunden.

Die Logos stehen als Data-URLs im Thema `radio.logos` (`{"fm": {"96.2": "data:image/png;base64,…"}, "am": {…}}`),
nur bei Änderungen gesendet, damit `radio.state` klein bleibt. Sie erscheinen auf der Seite des Plugins, als Cover
auf der Startseite (`media.metadata.cover`, solange das Radio spielt) und in Android Auto bei Senderliste,
Favoriten und aktuellem Sender.

## Simulierter Stick (Test ohne Hardware)

`tools/fake-sdr/` ersetzt `rtl_fm`, `rtl_power`, `redsea` und `welle-cli`, zum Beispiel in der Entwicklungs-VM. Jeder Sender
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
Radio Hannover, Leibniz.FM auf ihren echten UKW-Frequenzen mit ihren echten PI-Codes laut FMLIST, ein Testton auf
87,6 MHz). Logos haben dort nur die beiden Testtöne (selbst gezeichnete Sinuskurven); Senderlogos zum Testen selbst in
`logos/` legen. Pfad auch über `OPENHU_FAKE_SDR_STATIONS`.

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
| `pi` | RDS-PI-Code, z. B. `"0xD382"` (Standard: aus dem Namen abgeleitet); gleicher PI auf zwei Frequenzen = ein Programm auf zwei Sendern |
| `url` | Stream (MP3, AAC, HLS, Icecast, auch `.m3u`/`.pls`) oder lokale Datei (läuft in Schleife) |
| `tone` | statt `url`: Sinuston in Hz, ohne Netzwerk und ohne `ffmpeg` |
| `rt` | fester RDS-Radiotext (Standard: Titel aus dem Stream, sonst `name`) |
| `level` | Pegel für die Sendersuche in dB (Standard -10, Rauschen -40, unter -30 wird der Sender nicht gefunden) |
| `logo` | Senderlogo, lokale PNG/JPEG-Datei (relativ zur Senderliste); eine Datei in `logos/` hat Vorrang |

Die Streams in der Liste sind die öffentlichen Web-Streams der Sender, zum Anhören beim Testen. Eigene Listen
bitte nur mit Streams, die man so nutzen darf.

**DAB+ simuliert:** Abschnitt `dab` der Senderliste – Ensembles mit Kanal, Ensemble-ID, Name und Diensten
(`sid`, `label`, `shortLabel`, `url` oder `tone`, `dls` fest statt des Stream-Titels, `slides` als Slideshow-Bilder
im Wechsel alle `slideSeconds`, `logo`). Mitgeliefert: die Hannoveraner Ensembles 5C (DR Deutschland), 7A (NDR NDS)
und 8C (NI HANNOVER K8C) mit echten Kanälen, Ensemble- und Service-IDs laut DABLIST (sender-tabelle.de) und den
Web-Streams der Sender; 12D „OpenHU Test“ ist erfunden (Testton, selbst gezeichnete Testbilder als Slideshow). Der
simulierte `welle-cli` braucht `ffmpeg` (MP3), das Plugin nimmt `ffmpeg` statt `mpg123`, wenn das fehlt. Wie der
echte läuft er bei `"error"` ohne Stick mit „Null device“ weiter.

**Grenzen:** getestet wird alles oberhalb der Hardware (Plugin, Oberfläche, Favoriten, Suchlauf, RDS-Anzeige,
später die Android-Auto-Anbindung). Nicht simuliert: echter Empfang, Verstärkung, `ppm`, AM-Direct-Sampling,
echte RDS-Dekodierung. Dafür einen echten Stick in die VM durchreichen:
`scripts/run-vm.sh --phone 0bda:2838` (openhu-os; auf dem Host vorher `dvb_usb_rtl28xxu` entladen).

## Tests

```
python3 -m unittest discover -s plugins/org.openhu.radio/tests
```

Tests mit `ffmpeg`/`sox` werden übersprungen, wenn die Programme fehlen.
