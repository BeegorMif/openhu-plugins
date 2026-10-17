# Radio (`org.openhu.radio`)

FM/AM/DAB+-Radio mit einem RTL-SDR-USB-Stick: `rtl_fm` → `pacat`, RDS über `redsea` (mit `sox`), Sendersuche über
`rtl_power`; DAB+ über den eigenen Decoder `openhu-dab`. `openhu-dab` und `redsea` kommen mit dem Plugin (ein Archiv
pro Architektur, amd64 und arm64, gebaut für Debian trixie, siehe [Eigene Programme](#eigene-programme)).

**Pakete auf der Head-Unit** (Debian trixie; im OpenHU-OS-Image enthalten, auch in `packages` im Manifest):

| Paket | wofür |
|---|---|
| `rtl-sdr` | `rtl_fm`, `rtl_power` (FM/AM, Sendersuche) |
| `pulseaudio-utils` | `pacat` (Ton) |
| `sox` | RDS (Ton aus dem FM-Multiplex) |
| `librtlsdr0`, `libfaad2`, `libfftw3-single3`, `libsamplerate0` | Bibliotheken von `openhu-dab` |
| `libliquid1`, `libsndfile1` | Bibliotheken von `redsea` |

Fehlt eine Bibliothek, zeigt die Seite, welche (z. B. „DAB nicht verfügbar, es fehlt: librtlsdr.so.0 (librtlsdr0)“),
ebenso `radio.state.dabMissing` / `rdsMissing`. Für den DVB-T-Treiber gilt wie immer: `dvb_usb_rtl28xxu` darf den
Stick nicht belegen (im OS-Image gesperrt).

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

- **Empfang:** `openhu-dab --channel <Kanal> --service <sid> --rate 48000 --events-fd <fd> --slides <dir>`
  (dazu `--gain`, `--ppm`, `--bias-tee` aus der Konfiguration). Ton: PCM (s16le, Stereo, 48 kHz) direkt aus
  `openhu-dab` in `pacat`, kein MP3-Umweg, kein Netzwerk-Port. Ein Stick: der Bandwechsel beendet FM/AM bzw.
  `openhu-dab`.
- **Metadaten:** Dienstname als `rds.ps`, DLS (Dynamic Label) als `rds.rt`, Ensemble in `radio.state.dab`.
- **Slideshow (MOT SLS):** das Bild aus der Sendung im Thema `radio.slide` (`{band, station, image}`, Data-URL) und
  als `media.metadata.cover` (sonst das Senderlogo). Nur Bilder, die der Sender selbst ausstrahlt.
- **Sendersuche:** `openhu-dab --scan` geht alle Kanäle nacheinander durch: bis zu `dabSyncSeconds` (3 s) für ein
  DAB-Signal, mit Signal höchstens `dabScanSeconds` (10 s) für Ensemble und Dienstnamen. Dauert einige Minuten;
  Fortschritt in `radio.state.scan`, „Abbrechen“ (`stop`) behält die alte Liste. `dabChannels` in `config.json`
  beschränkt die Suche auf bestimmte Kanäle (z. B. `["5C", "7A", "8C"]` in Hannover).
- **Kein Stick / Stick belegt:** `openhu-dab` meldet `no-device` bzw. `device-busy` und endet; die Seite zeigt
  „Kein RTL-SDR-Stick gefunden“ bzw. „Der RTL-SDR-Stick wird von einem anderen Programm benutzt“.
- **Antennenspeisung:** `"biasTee": true` in `config.json` schaltet die Phantomspeisung des Sticks ein (RTL-SDR Blog
  V3/V4 und kompatible) für aktive Antennen.

Der echte DAB-Empfang ist noch nicht mit einem Stick getestet (nur der simulierte Stick und der Start von
`openhu-dab` ohne Stick); offen ist auch, wie viel CPU `openhu-dab` auf einem Raspberry Pi 4 neben der Android-Auto-
Videodekodierung braucht (auf arm64 nutzt der Viterbi-Decoder noch keine NEON-Befehle).

### openhu-dab

Eigener kleiner Empfänger auf der DAB-Bibliothek von [dab-cmdline](https://github.com/JvanKatwijk/dab-cmdline)
(J. van Katwijk), Quelltext in [`native/openhu-dab/`](native/openhu-dab). Kein Netzwerk-Port; beendet sich sauber bei
SIGTERM und mit dem Plugin (`PR_SET_PDEATHSIG`).

```
openhu-dab --channel 7A [--service 0xD882] [Optionen]   Kanal einstellen, Ensemble/Dienste melden, Dienst spielen
openhu-dab --scan [--channels 5C,7A] [Optionen]          Kanäle nacheinander absuchen, dann Ende
  --gain DB|auto  --ppm N  --bias-tee  --device N  --rate N (Standard 48000, 0 = Rate des Dienstes)
  --events-fd N (Standard 2)  --slides DIR (sonst base64 im Ereignis)  --sync-seconds N  --scan-seconds N
```

Ton: PCM s16le Stereo auf stdout, auf `--rate` umgerechnet (libsamplerate), damit `pacat` bei 32-kHz-Diensten nicht
neu starten muss. Ereignisse: eine JSON-Zeile pro Ereignis auf `--events-fd`:

| `event` | Felder |
|---|---|
| `device` | `name`, `gain` (Zehntel dB, -1 automatisch), `biasTee`, `version` |
| `tuned` | `channel`, `frequency` (kHz) |
| `sync` | `channel`, `synced` (DAB-Signal gefunden) |
| `ensemble` | `channel`, `id` (`"0x1188"`), `label`, `ecc` (`"0xE0"`, leer solange unbekannt; kann ein zweites Mal kommen) |
| `service` | `channel`, `sid`, `label`, `shortLabel`, `audio`, `dabPlus`, `bitrate` |
| `playing` | `sid`, `label`, `dabPlus`, `bitrate` – der Dienst läuft |
| `audio` | `rate`, `channels` (2), `format` (`s16le`), `sourceRate` – vor dem ersten Ton und wenn sich die Rate ändert |
| `dls` | `sid`, `text` (Dynamic Label) |
| `slide` | `sid`, `mime`, `name`, `size`, `path` (Datei in `--slides`, die letzten zwei bleiben) oder `data` (base64) |
| `signal` | `synced`, `snr`, `fic` (FIC-Qualität in %), höchstens alle 5 s |
| `scan` | `channel`, `index`, `total`, `found` – Beginn eines Kanals beim Suchlauf |
| `channel` | `channel`, `ensemble` (bool), `services` (neue Dienste) – Ende eines Kanals |
| `done` | `complete`, `ensembles`, `services` – Ende des Suchlaufs |
| `error` | `code` (`no-device`, `device-busy`, `device-lost`, `device`, `slides`, …), `message` |

Exit-Status: 0 fertig/beendet, 2 falsche Argumente, 3 Stick-Fehler.

## Eigene Programme

`native/build.sh` baut `openhu-dab` und `redsea` für die Architektur, auf der es läuft (Debian trixie), nach
`bin/<arch>/`, zusammen mit den Lizenzen und `build-info.json`. Die Quellen sind festgelegt und werden mit sha256
geprüft (ein Quell-Tarball pro Projekt statt eines Git-Submoduls: kein Submodul-Checkout, ein Archiv, das so auch
veröffentlicht wird):

| Projekt | Version | Lizenz |
|---|---|---|
| [dab-cmdline](https://github.com/JvanKatwijk/dab-cmdline) (DAB-Bibliothek) | Commit `8b82305` + [`patches/`](native/openhu-dab/patches) | GPL-2.0-or-later (einzelne Dateien: GPL ohne Version, kjmp2 zlib) |
| [redsea](https://github.com/windytan/redsea) | 1.3.1 | MIT |
| `openhu-dab` selbst | – | GPL-3.0-or-later |

Der Workflow `native.yml` baut beides in einem `debian:trixie`-Container für amd64 und arm64 (GitHub-arm64-Runner)
und startet die Programme einmal (`--version`, `--help`, Fehlerereignis ohne Stick). Nach dem Merge legt
`index.yml` sie in die Archive `dist/org.openhu.radio-<version>-<arch>.tar.gz` und die Quell-Tarballs nach
`dist/sources/` (GPL: die Quellen liegen neben den Programmen); unveränderte Quellen nehmen die Programme aus dem
veröffentlichten Archiv, damit dessen Prüfsumme gleich bleibt. Das Plugin nimmt `bin/<arch>/openhu-dab` und
`bin/<arch>/redsea` für die Architektur des Geräts, sonst (Entwicklung) die aus `PATH`.

Bauabhängigkeiten: `build-essential cmake pkg-config ca-certificates curl patch librtlsdr-dev libfftw3-dev
libfaad-dev zlib1g-dev libsamplerate0-dev meson ninja-build libsndfile1-dev nlohmann-json3-dev libliquid-dev`.

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

`tools/fake-sdr/` ersetzt `rtl_fm`, `rtl_power`, `redsea` und `openhu-dab`, zum Beispiel in der Entwicklungs-VM. Jeder Sender
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
Web-Streams der Sender; 12D „OpenHU Test“ ist erfunden (Testton, selbst gezeichnete Testbilder als Slideshow). Das
simulierte `openhu-dab` hat dieselben Optionen und Ereignisse wie das echte und braucht `ffmpeg` (Ton als PCM); bei
`"error"` meldet es `no-device` bzw. `device-busy` wie das echte.

**Grenzen:** getestet wird alles oberhalb der Hardware (Plugin, Oberfläche, Favoriten, Suchlauf, RDS-Anzeige,
später die Android-Auto-Anbindung). Nicht simuliert: echter Empfang, Verstärkung, `ppm`, AM-Direct-Sampling,
echte RDS-Dekodierung. Dafür einen echten Stick in die VM durchreichen:
`scripts/run-vm.sh --phone 0bda:2838` (openhu-os; auf dem Host vorher `dvb_usb_rtl28xxu` entladen).

## Tests

```
python3 -m unittest discover -s plugins/org.openhu.radio/tests
```

Tests mit `ffmpeg`/`sox` werden übersprungen, wenn die Programme fehlen. Die Plugin-Tests nutzen das simulierte
`openhu-dab`; das echte wird in CI gebaut und ohne Stick gestartet (`native.yml`).
