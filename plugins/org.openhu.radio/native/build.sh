#!/bin/bash
# Builds the radio plugin's native tools for the machine it runs on (Debian trixie, amd64 or arm64):
#   openhu-dab   DAB/DAB+ receiver (openhu-dab/, on top of dab-cmdline's DAB library)
#   redsea       RDS decoder for FM (windytan/redsea)
# from pinned upstream sources, checked against their sha256. The binaries, the licences and build-info.json go
# to bin/<arch>/ of the plugin (or --out); the archive for that architecture carries them (tools/openhu-repo-index).
#
#   native/build.sh [--out DIR] [--sources DIR] [--jobs N]
#   native/build.sh --source-hash        hash of everything that goes into the binaries (CI reuses a build)
#
# --sources keeps the downloaded source archives there (and uses them from there: offline builds). They are the
# corresponding source of the binaries; the index workflow publishes them in dist/sources/.
#
# Build dependencies (Debian trixie): build-essential cmake pkg-config ca-certificates curl patch librtlsdr-dev
#   libfftw3-dev libfaad-dev zlib1g-dev libsamplerate0-dev meson ninja-build libsndfile1-dev nlohmann-json3-dev
#   libliquid-dev
#
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

DAB_CMDLINE_COMMIT=8b8230526a68d9ec52911dae0bd455cf1bb2fbad
DAB_CMDLINE_SHA256=4a8e2ef4cd8caf80cceba80208f956c87eff6542d59c830bbaf93c9660929ac9
DAB_CMDLINE_URL=https://github.com/JvanKatwijk/dab-cmdline/archive/$DAB_CMDLINE_COMMIT.tar.gz
REDSEA_VERSION=1.3.1
REDSEA_SHA256=2d1137dba23c1ae2d8af87bda45ab90ee962e55d3b93dc9295d1a53e15a8cfae
REDSEA_URL=https://github.com/windytan/redsea/archive/refs/tags/v$REDSEA_VERSION.tar.gz

HERE=$(cd "$(dirname "$0")" && pwd)
PLUGIN=$(dirname "$HERE")

source_hash() {
    # this script, openhu-dab's sources and patches (the pins are in this script)
    (cd "$HERE" && find . -type f ! -name '*.pyc' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | cut -c1-16
}

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
OUT=""
SOURCES=""
JOBS=$(nproc 2>/dev/null || echo 2)
while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT=$2; shift 2 ;;
        --sources) SOURCES=$2; shift 2 ;;
        --jobs) JOBS=$2; shift 2 ;;
        --source-hash) source_hash; exit 0 ;;
        -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done
OUT=${OUT:-$PLUGIN/bin/$ARCH}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
SOURCES=${SOURCES:-$WORK/sources}
mkdir -p "$SOURCES" "$OUT"

fetch() {  # url sha256 file
    local file=$SOURCES/$3
    if [ ! -f "$file" ]; then
        echo "download $1"
        curl -fsSL --retry 3 -o "$file.part" "$1"
        mv "$file.part" "$file"
    fi
    if ! echo "$2  $file" | sha256sum -c --quiet; then
        echo "error: $file does not match the pinned sha256" >&2
        exit 1
    fi
}

fetch "$DAB_CMDLINE_URL" "$DAB_CMDLINE_SHA256" "dab-cmdline-$DAB_CMDLINE_COMMIT.tar.gz"
fetch "$REDSEA_URL" "$REDSEA_SHA256" "redsea-$REDSEA_VERSION.tar.gz"

echo "== openhu-dab (dab-cmdline ${DAB_CMDLINE_COMMIT:0:7})"
tar -xzf "$SOURCES/dab-cmdline-$DAB_CMDLINE_COMMIT.tar.gz" -C "$WORK"
DAB_SRC=$WORK/dab-cmdline-$DAB_CMDLINE_COMMIT
for patch in "$HERE"/openhu-dab/patches/*.patch; do
    patch -d "$DAB_SRC" -p1 --quiet < "$patch"
done
cmake -S "$HERE/openhu-dab" -B "$WORK/build-dab" -DCMAKE_BUILD_TYPE=Release \
    -DDAB_CMDLINE_DIR="$DAB_SRC" -DDAB_CMDLINE_VERSION="${DAB_CMDLINE_COMMIT:0:7}" >"$WORK/cmake.log" \
    || { cat "$WORK/cmake.log"; exit 1; }
cmake --build "$WORK/build-dab" -j "$JOBS" >"$WORK/build-dab.log" 2>&1 || { tail -40 "$WORK/build-dab.log"; exit 1; }
install -m 755 -s "$WORK/build-dab/openhu-dab" "$OUT/openhu-dab"

echo "== redsea $REDSEA_VERSION"
tar -xzf "$SOURCES/redsea-$REDSEA_VERSION.tar.gz" -C "$WORK"
# system nlohmann-json, no downloads of meson subprojects
meson setup "$WORK/build-redsea" "$WORK/redsea-$REDSEA_VERSION" --buildtype=release --wrap-mode=nodownload \
    >"$WORK/meson.log" || { cat "$WORK/meson.log"; exit 1; }
meson compile -C "$WORK/build-redsea" -j "$JOBS" >"$WORK/build-redsea.log" 2>&1 \
    || { tail -40 "$WORK/build-redsea.log"; exit 1; }
install -m 755 -s "$WORK/build-redsea/redsea" "$OUT/redsea"

# licences next to the binaries (openhu-dab: GPL-3.0-or-later with dab-cmdline's GPL-2.0-or-later code)
install -m 644 "$HERE/openhu-dab/COPYING" "$OUT/COPYING.openhu-dab"
install -m 644 "$DAB_SRC/LICENSE" "$OUT/LICENSE.dab-cmdline"
install -m 644 "$WORK/redsea-$REDSEA_VERSION/LICENSE" "$OUT/LICENSE.redsea"
cat > "$OUT/build-info.json" <<EOF
{
  "arch": "$ARCH",
  "sourceHash": "$(source_hash)",
  "openhu-dab": "$("$OUT/openhu-dab" --version | awk '{print $2}')",
  "dab-cmdline": "$DAB_CMDLINE_COMMIT",
  "redsea": "$REDSEA_VERSION",
  "sources": ["dab-cmdline-$DAB_CMDLINE_COMMIT.tar.gz", "redsea-$REDSEA_VERSION.tar.gz"],
  "system": "$(. /etc/os-release && echo "$ID $VERSION_ID")"
}
EOF

"$OUT/openhu-dab" --version
"$OUT/redsea" --version | head -1
echo "-> $OUT"
