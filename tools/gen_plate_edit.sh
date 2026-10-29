#!/bin/bash
# Re-lights a plate with GPT Image 2's edit endpoint on fal: same wall, same sill, same framing, different light.
# Usage: FAL_KEY=… tools/gen_plate_edit.sh <name> <source-image> <prompt-file> <count>   (writes <name>-1.png …)
set -euo pipefail
name="$1"; source="$2"; prompt="$(cat "$3")"; count="$4"
tmp="$(mktemp -d)"
umask 077
trap '[ -n "$tmp" ] && rm -rf "$tmp"' EXIT
printf 'Authorization: Key %s\n' "$FAL_KEY" > "$tmp/auth"   # keeps the key out of the process list
sips -s format jpeg -s formatOptions 92 "$source" --out "$tmp/source.jpg" >/dev/null
python3 - "$prompt" "$count" "$tmp/source.jpg" > "$tmp/body.json" <<'PY'
import base64, json, sys
prompt, count, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
uri = 'data:image/jpeg;base64,' + base64.b64encode(open(path, 'rb').read()).decode()
print(json.dumps({'prompt': prompt, 'image_urls': [uri], 'image_size': {'width': 1216, 'height': 2640},
                  'quality': 'high', 'num_images': count, 'output_format': 'png'}))
PY
curl -sS --max-time 900 -X POST https://fal.run/openai/gpt-image-2/edit -H @"$tmp/auth" \
     -H "Content-Type: application/json" --data-binary "@$tmp/body.json" > "$tmp/resp.json"
python3 - "$name" "$tmp/resp.json" <<'PY'
import json, sys, urllib.request
name, resp = sys.argv[1], json.load(open(sys.argv[2]))
if 'images' not in resp:
    print(name, 'error:', str(resp)[:400]); sys.exit(1)
for i, img in enumerate(resp['images']):
    urllib.request.urlretrieve(img['url'], f'{name}-{i + 1}.png')
    print('saved', f'{name}-{i + 1}.png', img.get('width'), 'x', img.get('height'))
PY
