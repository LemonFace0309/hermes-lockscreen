#!/bin/bash
# Builds Hermes.zip at the top of the repo: the folder a new user moves into iCloud Drive › Shortcuts, holding the
# images, the three signed shortcuts and SETUP.txt. The same steps as build.sh, without publishing to iCloud.
# Needs a Mac with Shortcuts (to sign), Swift and Node.js 18+.
# Usage: tools/package.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build/release
swiftc -O tools/render_assets.swift -o build/render_assets
build/render_assets .
python3 tools/test_workflow_structure.py
python3 tools/test_scenarios.py > build/scenarios.txt || { cat build/scenarios.txt; exit 1; }
tail -1 build/scenarios.txt
python3 tools/build_shortcut.py build/release
rm -rf build/Hermes && mkdir -p build/Hermes
for unsigned in build/release/*.unsigned.shortcut; do
    name="$(basename "${unsigned%.unsigned.shortcut}")"
    shortcuts sign --mode anyone -i "$unsigned" -o "build/Hermes/$name.shortcut"
done
for image in $(cat tools/images.txt); do cp "assets/$image.png" build/Hermes/; done
cp SETUP.md build/Hermes/SETUP.txt
rm -f Hermes.zip
(cd build && zip -qrX ../Hermes.zip Hermes -x '*.DS_Store')
echo "Hermes.zip: $(du -h Hermes.zip | cut -f1), $(unzip -l Hermes.zip | tail -1 | awk '{print $2}') files"
