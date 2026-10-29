#!/usr/bin/env python3
"""Builds "Hermes Speed Test": times the steps an update is made of (actions, file reads and saves, image work) on the
phone, so tuning follows measurements. It reads the Hermes folder and writes only Hermes/bench/ and Hermes/bench.txt,
then shows the results.

    python3 build_speed_test.py <out-dir>"""
import base64
import plistlib
import subprocess
import sys
from pathlib import Path

import build_shortcut as b
from build_shortcut import attachment, token_string, variable

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
D, NAME = b.DIR, 'Hermes Speed Test'
s = b.Shortcut()
s.comment('Times the steps an update is made of and saves them to Hermes/bench.txt. It changes nothing else.')
s.set_text('Out', NAME, ' ', b.RELEASE, '\n')


def start():
    s.set('T', b.ms_now(s))


def lap(label, n=1):
    took = s.math(b.ms_now(s), '-', variable('T'))
    if n > 1:
        s.set_text('Out', variable('Out'), label, ': ', took, ' ms, ', s.math(took, '÷', n), ' each\n')
    else:
        s.set_text('Out', variable('Out'), label, ': ', took, ' ms\n')


def timed(label, n, body):
    start()
    g = s.repeat(n)
    body()
    s.end_repeat(g)
    lap(label, n)


start()
lap('nothing (the timer itself)')

s.comment('Actions')
timed('Set Variable', 50, lambda: s.set('X', variable('Out')))
timed('Number', 50, lambda: s.number(1))
timed('If + End If', 50, lambda: s.end(s.if_positive(variable('Repeat Index'))))
timed('Calculate', 50, lambda: s.math(variable('Repeat Index'), '+', 1))
s.set('Chat', s.act('detect.dictionary', {'WFInput': attachment(s.file(f'{D}/chat.json', True))}, 'Dictionary'))
s.set_text('Log', variable('Chat', 'log'))
timed('Text with a variable', 20, lambda: s.text('x', variable('Log')))
timed('Replace Text (regex, 2 KB)', 20, lambda: s.replace(variable('Log'), f'{b.RS}[^{b.RS}]*$'))
timed('Match Text (2 KB)', 20, lambda: s.match(variable('Log'), f'[^{b.RS}]+'))
timed('Format Date', 20, lambda: s.fmt(s.now(), 'A'))

s.comment('Reading files')
timed('Get File, small image', 5, lambda: s.file(f'{D}/tail-left.png', True))
timed('Get File, missing', 3, lambda: s.file(f'{D}/rows/no-such-row.png', False))
timed('Get File + parse chat.json', 3, lambda: s.act(
    'detect.dictionary', {'WFInput': attachment(s.file(f'{D}/chat.json', True))}, 'Dictionary'))
start()
s.set('Wall', s.file(f'{D}/wall-day.png', True))
lap('Get File, wall (5 MB)')
start()
s.set('WallH', b.height(s, variable('Wall')))
lap('Height of the wall (first decode)')
start()
s.set('Col', s.file(f'{D}/rows/col.png', True))
s.set('Row', s.file(f'{D}/rows/6.png', True))
lap('Get File, stack + a tall row')
s.set('ColH', b.height(s, variable('Col')))
s.set('RowH', b.height(s, variable('Row')))
s.set('Blank', s.file(f'{D}/fade-mask.png', True))

s.comment('Image work')
timed('Height of an image', 5, lambda: b.height(s, variable('Col')))
timed('Crop', 5, lambda: s.crop(variable('Wall'), 0, 700, b.W, 1538))
s.set('Pair', variable('Col'))
s.append('Pair', variable('Row'))
timed('Combine Images (stack + row)', 3, lambda: s.combine(variable('Pair')))
timed('Overlay Image (row on wall)', 3, lambda: s.overlay(variable('Wall'), variable('Row'), 0, 1200, b.W,
                                                           variable('RowH')))
s.set('Area', s.crop(variable('Wall'), 0, 700, b.W, 1538))
s.set('Fade', s.crop(variable('Blank'), 0, 0, b.W, 1538))
timed('Mask Image (fade)', 3, lambda: s.mask_with(variable('Area'), variable('Fade')))
s.set('Clear', s.crop(variable('Blank'), 0, 0, b.W, 300))
timed('Overlay Text (3 lines)', 3, lambda: s.overlay_text(
    variable('Clear'), 'Your train leaves Friday, December 12 at 9:10 a.m. from Penn Station, changing in '
    'Boston, then on to Portland.', 39, 22, 'body', b.INK, width=b.B['maxText']))
s.set('Fresh', s.crop(variable('Row'), 0, 0, b.W, variable('RowH')))

s.comment('Saving files')
timed('Save File, same small file', 5, lambda: s.save(s.dictionary([('i', variable('Repeat Index'))]),
                                                      f'{D}/bench/status.json'))
timed('Save File, new small file', 3, lambda: s.save(s.dictionary([('i', variable('Repeat Index'))]),
                                                     token_string(f'{D}/bench/new-', variable('Repeat Index'), '.json')))
timed('Save File, a drawn row', 3, lambda: s.save(variable('Fresh'), f'{D}/bench/row.png'))
timed('Save File, the stack', 2, lambda: s.save(variable('Col'), f'{D}/bench/col.png'))
s.save(variable('Out'), f'{D}/bench.txt')

s.comment('An image kept inside the shortcut instead of in a file')
tail = base64.b64encode((b.ROOT / 'assets/tail-left.png').read_bytes()).decode()


def decode():
    data = s.act('base64encode', {'WFInput': token_string(tail), 'WFEncodeMode': 'Decode'}, 'Base64 Encoded')
    s.set('Kept', s.act('setitemname', {'WFInput': attachment(data), 'WFName': 'tail.png'}, 'Renamed Item'))


timed('Decode a small image', 5, decode)
start()
s.set('KeptOn', s.overlay(variable('Clear'), variable('Kept'), 100, 100, 82, 66))
lap('Overlay the decoded image')
s.set_text('Out', variable('Out'), 'decoded image height: ', b.height(s, variable('Kept')), '\n')
s.save(variable('Out'), f'{D}/bench.txt')
s.act('showresult', {'Text': token_string(variable('Out'))})

built = b.workflow(s, glyph=59448, color=4271458815, accepts_input=False)
unsigned = out / f'{NAME}.unsigned.shortcut'
with unsigned.open('wb') as f:
    plistlib.dump(built, f, fmt=plistlib.FMT_BINARY)
subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', unsigned, '-o', out / f'{NAME}.shortcut'], check=True)
print(f'{len(built["WFWorkflowActions"])} actions -> {out / (NAME + ".shortcut")}')
