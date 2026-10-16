#!/usr/bin/env bash
# fetch_target.sh — Clone (or update) a legacy demo application at a pinned commit
# into a work directory that MUST be outside this repository.
# Usage: fetch_target.sh <target.json> <dest_dir>
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $(basename "$0") <target.json> <dest_dir>" >&2
    exit 64
fi

TARGET_JSON="$1"
DEST_ARG="$2"

# Read url and commit from the JSON file using python3's json module
URL=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['url'])" "$TARGET_JSON")
COMMIT=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['commit'])" "$TARGET_JSON")

# Resolve dest_dir to an absolute path (does not need to exist)
DEST=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$DEST_ARG")

# Resolve this repository's root: parent of the directory containing this script
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")

# Refuse if dest equals or is inside the repository root
if [[ "$DEST" == "$REPO_ROOT" || "$DEST" == "$REPO_ROOT/"* ]]; then
    echo "Error: destination '$DEST' is inside this repository ('$REPO_ROOT')" >&2
    exit 2
fi

# Clone or fetch
if [[ ! -d "$DEST/.git" ]]; then
    mkdir -p "$(dirname "$DEST")"
    git clone --quiet "$URL" "$DEST"
else
    git -C "$DEST" fetch --quiet origin
fi

# Checkout the pinned commit onto branch 'modernize'
if ! git -C "$DEST" checkout --quiet -f -B modernize "$COMMIT" 2>/dev/null; then
    echo "commit $COMMIT not found in $URL" >&2
    exit 1
fi

# Reset to the exact commit and clean untracked files
git -C "$DEST" reset --quiet --hard "$COMMIT"
git -C "$DEST" clean -fdxq

# Verify HEAD starts with the requested commit
FULL_SHA=$(git -C "$DEST" rev-parse HEAD)
if [[ "$FULL_SHA" != "$COMMIT"* ]]; then
    echo "Error: HEAD ($FULL_SHA) does not match requested commit ($COMMIT)" >&2
    exit 1
fi

# Set a local commit identity for the runner
git -C "$DEST" config user.name "Bob verified runner"
git -C "$DEST" config user.email "runner@example.invalid"

echo "OK $FULL_SHA $DEST"
