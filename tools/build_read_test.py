#!/usr/bin/env python3
"""Builds "Hermes Read Test": the renderer as it reads Messages, runnable on its own from the Shortcuts editor (no
input needed), so a failing action is highlighted with its reason instead of hiding inside Run Shortcut. It works on
the real Hermes folder and does what a normal read does; nothing runs it but you.

    python3 build_read_test.py <out-dir> <agent name>"""
import plistlib
import subprocess
import sys
from pathlib import Path

import build_shortcut as b

out, agent = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
b.RENDERER_NAME, b.QA, b.DEFAULT_AGENT = 'Hermes Read Test', 'debug', agent
built = b.build_renderer()
built['WFWorkflowImportQuestions'] = []
unsigned = out / 'Hermes Read Test.unsigned.shortcut'
with unsigned.open('wb') as f:
    plistlib.dump(built, f, fmt=plistlib.FMT_BINARY)
subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', unsigned, '-o', out / 'Hermes Read Test.shortcut'], check=True)
print(f'{len(built["WFWorkflowActions"])} actions -> {out / "Hermes Read Test.shortcut"}')
