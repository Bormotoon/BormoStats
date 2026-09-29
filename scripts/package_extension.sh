#!/usr/bin/env bash
# Build a release archive of the browser extension with a SHA-256 checksum and,
# when EXTENSION_SIGNING_KEY (a GPG key id) is set, a detached signature.
# Chrome Web Store uploads are signed by the store; the checksum/signature let
# self-hosted installs verify the artifact they load.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/browser_extension"
OUT="$ROOT_DIR/dist/extension"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/manifest.json")"
ARCHIVE="$OUT/bormostats-extension-$VERSION.zip"

mkdir -p "$OUT"
rm -f "$ARCHIVE" "$ARCHIVE".*
(cd "$SRC" && zip -q -X -r "$ARCHIVE" manifest.json protocol.js background.js content.js popup.html popup.js)
(cd "$OUT" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
if [[ -n "${EXTENSION_SIGNING_KEY:-}" ]]; then
  gpg --batch --yes --local-user "$EXTENSION_SIGNING_KEY" --armor --detach-sign "$ARCHIVE"
fi
echo "Extension package: $ARCHIVE"
