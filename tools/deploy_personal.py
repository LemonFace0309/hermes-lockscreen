#!/usr/bin/env python3
"""Builds signed copies of Hermes Chat Renderer and Hermes Lock Screen with your answers built in, for importing over
the installed ones on a Mac whose Shortcuts library syncs with your iPhone (no questions on import).

    python3 deploy_personal.py <out-dir> <agent name> <current Hermes Lock Screen plist>

The Lock Screen you picked in Set Wallpaper Photo (WFSelectedPoster) is copied from the installed shortcut, exported
from Shortcuts and read with decode_shortcut.py, so it survives the replacement."""
import plistlib
import subprocess
import sys
from pathlib import Path

import build_shortcut as b

out, agent, current = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
installed = plistlib.load(current.open('rb'))
poster = next(a['WFWorkflowActionParameters']['WFSelectedPoster'] for a in installed['WFWorkflowActions']
              if a['WFWorkflowActionIdentifier'].endswith('wallpaper.set'))
built = b.build_all()
renderer = built[b.RENDERER_NAME]
question = renderer['WFWorkflowImportQuestions'][0]
renderer['WFWorkflowActions'][question['ActionIndex']]['WFWorkflowActionParameters']['WFTextActionText'] = \
    b.token_string(agent)
renderer['WFWorkflowImportQuestions'] = []
lock = built[b.WALLPAPER_NAME]
for action in lock['WFWorkflowActions']:
    if action['WFWorkflowActionIdentifier'].endswith('wallpaper.set'):
        action['WFWorkflowActionParameters']['WFSelectedPoster'] = poster
for name in (b.RENDERER_NAME, b.WALLPAPER_NAME):
    unsigned = out / f'{name}.unsigned.shortcut'
    with unsigned.open('wb') as f:
        plistlib.dump(built[name], f, fmt=plistlib.FMT_BINARY)
    subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', unsigned, '-o', out / f'{name}.shortcut'], check=True)
    print(f'{name}: {len(built[name]["WFWorkflowActions"])} actions -> {out / (name + ".shortcut")}')
print(f'Lock Screen kept: {poster.get("name")} ({poster.get("UUID")})')
