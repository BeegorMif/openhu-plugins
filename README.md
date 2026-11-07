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
| `org.openhu.media` | Music player for USB sticks and the head unit's Music folder: albums, artists, songs, playlists (M3U, PLS, XSPF, own playlists on the stick) and folders, a queue with order, shuffle and random, gapless playback with `mpv` |

## Layout

```
repo.json                    name/description of the repository
plugins/<id>/manifest.json   one folder per plugin (format: openhu/docs/plugins.md)
common/openhu.py             API client for Python plugins, copied into the archive via "shared"
common/openhu.ts             the same for TypeScript plugins run with bun (copy it via "shared" as well)
common/qml/                  QML components and icons of the radio and music pages ("shared": ["qml"]);
                             plugins/<id>/lib is a symlink to common/ so the pages also work from the checkout
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

## Settings

Settings a user may change are declared in the manifest's `settings` (switch, choice, number, text, section) and show
up in OpenHU under Settings → Apps → Installed → Settings. The values live in OpenHU's config store for the plugin
(`~/.openhu/plugin-data/<id>/config.json`, format and API: openhu/docs/plugins.md). In Python, `load_config()` and
`save_config()` go through the store, `follow_config(api, config, on_change)` keeps the dict current when a value is
changed in the settings; `api.config` and `api.on_config()` are the direct way (TypeScript: `api.config`,
`api.onConfig()`). Titles and descriptions are translated like the other texts: `<id>.settings.<key>`,
`<id>.settings.<key>.description` and `<id>.settings.<key>.<option>`; `tools/openhu-translations` adds them.

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
python3 -m unittest discover -s plugins/org.openhu.media/tests
bun test tests/ts                              # openhu.ts
```

## Notice

> [!CAUTION]
> The plugins were mostly written by an AI (Anthropic Claude) and only tested by sampling (camera with a webcam, CAN
> and radio with unit tests, not in a vehicle). Use at your own risk, no warranty. Do not operate while driving.
