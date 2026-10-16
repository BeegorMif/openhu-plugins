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
| `org.openhu.radio` | FM/AM/DAB+-Radio mit RTL-SDR-Stick, Sendersuche, Favoriten, RDS (mit `redsea`), DAB+ (mit `welle-cli`) |

## Aufbau

```
repo.json                    Name/Beschreibung des Repositories
plugins/<id>/manifest.json   ein Ordner pro Plugin (Format: openhu/docs/plugins.md)
common/openhu.py             API-Client für Python-Plugins, wird über "shared" ins Archiv kopiert
tools/openhu-repo-index      baut dist/*.tar.gz und index.json
index.json, dist/            generiert – nicht von Hand ändern
```

Nach jeder Änderung `tools/openhu-repo-index` ausführen und `dist/` + `index.json` mit committen
(oder die GitHub-Action `.github/workflows/index.yml` erledigt das nach dem Push).
Für ein neues Release die `version` im Manifest erhöhen, dann bietet der Store ein Update an.

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
python3 -m unittest discover -s plugins/org.openhu.can/tests
python3 -m unittest discover -s plugins/org.openhu.swc/tests
python3 -m unittest discover -s plugins/org.openhu.radio/tests
```

## Hinweis

> [!CAUTION]
> Die Plugins wurden größtenteils von einer KI (Anthropic Claude) geschrieben und nur stichprobenartig getestet
> (Kamera mit einer Webcam, CAN und Radio mit Unit-Tests, nicht im Fahrzeug). Nutzung auf eigene Gefahr, keine
> Gewährleistung. Nicht während der Fahrt bedienen.
