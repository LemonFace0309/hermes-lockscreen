#!/usr/bin/env python3
"""Builds the phone's Hermes Lock Screen for Hermes Wall: it asks the Mac for the Lock Screen picture and sets it. It
keeps the name of the Shortcuts-drawn one, so replacing that on the phone keeps the Message automation and Talk to
Hermes pointing at it.

    python3 mac/build_phone_shortcut.py <out-dir> --tailscale    the Mac's Tailscale name (phone on any network)
    python3 mac/build_phone_shortcut.py <out-dir>                the Mac's local name (phone on the same Wi-Fi)
    python3 mac/build_phone_shortcut.py <out-dir> --url http://<host>:7337/wall

What started it goes to the Mac as {"input": …} (a message's words, Talk to Hermes's "me-audio[<name>]: <words>", a
Sun automation's light, or nothing), with the token from ~/Library/Application Support/Hermes Wall/config.json. Only an
image is set; an error or an unreachable Mac leaves the wall as it was. The Lock Screen to draw on (WFSelectedPoster)
is the one picked in the installed Hermes Lock Screen (mac/phone/lock-screen-poster.plist). Without that file, it's
picked on the phone, in the Set Wallpaper Photo action."""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_shortcut as b  # noqa: E402
from build_shortcut import HAS_VALUE, IS, Shortcut, attachment, shortcut_input, token_string, variable, workflow  # noqa: E402

args = sys.argv[1:]
out = Path(args[0])
config = json.loads((Path.home() / 'Library/Application Support/Hermes Wall/config.json').read_text())
port = config.get('port', 7337)


def tailscale_name():
    """This Mac's MagicDNS name, from whichever Tailscale is installed (Homebrew's CLI or the app's)."""
    for cli in ('tailscale', '/Applications/Tailscale.app/Contents/MacOS/Tailscale'):
        try:
            status = json.loads(subprocess.run([cli, 'status', '--json'], capture_output=True, text=True, check=True).stdout)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        name = (status.get('Self') or {}).get('DNSName', '').rstrip('.')
        if name:
            return name
    raise SystemExit('Tailscale isn’t running on this Mac (or has no MagicDNS name): start it and sign in, or pass --url.')


if '--url' in args:
    url = args[args.index('--url') + 1]
elif '--tailscale' in args:
    url = f'http://{tailscale_name()}:{port}/wall'
else:
    host = subprocess.run(['scutil', '--get', 'LocalHostName'], capture_output=True, text=True, check=True).stdout.strip()
    url = f'http://{host}.local:{port}/wall'
poster_file = Path(__file__).parent / 'phone/lock-screen-poster.plist'
poster = plistlib.load(poster_file.open('rb')) if poster_file.exists() else None


def fields(items):
    return {'Value': {'WFDictionaryFieldValueItems': [{'WFItemType': 0, 'WFKey': token_string(k), 'WFValue': token_string(v)}
                                                      for k, v in items]},
            'WFSerializationType': 'WFDictionaryFieldValue'}


s = Shortcut()
s.comment(f'{b.WALLPAPER_NAME} puts your chat with your agent on the Lock Screen. The Mac that has your Messages draws '
          'it (Hermes Wall); this asks the Mac for the picture and sets it. Your Message automation, your Sun '
          'automations and Talk to Hermes run it.')
s.set_text('Input', '')
g = s.if_(shortcut_input(), HAS_VALUE)
s.set('InputType', s.act('getitemtype', {'WFInput': attachment(shortcut_input())}, 'Type'))
g2 = s.if_(variable('InputType'), IS, string='Text')
s.set_text('Input', shortcut_input())
s.otherwise(g2)
g3 = s.if_(variable('InputType'), IS, string='Date')
s.otherwise(g3)
s.comment('From the Message automation: the message’s words, so the Mac can wait until it has the message too.')
s.set_text('Input', shortcut_input('Content'))
g4 = s.if_nonempty(variable('Input'))
s.otherwise(g4)
s.set_text('Input', shortcut_input())
s.end(g4)
s.end(g3)
s.end(g2)
s.end(g)
wall = s.act('downloadurl', {'WFURL': token_string(url), 'WFHTTPMethod': 'POST', 'WFHTTPBodyType': 'JSON',
                             'WFHTTPHeaders': fields([('X-Hermes-Token', config['token'])]),
                             'WFJSONValues': fields([('input', variable('Input'))])}, 'Contents of URL')
s.set('Wall', wall)
g = s.if_(s.act('getitemtype', {'WFInput': attachment(variable('Wall'))}, 'Type'), IS, string='Image')
s.comment('Keep it set to Lock Screen only, with Show Preview, Crop to Subject, Legibility Blur and Perspective Zoom '
          'off. To change which Lock Screen it draws on, tap the Wallpaper parameter and pick one with a photo.')
s.act('wallpaper.set', {'WFInput': attachment(variable('Wall')), 'WFWallpaperLocation': ['Lock Screen'],
                        'WFWallpaperShowPreview': False, 'WFWallpaperSmartCrop': False, 'WFWallpaperLegibilityBlur': False,
                        'WFWallpaperPerspectiveZoom': False, **({'WFSelectedPoster': poster} if poster else {})})
s.end(g)
shortcut = workflow(s, glyph=59403, color=4274264319, accepts_input=True)

saves = [a for a in shortcut['WFWorkflowActions'] if a['WFWorkflowActionIdentifier'].endswith('documentpicker.save')]
sets = [a for a in shortcut['WFWorkflowActions'] if a['WFWorkflowActionIdentifier'].endswith('wallpaper.set')]
assert not saves and len(sets) == 1, 'saves nothing; sets one wallpaper'

out.mkdir(parents=True, exist_ok=True)
unsigned = out / f'{b.WALLPAPER_NAME}.unsigned.shortcut'
with unsigned.open('wb') as f:
    plistlib.dump(shortcut, f, fmt=plistlib.FMT_BINARY)
subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', unsigned, '-o', out / f'{b.WALLPAPER_NAME}.shortcut'], check=True)
print(f'{b.WALLPAPER_NAME}: {len(shortcut["WFWorkflowActions"])} actions, asks {url} -> {out / (b.WALLPAPER_NAME + ".shortcut")}')
print(f'Lock Screen kept: {poster.get("name")}' if poster else
      'Lock Screen: none yet. On the phone, pick one in Hermes Lock Screen’s Set Wallpaper Photo action.')
