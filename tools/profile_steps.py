#!/usr/bin/env python3
"""Counts the actions each kind of update runs, by the generator function that wrote them, on the simulated iPhone
(tools/sim.mjs). The phone runs roughly one action per 5–10 ms, so this is where an update's time goes, apart from
file reads and saves (counted too).

    python3 tools/profile_steps.py [how many lines per update to show]"""
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import build_shortcut as b

ROOT = Path(__file__).resolve().parent.parent
HERE = str(Path(b.__file__).resolve())
SKIP = set(vars(b.Shortcut)) | {'<lambda>', '<listcomp>', '<genexpr>'}
act = b.Shortcut.act
made = []
LINES = os.environ.get('LINES_TOO') == '1'   # also split by the line each function was called from


def traced(self, ident, params=None, output=None):
    """Notes which generator functions (outermost first) wrote each action."""
    ref = act(self, ident, params, output)
    frames = [f for f in reversed(inspect.stack()[1:]) if f.filename == HERE and f.function not in SKIP]
    path = [f.function for f in frames[1:]]   # frames[0] is the build_* function
    self.origin.append(f'{">".join(path)} (line {frames[1].lineno if LINES else ""})' if path and LINES else
                       '>'.join(path) or f'{frames[0].function}:{frames[0].lineno}')
    return ref


def init(self):
    self.actions, self.quiet, self.origin = [], False, []
    made.append(self)


b.Shortcut.act, b.Shortcut.__init__ = traced, init
built = b.build_all()
origins = {name: next(s.origin for s in made if s.actions is wf['WFWorkflowActions']) for name, wf in built.items()}
node = os.environ.get('NODE') or shutil.which('node') or '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
with tempfile.TemporaryDirectory(prefix='hermes-profile-') as folder:
    wf_path, origin_path = Path(folder) / 'workflows.json', Path(folder) / 'origins.json'
    wf_path.write_text(json.dumps(built))
    origin_path.write_text(json.dumps(origins))
    sys.exit(subprocess.run([node, str(ROOT / 'tools/profile_steps.mjs'), str(wf_path), str(origin_path),
                             str(ROOT / 'design/tokens.json'), str(ROOT / 'assets/manifest.json'),
                             *sys.argv[1:]]).returncode)
