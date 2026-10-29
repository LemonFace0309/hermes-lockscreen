#!/bin/bash
# Renders the images, tests and builds the three shortcuts, signs them, then copies them, the images and the guide to
# iCloud Drive › Shortcuts › Hermes (where the renderer reads them on the phone). Nothing in the folder's chat
# (chat.json, rows/) is touched.
# Usage: tools/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

icloud="$HOME/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/Hermes"
mkdir -p build/release "$icloud"
swiftc -O tools/render_assets.swift -o build/render_assets
build/render_assets .
python3 tools/test_workflow_structure.py
python3 tools/test_scenarios.py > build/scenarios.txt || { cat build/scenarios.txt; exit 1; }
tail -1 build/scenarios.txt
python3 tools/build_shortcut.py build/release
for unsigned in build/release/*.unsigned.shortcut; do
    signed="${unsigned%.unsigned.shortcut}.shortcut"
    shortcuts sign --mode anyone -i "$unsigned" -o "$signed"
    cp "$signed" "$icloud/"
    echo "signed -> $icloud/$(basename "$signed")"
done
# Only changed images are copied: an unchanged copy would make every phone download it again (the walls are 5 MB).
for image in $(cat tools/images.txt); do
    cmp -s "assets/$image.png" "$icloud/$image.png" || { cp "assets/$image.png" "$icloud/"; echo "image -> $image.png"; }
done
cp SETUP.md "$icloud/SETUP.txt"
echo "setup guide -> $icloud/SETUP.txt"
