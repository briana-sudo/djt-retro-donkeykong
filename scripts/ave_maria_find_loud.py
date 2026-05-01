"""AVE-MARIA-FIX — scan audio_full_backup/ave_maria.mp3 for loudest 4-second window.

Strategy:
  1. Run ffmpeg with astats per-second to measure RMS_level across the whole file.
  2. Convert dB → linear, compute a 4-second rolling-mean of linear amplitude.
  3. Convert back to dB and find the top windows (peak loudness sustained over 4s).
  4. Report the top 3 candidate start timestamps.

Output is purely informational — caller does the actual ffmpeg trim using the chosen
candidate's start timestamp.
"""
from __future__ import annotations
import math
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SRC = PROJECT_ROOT / 'audio_full_backup' / 'ave_maria.mp3'
WINDOW_SEC = 4

if not SRC.exists():
    print(f'MISSING: {SRC}')
    sys.exit(1)

# astats per-second RMS via aresample=44100 (force 44.1 kHz so each asetnsamples=44100
# block is exactly 1 real second regardless of source sample rate). The earlier version
# without aresample produced 0.92s blocks on a 48 kHz source — candidate timestamps were
# 8% off and one candidate exceeded the source duration.
cmd = [
    'ffmpeg', '-hide_banner', '-i', str(SRC),
    '-af', 'aresample=44100,asetnsamples=44100,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level',
    '-f', 'null', '-',
]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
err = proc.stderr

# Parse RMS_level lines. Each printed line looks like:
#   [Parsed_ametadata_2 @ 0x...] lavfi.astats.Overall.RMS_level=-23.456789
rms_db: list[float] = []
for line in err.splitlines():
    m = re.search(r'lavfi\.astats\.Overall\.RMS_level=([-\d.]+)', line)
    if not m:
        continue
    val = m.group(1)
    if val == '-' or val == '-inf':
        rms_db.append(-90.0)  # silence floor
    else:
        try:
            rms_db.append(float(val))
        except ValueError:
            rms_db.append(-90.0)

if not rms_db:
    print('No RMS data parsed — astats output may have failed.')
    print(err[-1000:])
    sys.exit(1)

n = len(rms_db)
print(f'Parsed {n} per-second RMS samples (file is ~{n}s, source duration 213.95s).')
print()

# Convert dB to linear amplitude for proper averaging:
#   linear = 10^(dB/20)
linear = [10.0 ** (db / 20.0) for db in rms_db]

# 4-second rolling mean (linear), then back to dB
candidates: list[tuple[float, int]] = []  # (mean_db, start_second)
for i in range(0, n - WINDOW_SEC + 1):
    window = linear[i:i + WINDOW_SEC]
    mean_lin = sum(window) / WINDOW_SEC
    mean_db = 20.0 * math.log10(mean_lin) if mean_lin > 0 else -90.0
    candidates.append((mean_db, i))

# Sort descending by loudness, then dedupe overlapping windows (keep only one
# candidate per ~6-second neighborhood so we get diverse picks, not 4 candidates
# from the same loud passage).
candidates.sort(key=lambda x: x[0], reverse=True)
picked: list[tuple[float, int]] = []
MIN_GAP = 8  # seconds — candidates must be at least this far apart
for db, start in candidates:
    if all(abs(start - p_start) >= MIN_GAP for _, p_start in picked):
        picked.append((db, start))
    if len(picked) >= 5:
        break

print('Top loudness candidates (4-second mean RMS, sorted by loudness):')
for rank, (db, start) in enumerate(picked, 1):
    mm = start // 60
    ss = start % 60
    # Also show the per-second RMS for the 4s window so caller can sanity check.
    window_db = rms_db[start:start + WINDOW_SEC]
    detail = ', '.join(f'{x:+.1f}' for x in window_db)
    print(f'  #{rank}  start={mm:02d}:{ss:02d}  4s-mean RMS = {db:+.2f} dB   per-sec: [{detail}]')
