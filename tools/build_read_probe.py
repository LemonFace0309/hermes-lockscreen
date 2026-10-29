#!/usr/bin/env python3
"""Builds "Hermes Read Probe": the renderer's read of Messages, one property at a time, noting each one (how long it
took and what kind of value came back, never message text) in Hermes/probe.txt before going on. If iOS ends the run,
the last line says which property of which message it was reading.

    python3 build_read_probe.py <out-dir> <agent name>"""
import plistlib
import subprocess
import sys
from pathlib import Path

import build_shortcut as b
from build_shortcut import attachment, prop, token_string, variable

out, agent = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
NAME, PATH = 'Hermes Read Probe', f'{b.DIR}/probe.txt'
s = b.Shortcut()
s.comment('Reads Messages the way Hermes Chat Renderer does, one property at a time, and notes each step in '
          'Hermes/probe.txt (timings and kinds of values, never message text). It changes nothing else.')
it = {'Type': 'Variable', 'VariableName': 'Repeat Item'}


def note(*parts):
    s.set_text('Probe', variable('Probe'), *parts, '\n')
    s.save(variable('Probe'), PATH)


def timed(label, value_fn, show):
    """Reads one property, then notes how long it took and `show(value)`."""
    s.set('T', b.ms_now(s))
    s.set('V', value_fn())
    note(variable('Repeat Index'), f' {label} ', s.math(b.ms_now(s), '-', variable('T')), ' ms ', *show(variable('V')))


s.set('PeerKey', b.name_key(s, s.text(agent)))
s.set_text('Probe', 'Hermes Read Probe ', b.RELEASE, '\n')
s.set('T', b.ms_now(s))
s.set('Found', b.find_messages(s, b.SYNC['hours'], b.SYNC['limit']))
note('find ', s.math(b.ms_now(s), '-', variable('T')), ' ms, ', s.count(variable('Found'), 'Items'), ' messages')
loop = s.repeat_each(variable('Found'))
kind = lambda v: (s.act('getitemtype', {'WFInput': attachment(v)}, 'Type'), ', ', s.count(s.text(v)), ' chars')
timed('date', lambda: prop(it, 'Date', 'date'), lambda v: (s.fmt(v, b.WHEN),))
timed('conversation', lambda: s.text(prop(it, 'Conversation', 'conversation')),
      lambda v: ('agent ', s.act('text.match', {'text': token_string(b.name_key(s, v)), 'WFMatchTextPattern':
                                                 token_string('^', variable('PeerKey'), '$')}, 'Matches'), ' ', *kind(v)))
g = s.if_same(b.name_key(s, variable('V')), variable('PeerKey'))
timed('sender', lambda: s.text(prop(it, 'Sender', 'author')), kind)
timed('body', lambda: s.text(prop(it, 'Body', 'body')), kind)
timed('attachments', lambda: prop(it, 'Attachments', 'attachments'), kind)
timed('attachments as text', lambda: s.text(prop(it, 'Attachments', 'attachments')), lambda v: (v,))
timed('type', lambda: s.text(prop(it, 'Type', 'messageType'), '/', prop(it, 'Reaction', 'reaction')), lambda v: (v,))
g2 = s.if_matches(variable('V'), r'Reaction|^[^/]*/.+$')
timed('reference', lambda: prop(it, 'Reference', 'referencedMessage'),
      lambda v: (s.act('getitemtype', {'WFInput': attachment(v)}, 'Type'),))
s.set('RefMsg', variable('V'))
timed('reference date', lambda: prop({'Type': 'Variable', 'VariableName': 'RefMsg'}, 'Date', 'date'),
      lambda v: (s.fmt(v, b.WHEN),))
s.end(g2)
s.end(g)
s.end_repeat_each(loop)
note('done')

built = b.workflow(s, glyph=59448, color=4271458815, accepts_input=False)
unsigned = out / f'{NAME}.unsigned.shortcut'
with unsigned.open('wb') as f:
    plistlib.dump(built, f, fmt=plistlib.FMT_BINARY)
subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', unsigned, '-o', out / f'{NAME}.shortcut'], check=True)
print(f'{len(built["WFWorkflowActions"])} actions -> {out / (NAME + ".shortcut")}')
