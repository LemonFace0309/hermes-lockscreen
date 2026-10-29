#!/usr/bin/env python3
"""Reads a signed .shortcut file (as Shortcuts exports or `shortcuts sign` writes) back into its plist.

    python3 decode_shortcut.py <file.shortcut> <out.plist>

A signed shortcut is an Apple Encrypted Archive in its signed-only profile: the payload isn't encrypted, so its LZFSE
stream (bvx2 … bvx$) sits in the file as is. Decompressed, it is an Apple Archive holding Shortcut.wflow."""
import subprocess
import sys
import tempfile
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
data = src.read_bytes()
assert data[:4] == b'AEA1', 'not a signed shortcut'
start, end = data.find(b'bvx'), data.rfind(b'bvx$')
assert 0 < start < end, 'no compressed payload found'
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / 'payload.lzfse').write_bytes(data[start:end + 4])
    subprocess.run(['compression_tool', '-decode', '-a', 'lzfse', '-i', tmp / 'payload.lzfse', '-o', tmp / 'out.aar'],
                   check=True)
    (tmp / 'x').mkdir()
    subprocess.run(['aa', 'extract', '-i', tmp / 'out.aar', '-d', tmp / 'x'], check=True)
    out.write_bytes(next((tmp / 'x').rglob('*.wflow')).read_bytes())
print(f'decoded -> {out}')
