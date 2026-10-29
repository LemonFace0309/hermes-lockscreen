#!/bin/bash
# Generates background plates with GPT Image 2 on fal (model chosen 2026-10-28: #1 on current image arenas).
# Usage: FAL_KEY=… tools/gen_plate.sh <name> <prompt-file> <count>   (writes <name>-1.png … in the current folder)
set -euo pipefail
name="$1"; prompt="$(cat "$2")"; count="$3"
tmp="$(mktemp -d)"
umask 077
trap '[ -n "$tmp" ] && rm -rf "$tmp"' EXIT
printf 'Authorization: Key %s\n' "$FAL_KEY" > "$tmp/auth"   # keeps the key out of the process list
body=$(python3 -c 'import json,sys; print(json.dumps({"prompt": sys.argv[1], "image_size": {"width": 1216, "height": 2640}, "quality": "high", "num_images": int(sys.argv[2]), "output_format": "png"}))' "$prompt" "$count")
resp=$(curl -sS --max-time 600 -X POST https://fal.run/openai/gpt-image-2 -H @"$tmp/auth" -H "Content-Type: application/json" -d "$body")
python3 - "$name" "$resp" <<'PY'
import json, sys, urllib.request
name, resp = sys.argv[1], json.loads(sys.argv[2])
if 'images' not in resp:
    print(name, 'error:', str(resp)[:300]); sys.exit(1)
for i, img in enumerate(resp['images']):
    urllib.request.urlretrieve(img['url'], f'{name}-{i + 1}.png')
    print('saved', f'{name}-{i + 1}.png', img.get('width'), 'x', img.get('height'))
PY
