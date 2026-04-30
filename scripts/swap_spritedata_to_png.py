"""Replace inline-base64 JPG entries in index.html's spriteData with relative .png paths.

Reads index.html, rewrites lines whose pattern matches `NAME: 'data:image/jpeg;base64,...'`
to `NAME: 'sprites/NAME.png',` while preserving indent and surrounding lines.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent.parent
SRC = HERE / 'index.html'

LINE_RE = re.compile(
    r"^(\s*)(\w+)\s*:\s*['\"]data:image/jpeg;base64,[A-Za-z0-9+/=]+['\"]\s*,?\s*$"
)

with open(SRC, encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

new_lines: list[str] = []
replacements = 0
last_match_idx: int | None = None
match_indices: list[int] = []
for i, line in enumerate(lines):
    m = LINE_RE.match(line)
    if m:
        match_indices.append(i)
        last_match_idx = i

# Re-pass to write replacements with proper trailing-comma handling.
for i, line in enumerate(lines):
    m = LINE_RE.match(line)
    if not m:
        new_lines.append(line)
        continue
    indent = m.group(1)
    name = m.group(2)
    is_last = (i == last_match_idx)
    trail = '' if is_last else ','
    new_lines.append(f"{indent}{name}: 'sprites/{name}.png'{trail}\n")
    replacements += 1

with open(SRC, 'w', encoding='utf-8', newline='\n') as f:
    f.writelines(new_lines)

print(f"Rewrote {replacements} spriteData entries to PNG paths.")
print("Sample:")
for idx in match_indices[:3] + match_indices[-2:]:
    print(f"  L{idx+1}: {new_lines[idx].rstrip()}")
