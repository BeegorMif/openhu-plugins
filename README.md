# OpenAuto Plugins

Plugin-Repository für [OpenAuto](https://github.com/average-web-dev/openauto) – im Store als Quelle eintragen:

```
github average-web-dev/openauto-plugins main
```

| Plugin | |
|---|---|
| `org.openauto.can` | CAN-Bus über SocketCAN: Fahrzeugdaten (`vehicle.*`), Lenkradtasten, Rückwärtsgang → Kamera, Licht → Nachtmodus. Fahrzeugprofile in `profiles/`. |
| `org.openauto.swc` | Lenkradtasten über Eingabegeräte (USB-Lenkradadapter, IR-Fernbedienungen, Multimedia-Tasten) mit Anlern-Modus |
| `org.openauto.camera` | Rückfahrkamera mit Hilfslinien, im Inhaltsbereich oder als Vollbild, automatisch beim Rückwärtsgang |
| `org.openauto.radio` | FM/AM-Radio mit RTL-SDR-Stick, Sendersuche, Favoriten, RDS (mit `redsea`) |

## Aufbau

```
repo.json                    Name/Beschreibung des Repositories
plugins/<id>/manifest.json   ein Ordner pro Plugin (Format: openauto/docs/plugins.md)
common/oa.py                 API-Client für Python-Plugins, wird über "shared" ins Archiv kopiert
tools/oa-repo-index          baut dist/*.tar.gz und index.json
index.json, dist/            generiert – nicht von Hand ändern
```

Nach jeder Änderung `tools/oa-repo-index` ausführen und `dist/` + `index.json` mit committen
(oder die GitHub-Action `.github/workflows/index.yml` erledigt das nach dem Push).
Für ein neues Release die `version` im Manifest erhöhen, dann bietet der Store ein Update an.

## Eigenes Repository

Dieses Repository forken oder ein leeres mit gleichem Aufbau anlegen, Plugins unter `plugins/` ablegen,
`tools/oa-repo-index` ausführen, pushen und in OpenAuto unter Apps → Store → Quellen
`github <benutzer>/<repo>` eintragen. Zum lokalen Entwickeln: Repo neben `openauto/` legen,
`./run.sh` hängt es als `/opt/openauto-plugins` ein → Quelle `file /opt/openauto-plugins`.

## Tests

```
python3 -m unittest discover -s plugins/org.openauto.can/tests
python3 -m unittest discover -s plugins/org.openauto.swc/tests
python3 -m unittest discover -s plugins/org.openauto.radio/tests
```
