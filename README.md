# OpenHU Plugins

Plugin-Repository für [OpenHU](https://github.com/average-web-dev/openhu), im Store bereits als offizielle Quelle
eingetragen:

```
github average-web-dev/openhu-plugins main
```

| Plugin | |
|---|---|
| `org.openhu.can` | CAN-Bus über SocketCAN: Fahrzeugdaten (`vehicle.*`), Lenkradtasten, Rückwärtsgang → Kamera, Licht → Nachtmodus. Fahrzeugprofile in `profiles/`. |
| `org.openhu.swc` | Lenkradtasten über Eingabegeräte (USB-Lenkradadapter, IR-Fernbedienungen, Multimedia-Tasten) mit Anlern-Modus |
| `org.openhu.camera` | Rückfahrkamera mit Hilfslinien, im Inhaltsbereich oder als Vollbild, automatisch beim Rückwärtsgang |
| `org.openhu.logger` | Fahrzeugdaten-Logger: zeichnet `vehicle.*`, Android-Auto-Zustand und Werte der Head-Unit auf dem Gerät auf (SQLite, komprimiert, Größenlimit), erkennt Fahrten, hochfrequente Aufnahmen; Schnittstelle für andere Plugins (Fahrten, Messwerte, Live-Werte) |
| `org.openhu.radio` | FM/AM/DAB+-Radio mit RTL-SDR-Stick, Sendersuche, Favoriten, RDS (mit `redsea`), DAB+ (mit `welle-cli`) |

## Aufbau

```
repo.json                    Name/Beschreibung des Repositories
plugins/<id>/manifest.json   ein Ordner pro Plugin (Format: openhu/docs/plugins.md)
common/openhu.py             API-Client für Python-Plugins, wird über "shared" ins Archiv kopiert
tools/openhu-repo-index      baut dist/*.tar.gz und index.json
tools/openhu-translations    hält plugins/<id>/i18n/*.ts aktuell und kompiliert die .qm-Dateien
index.json, dist/            generiert – nicht von Hand ändern
```

Nach jeder Änderung `tools/openhu-repo-index` ausführen und `dist/` + `index.json` mit committen
(oder die GitHub-Action `.github/workflows/index.yml` erledigt das nach dem Push).
Für ein neues Release die `version` im Manifest erhöhen, dann bietet der Store ein Update an.

Versionen: alle Plugins starten mit dem ersten echten Release bei `1.0.0` (die 2.x-Versionen davor waren
Entwicklungsstände). Der Store bietet nur höhere Versionen als Update an: Geräte mit einem 2.x-Stand die Plugins
einmal entfernen und neu installieren.

## Übersetzungen

Die Plugins folgen der Sprache von OpenHU (Englisch, Deutsch; [openhu/docs/translations.md](https://github.com/average-web-dev/openhu/blob/main/docs/translations.md)).
Im Code stehen nur Text-IDs mit der Plugin-ID davor, die Texte pro Sprache in `plugins/<id>/i18n/<sprache>.ts`,
Englisch eingeschlossen:

- QML: `qsTrId("org.openhu.radio.main.scan")`, Argumente mit `.arg()` (`%1`, `%2`)
- Prozess (Meldungen, die er veröffentlicht): `texts = Texts()` aus `openhu.py`, `texts.tr("org.openhu.radio.error.no_stick")`
  oder `texts.text(...)` für Meldungen, die gespeichert und nach einem Sprachwechsel (`ui.language`) neu
  veröffentlicht werden (`texts.follow(api, publish_state)`). Er liest dieselben `.ts`-Dateien.
- Name und Beschreibung in Dock und Store: `<id>.name`, `<id>.description`; im Manifest stehen die englischen.
- Technische Meldungen des Systems (z. B. `can0: No such device`) bleiben, wie sie sind.

```
tools/openhu-translations             # .ts-Dateien an den Code anpassen (neue IDs unübersetzt), .qm kompilieren
linguist plugins/<id>/i18n/en.ts plugins/<id>/i18n/de.ts   # Texte schreiben (oder im Editor)
tools/openhu-translations             # danach die .qm neu kompilieren und mit committen
tools/openhu-translations --check     # wie in der CI: alles übersetzt, keine Texte ohne ID, .qm aktuell
```

Eine neue Sprache: `tools/openhu-translations --add fr`, übersetzen, `.ts` und `.qm` committen. Die `.qm`-Dateien
werden mit committet, damit die Archive ohne Qt gebaut werden; zum Kompilieren braucht man `lrelease`
(Debian: `qt6-l10n-tools`, oder im OpenHU-Container `docker/dev.sh shell`). Eine Zeile, deren Text absichtlich
nicht übersetzt wird (Symbole, Beispiele), bekommt den Kommentar `// untranslated`.

## Eigenes Repository

Dieses Repository forken oder ein leeres mit gleichem Aufbau anlegen, Plugins unter `plugins/` ablegen,
`tools/openhu-repo-index` ausführen, pushen und in OpenHU unter **Einstellungen → Apps & Store → Quellen**
`github <benutzer>/<repo>` eintragen. Zum lokalen Entwickeln: Repo neben das OpenHU-Repository legen,
`docker/run.sh` (im OpenHU-Repo) hängt es als `/opt/openhu-plugins` ein → Quelle `file /opt/openhu-plugins`.

Ein Plugin-Prozess kann zum Entwickeln auch auf dem eigenen Rechner laufen und mit einer Head-Unit im Netzwerk
sprechen: `PYTHONPATH=common OPENHU_API_URL=ws://<head-unit>:5520 OPENHU_API_TOKEN=<token> python3 plugins/<id>/bin/<name>.py` (Token unter
**Einstellungen → Netzwerk → API-Token**, die API muss dort im Netzwerk freigegeben sein). Auf der Head-Unit selbst
brauchen Plugins keinen Token.

Plugin-Format, QML-Modul und ein vollständiges Beispiel: [openhu/docs/plugins.md](https://github.com/average-web-dev/openhu/blob/main/docs/plugins.md),
API: [openhu/docs/api.md](https://github.com/average-web-dev/openhu/blob/main/docs/api.md).

## Tests

```
python3 -m unittest discover -s tests          # openhu.py, Übersetzungen
python3 -m unittest discover -s plugins/org.openhu.can/tests
python3 -m unittest discover -s plugins/org.openhu.swc/tests
python3 -m unittest discover -s plugins/org.openhu.radio/tests
python3 -m unittest discover -s plugins/org.openhu.logger/tests
```

## Hinweis

> [!CAUTION]
> Die Plugins wurden größtenteils von einer KI (Anthropic Claude) geschrieben und nur stichprobenartig getestet
> (Kamera mit einer Webcam, CAN und Radio mit Unit-Tests, nicht im Fahrzeug). Nutzung auf eigene Gefahr, keine
> Gewährleistung. Nicht während der Fahrt bedienen.
