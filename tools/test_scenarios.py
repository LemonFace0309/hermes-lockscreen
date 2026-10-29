#!/usr/bin/env python3
"""Runs the edge-case scenarios (tools/test_scenarios.mjs) against freshly generated shortcuts, on the simulated
iPhone in tools/sim.mjs. Needs Node.js 18+ (set NODE to use a particular one)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import build_shortcut

ROOT = Path(__file__).resolve().parent.parent
node = os.environ.get('NODE') or shutil.which('node') or '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
if not Path(node).exists():
    raise SystemExit('Node.js 18+ is needed: install it, or set NODE to its path.')
with tempfile.TemporaryDirectory(prefix='hermes-scenarios-') as folder:
    path = Path(folder) / 'workflows.json'
    path.write_text(json.dumps(build_shortcut.build_all()))
    result = subprocess.run([node, str(ROOT / 'tools/test_scenarios.mjs'), str(path), str(ROOT / 'design/tokens.json'),
                             str(ROOT / 'assets/manifest.json')])
sys.exit(result.returncode)
