#!/usr/bin/env bash
# Build the Decky plugin zip: decky/out/Synker.zip
#   1. builds the synker binary with PyInstaller (unless SYNKER_BIN points to one)
#   2. builds the frontend with pnpm
#   3. assembles the plugin folder and zips it
set -euo pipefail
cd "$(dirname "$0")/.."
DECKY_DIR=$PWD
ROOT=$(cd .. && pwd)
NAME=Synker

if [[ -z "${SYNKER_BIN:-}" ]]; then
  python3 "$ROOT/packaging/build.py"
  SYNKER_BIN="$ROOT/dist/synker"
fi

pnpm install --frozen-lockfile 2>/dev/null || pnpm install
pnpm run build

OUT="$DECKY_DIR/out"
STAGE="$OUT/$NAME"
rm -rf -- "$STAGE" "$OUT/$NAME.zip"
mkdir -p "$STAGE/dist" "$STAGE/bin"
cp dist/index.js "$STAGE/dist/"
cp main.py plugin.json package.json "$STAGE/"
cp "$ROOT/LICENSE" "$STAGE/LICENSE"
cat LICENSE.decky-template >> "$STAGE/LICENSE"
cp "$ROOT/README.md" "$STAGE/README.md"
install -m 755 "$SYNKER_BIN" "$STAGE/bin/synker"
(cd "$OUT" && zip -qr "$NAME.zip" "$NAME")
echo "Built $OUT/$NAME.zip"
