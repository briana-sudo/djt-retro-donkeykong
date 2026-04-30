"""Inventory JPG sprite names from index.html's inline-base64 spriteData."""
import re
from pathlib import Path

HERE = Path(__file__).parent.parent
SRC = HERE / 'index.html'

with open(SRC, encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# spriteData starts at ~line 23. Each entry: NAME: 'data:image/jpeg;base64,...'
pattern = re.compile(r'^\s*(\w+)\s*:\s*[\'"]data:image/jpeg')
names = []
for i, line in enumerate(lines, start=1):
    m = pattern.match(line)
    if m:
        names.append((i, m.group(1)))

print(f'Found {len(names)} JPG sprites in spriteData:')
for ln, n in names:
    print(f'  line {ln}: {n}')
