# Radio (`org.openhu.radio`)

FM/AM/DAB+ radio with an RTL-SDR USB stick: `rtl_fm` → `pacat`, RDS via `redsea` (with `sox`), station scan via
`rtl_power`; DAB+ via the own decoder `openhu-dab`. `openhu-dab` and `redsea` come with the plugin (one archive per
architecture, amd64 and arm64, built for Debian trixie, see [Own programs](#own-programs)).

**Packages on the head unit** (Debian trixie; included in the OpenHU OS image, also in `packages` in the manifest):

| Package | What for |
|---|---|
| `rtl-sdr` | `rtl_fm`, `rtl_power` (FM/AM, station scan) |
| `pulseaudio-utils` | `pacat` (sound) |
| `sox` | RDS (audio from the FM multiplex) |
| `librtlsdr0`, `libfaad2`, `libfftw3-single3`, `libsamplerate0` | libraries of `openhu-dab` |
| `libliquid1`, `libsndfile1` | libraries of `redsea` |

If a library is missing, the page shows which one (e.g. "DAB not available, missing: librtlsdr.so.0 (librtlsdr0)"),
and so do `radio.state.dabMissing` / `rdsMissing`. As always, the DVB-T driver `dvb_usb_rtl28xxu` must not claim
the stick (blocked in the OS image).

**Page:** band tabs; the station that plays with its logo or DAB slideshow picture (initials on a colour of the
name without one), radio text and a soft background from the picture; for FM/AM a scale to tap or drag to any
frequency and − / + (held: faster, after about 1.5 s in bigger steps); the frequency is tuned when the finger is
lifted. The station list shows the favorites first, a heart in each row keeps or removes a station, the station that
plays shows its radio text. The icons are drawn for the plugin (`qml/Icons.js`).

State `radio.state`, commands `radio.command` and configuration: see the head of [`bin/radio.py`](bin/radio.py).
`radio.state.bands` contains both bands with stations, favorites and the RDS names and PI codes the plugin remembers
per frequency (for Android Auto, openhu#75).

**RDS PI:** The PI code identifies a program independently of the frequency (NDR 2 is `0xD382` on 96.2 MHz in
Hannover as well as on 97.8 MHz in Lingen). The plugin shows it in `radio.state.rds.pi`, remembers it per frequency
(`bands.fm.pis`) and, with `{"cmd": "tunePi", "value": "0xD382"}`, tunes to the strongest known frequency of the
program (level from the last scan); if it knows none, an error appears in `radio.state.error`. This way Android Auto
can select stations by their PI.

## DAB+

The band `dab` (tab "DAB+"): a station is a service in an ensemble (multiplex) on a channel 5A–13F, its key is the
service ID (`"0xD882"`) instead of a frequency (`frequency`, `stations`, `presets`, `tune`).

- **Reception:** `openhu-dab --channel <channel> --service <sid> --rate 48000 --events-fd <fd> --slides <dir>`
  (plus `--gain`, `--ppm`, `--bias-tee` from the configuration). Audio: PCM (s16le, stereo, 48 kHz) straight from
  `openhu-dab` into `pacat`, no MP3 detour, no network port. One stick: switching the band ends FM/AM or
  `openhu-dab`.
- **Metadata:** service name as `rds.ps`, DLS (Dynamic Label) as `rds.rt`, ensemble in `radio.state.dab`.
- **Slideshow (MOT SLS):** the picture from the broadcast in the topic `radio.slide` (`{band, station, image}`, data
  URL) and as `media.metadata.cover` (otherwise the station logo). Only pictures the station broadcasts itself.
- **Station scan:** `openhu-dab --scan` goes through all channels one after another: up to `dabSyncSeconds` (3 s) for
  a DAB signal, with a signal at most `dabScanSeconds` (10 s) for ensemble and service names. Takes a few minutes;
  progress in `radio.state.scan`, cancelling (✕ above the progress, `stop`) keeps the old list. `dabChannels` in `config.json` restricts the
  scan to certain channels (e.g. `["5C", "7A", "8C"]` in Hannover).
- **No stick / stick busy:** `openhu-dab` reports `no-device` or `device-busy` and exits; the page shows
  "No RTL-SDR stick found" or "The RTL-SDR stick is used by another program".
- **Antenna power:** `"biasTee": true` in `config.json` switches on the stick's phantom power (RTL-SDR Blog V3/V4 and
  compatible) for active antennas.

Real DAB reception has not been tested with a stick yet (only the simulated stick and the start of `openhu-dab`
without a stick); it is also open how much CPU `openhu-dab` needs on a Raspberry Pi 4 next to the Android Auto video
decoding (on arm64, the Viterbi decoder does not use NEON instructions yet).

### openhu-dab

Own small receiver on the DAB library of [dab-cmdline](https://github.com/JvanKatwijk/dab-cmdline)
(J. van Katwijk), source in [`native/openhu-dab/`](native/openhu-dab). No network port; exits cleanly on
SIGTERM and with the plugin (`PR_SET_PDEATHSIG`).

```
openhu-dab --channel 7A [--service 0xD882] [options]   tune the channel, report ensemble/services, play a service
openhu-dab --scan [--channels 5C,7A] [options]         scan the channels one after another, then exit
  --gain DB|auto  --ppm N  --bias-tee  --device N  --rate N (default 48000, 0 = rate of the service)
  --events-fd N (default 2)  --slides DIR (otherwise base64 in the event)  --sync-seconds N  --scan-seconds N
```

Audio: PCM s16le stereo on stdout, converted to `--rate` (libsamplerate), so `pacat` does not have to restart for
32 kHz services. Events: one JSON line per event on `--events-fd`:

| `event` | Fields |
|---|---|
| `device` | `name`, `gain` (tenths of dB, -1 automatic), `biasTee`, `version` |
| `tuned` | `channel`, `frequency` (kHz) |
| `sync` | `channel`, `synced` (DAB signal found) |
| `ensemble` | `channel`, `id` (`"0x1188"`), `label`, `ecc` (`"0xE0"`, empty while unknown; can come a second time) |
| `service` | `channel`, `sid`, `label`, `shortLabel`, `audio`, `dabPlus`, `bitrate` |
| `playing` | `sid`, `label`, `dabPlus`, `bitrate` – the service is playing |
| `audio` | `rate`, `channels` (2), `format` (`s16le`), `sourceRate` – before the first sound and when the rate changes |
| `dls` | `sid`, `text` (Dynamic Label) |
| `slide` | `sid`, `mime`, `name`, `size`, `path` (file in `--slides`, the last two are kept) or `data` (base64) |
| `signal` | `synced`, `snr`, `fic` (FIC quality in %), at most every 5 s |
| `scan` | `channel`, `index`, `total`, `found` – start of a channel during the scan |
| `channel` | `channel`, `ensemble` (bool), `services` (new services) – end of a channel |
| `done` | `complete`, `ensembles`, `services` – end of the scan |
| `error` | `code` (`no-device`, `device-busy`, `device-lost`, `device`, `slides`, …), `message` |

Exit status: 0 done/ended, 2 wrong arguments, 3 stick error.

## Own programs

`native/build.sh` builds `openhu-dab` and `redsea` for the architecture it runs on (Debian trixie) into
`bin/<arch>/`, together with the licenses and `build-info.json`. The sources are pinned and checked with sha256
(one source tarball per project instead of a git submodule: no submodule checkout, and an archive that is published
as it is):

| Project | Version | License |
|---|---|---|
| [dab-cmdline](https://github.com/JvanKatwijk/dab-cmdline) (DAB library) | commit `8b82305` + [`patches/`](native/openhu-dab/patches) | GPL-2.0-or-later (individual files: GPL without version, kjmp2 zlib) |
| [redsea](https://github.com/windytan/redsea) | 1.3.1 | MIT |
| `openhu-dab` itself | – | GPL-3.0-or-later |

The workflow `native.yml` builds both in a `debian:trixie` container for amd64 and arm64 (GitHub arm64 runner) and
starts the programs once (`--version`, `--help`, error event without a stick). After the merge, `index.yml` puts them
into the archives `dist/org.openhu.radio-<version>-<arch>.tar.gz` and the source tarballs into `dist/sources/` (GPL:
the sources are published next to the programs); unchanged sources take the programs from the published archive so
that its checksum stays the same. The plugin uses `bin/<arch>/openhu-dab` and `bin/<arch>/redsea` for the device's
architecture, otherwise (development) the ones from `PATH`.

Build dependencies: `build-essential cmake pkg-config ca-certificates curl patch librtlsdr-dev libfftw3-dev
libfaad-dev zlib1g-dev libsamplerate0-dev meson ninja-build libsndfile1-dev nlohmann-json3-dev libliquid-dev`.

## Station logos

The plugin does not bring any logos (they are trademarks of the stations) and does not load anything from the
internet. Your own pictures go into the folder `logos/` in the plugin's data directory
(`~/.openhu/plugin-data/org.openhu.radio/logos/`, created by the plugin at startup):

| File name | applies to |
|---|---|
| `96.2.png`, `96,2.jpg` | FM 96.2 MHz |
| `1008.png` | MW 1008 kHz |
| `NDR 2.png`, `ndr2.jpg` | the station whose RDS name (DAB: service name) the plugin has remembered (case, spaces and punctuation do not matter) |
| `0xD882.png` | the DAB service with this service ID |

The frequency takes precedence over the name. PNG or JPEG, at most 512 KB (256×256 pixels are enough; OpenHU scales
them down to 128×128 for Android Auto). The plugin notices new or changed files after 10 seconds at the latest.

The logos are in the topic `radio.logos` as data URLs (`{"fm": {"96.2": "data:image/png;base64,…"}, "am": {…}}`),
sent only on changes so `radio.state` stays small. They appear on the plugin's page, as cover on the home page
(`media.metadata.cover`, while the radio is playing) and in Android Auto in the station list, favorites and the
current station.

## Simulated stick (test without hardware)

`tools/fake-sdr/` replaces `rtl_fm`, `rtl_power`, `redsea` and `openhu-dab`, for example in the development VM. It is
a development tool only: the plugin itself never needs the internet. Each station in a station list plays an
**internet radio stream** (or a file, or a test tone), as if it were received over FM:

- Tuning to a frequency from the list plays its stream, in between there is quiet noise.
- RDS: station name from the list, radio text is the current title from the stream (Icecast metadata).
- The station scan finds exactly the stations of the list.
- If the stream breaks off, there is noise until it is connected again.
- Errors for testing: `"error": "no-device"` or `"busy"` in the station list.

The UI then shows "Simulated stick", `radio.state` has `simulated: true`.

**Switching it on** (one of these):

- `"fakeSdr": true` in `config.json` in the plugin's data directory
  (`~/.openhu/plugin-data/org.openhu.radio/config.json`),
- command `radio.command` `{"cmd": "fakeSdr", "value": true}` (takes effect immediately, is saved),
- environment variable `OPENHU_FAKE_SDR=1` for the plugin process.

A real stick is not touched meanwhile; switch it off with `false`.

**Needs:** `ffmpeg` for streams and files (test tone stations work without), `sox` for RDS, `pacat` as always.

**Station list:** `fake-sdr-stations.json` in the plugin's data directory, otherwise the bundled
[`tools/fake-sdr/stations.json`](tools/fake-sdr/stations.json) (Hannover area: NDR, Deutschlandfunk, ffn, Radio 21,
Radio Hannover, Leibniz.FM on their real FM frequencies with their real PI codes according to FMLIST, a test tone on
87.6 MHz). Only the two test tones have logos there (self-drawn sine waves); to test station logos, put them into
`logos/` yourself. The path can also be set with `OPENHU_FAKE_SDR_STATIONS`.

```json
{
  "fm": [
    {"frequency": 96.2, "name": "NDR 2", "ps": "NDR 2", "url": "https://icecast.ndr.de/ndr/ndr2/niedersachsen/mp3/128/stream.mp3"},
    {"frequency": 87.6, "name": "Test tone", "ps": "TESTTON", "tone": 440, "rt": "Simulated station"}
  ],
  "am": [
    {"frequency": 1008, "name": "AM test", "tone": 800}
  ],
  "error": null
}
```

| Field | |
|---|---|
| `frequency` | MHz (FM, 0.1 grid) or kHz (AM) |
| `name` | name, default for RDS |
| `ps` | RDS station name, 8 characters (default: `name`) |
| `pi` | RDS PI code, e.g. `"0xD382"` (default: derived from the name); the same PI on two frequencies = one program on two transmitters |
| `url` | stream (MP3, AAC, HLS, Icecast, also `.m3u`/`.pls`) or local file (loops) |
| `tone` | instead of `url`: sine tone in Hz, without network and without `ffmpeg` |
| `rt` | fixed RDS radio text (default: title from the stream, otherwise `name`) |
| `level` | level for the station scan in dB (default -10, noise -40, below -30 the station is not found) |
| `logo` | station logo, local PNG/JPEG file (relative to the station list); a file in `logos/` takes precedence |

The streams in the list are the stations' public web streams, to listen to while testing. Please only use your own
lists with streams you may use this way.

**Simulated DAB+:** section `dab` of the station list – ensembles with channel, ensemble ID, name and services
(`sid`, `label`, `shortLabel`, `url` or `tone`, `dls` fixed instead of the stream title, `slides` as slideshow
pictures alternating every `slideSeconds`, `logo`). Included: the Hannover ensembles 5C (DR Deutschland), 7A (NDR NDS)
and 8C (NI HANNOVER K8C) with real channels, ensemble and service IDs according to DABLIST (sender-tabelle.de) and the
stations' web streams; 12D "OpenHU Test" is made up (test tone, self-drawn test pictures as slideshow). The simulated
`openhu-dab` has the same options and events as the real one and needs `ffmpeg` (audio as PCM); with `"error"` it
reports `no-device` or `device-busy` like the real one.

**Limits:** everything above the hardware is tested (plugin, UI, favorites, scan, RDS display, later the Android Auto
integration). Not simulated: real reception, gain, `ppm`, AM direct sampling, real RDS decoding. For that, pass a real
stick through to the VM: `scripts/run-vm.sh --phone 0bda:2838` (openhu-os; unload `dvb_usb_rtl28xxu` on the host
first).

## Tests

```
python3 -m unittest discover -s plugins/org.openhu.radio/tests
```

Tests with `ffmpeg`/`sox` are skipped if the programs are missing. The plugin tests use the simulated
`openhu-dab`; the real one is built in CI and started without a stick (`native.yml`).
