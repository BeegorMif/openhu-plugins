# OpenHU Plugins

Plugin repository for [OpenHU](https://github.com/BeegorMif/openhu), registered in the store as an
official source:

```
github BeegorMif/openhu-plugins main
```

| Plugin | |
|---|---|
| `org.openhu.can` | CAN bus via SocketCAN: vehicle data (`vehicle.*`), steering wheel keys, reverse gear → camera, lights → night mode. Vehicle profiles in `profiles/`. |
| `org.openhu.swc` | Steering wheel keys via input devices (USB steering wheel adapters, IR remote controls, multimedia keys) with a learn mode |
| `org.openhu.camera` | Reverse camera with guide lines, in the content area or full screen, automatically in reverse gear |
| `org.openhu.logger` | Vehicle data logger: records `vehicle.*`, Android Auto state and head unit values on the device (SQLite, compressed, size limit), detects trips and high-rate recordings; interface for other plugins (trips, measurements, live values) |
| `org.beegor.display` | Monitor brightness from a CAN signal and status bar controls for blackout and DDC/CI power off |
| `org.openhu.radio` | FM/AM/DAB+ radio with an RTL-SDR stick, station scan, favorites, RDS (`redsea`), DAB+ with DLS and slideshow (own decoder `openhu-dab`); one archive per architecture (amd64, arm64) |

## Layout

```
repo.json                    name/description of the repository
plugins/<id>/manifest.json   one folder per plugin (format: openhu/docs/plugins.md)
common/openhu.py             API client for Python plugins, copied into the archive via "shared"
tools/openhu-repo-index      builds dist/*.tar.gz and index.json
tools/openhu-translations    keeps plugins/<id>/i18n/*.ts up to date and compiles the .qm files
index.json, dist/            generated – do not edit by hand
```

Run `tools/openhu-repo-index` after every change and commit `dist/` + `index.json` as well
(or let the GitHub action `.github/workflows/index.yml` do it after the push).
For a new release, raise the `version` in the manifest, then the store offers an update.

Versions: all plugins start with the first real release at `1.0.0` (the 2.x versions before were development
states). The store only offers higher versions as an update: on devices with a 2.x state, remove the plugins and
install them again once.

## Translations

The plugins follow OpenHU's language (English, German; [openhu/docs/translations.md](https://github.com/BeegorMif/openhu/blob/main/docs/translations.md)).
The code only contains text IDs prefixed with the plugin ID; the texts per language are in
`plugins/<id>/i18n/<language>.ts`, English included:

- QML: `qsTrId("org.openhu.radio.main.scan")`, arguments with `.arg()` (`%1`, `%2`)
- Process (messages it publishes): `texts = Texts()` from `openhu.py`, `texts.tr("org.openhu.radio.error.no_stick")`
  or `texts.text(...)` for messages that are stored and published again after a language change (`ui.language`)
  (`texts.follow(api, publish_state)`). It reads the same `.ts` files.
- Name and description in the dock and the store: `<id>.name`, `<id>.description`; the manifest holds the English ones.
- Technical system messages (e.g. `can0: No such device`) stay as they are.

```
tools/openhu-translations             # adapt the .ts files to the code (new IDs untranslated), compile the .qm files
linguist plugins/<id>/i18n/en.ts plugins/<id>/i18n/de.ts   # write the texts (or in an editor)
tools/openhu-translations             # then compile the .qm files again and commit them
tools/openhu-translations --check     # as in CI: everything translated, no texts without an ID, .qm up to date
```

A new language: `tools/openhu-translations --add fr`, translate, commit the `.ts` and `.qm` files. The `.qm` files are
committed so the archives can be built without Qt; compiling needs `lrelease` (Debian: `qt6-l10n-tools`, or in the
OpenHU container with `docker/dev.sh shell`). A line whose text is intentionally not translated (symbols, examples)
gets the comment `// untranslated`.

## Your own repository

Fork this repository or create an empty one with the same layout, put plugins under `plugins/`, run
`tools/openhu-repo-index`, push, and add `github <user>/<repo>` in OpenHU under **Settings → Apps & Store → Sources**.
For local development, put the repository next to the OpenHU repository; `docker/run.sh` (in the OpenHU repository)
mounts it as `/opt/openhu-plugins` → source `file /opt/openhu-plugins`.

For development, a plugin process can also run on your own machine and talk to a head unit on the network:
`PYTHONPATH=common OPENHU_API_URL=ws://<head-unit>:5520 OPENHU_API_TOKEN=<token> python3 plugins/<id>/bin/<name>.py`
(token under **Settings → Network → API token**; the API must be enabled for the network there). On the head unit
itself, plugins need no token.

Plugin format, QML module and a complete example: [openhu/docs/plugins.md](https://github.com/BeegorMif/openhu/blob/main/docs/plugins.md),
API: [openhu/docs/api.md](https://github.com/BeegorMif/openhu/blob/main/docs/api.md).

## Tests

```
python3 -m unittest discover -s tests          # openhu.py, translations
python3 -m unittest discover -s plugins/org.openhu.can/tests
python3 -m unittest discover -s plugins/org.openhu.swc/tests
python3 -m unittest discover -s plugins/org.openhu.radio/tests
python3 -m unittest discover -s plugins/org.openhu.logger/tests
```

## Notice

> [!CAUTION]
> The plugins were mostly written by an AI (Anthropic Claude) and only tested by sampling (camera with a webcam, CAN
> and radio with unit tests, not in a vehicle). Use at your own risk, no warranty. Do not operate while driving.
