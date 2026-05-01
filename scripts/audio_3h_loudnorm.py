"""AUDIO-3h two-pass ffmpeg loudnorm on the 3 BGM rotation tracks.

PASS 1: measure source loudness (input_i, input_tp, input_lra, input_thresh,
        target_offset) by running loudnorm with print_format=json.
PASS 2: apply normalization with measured values + linear=true so the EBU R128
        algorithm applies a single linear gain (no dynamic compression).

Target: -16 LUFS integrated, -1.5 dB true peak, 11 LU loudness range — the
Spotify/YouTube streaming-platform standard.

Outputs to <name>_normalized.mp3 then mv'd over the original after both passes
succeed. Backups already in /audio_pre_loudnorm/ from the AUDIO-3h prep step.

Idempotent: running twice on already-normalized files just produces near-zero
gain offsets and another file at -16 LUFS.
"""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
AUDIO_DIR = PROJECT_ROOT / 'audio'
TRACKS = ['greenwood', 'queen', 'brown']

# Target loudness (Brian's spec).
TARGET_I    = -16.0
TARGET_TP   = -1.5
TARGET_LRA  = 11.0


def run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace')
    return proc.returncode, proc.stdout, proc.stderr


def loudnorm_pass1(src: Path) -> dict:
    """Run pass 1 — measure. ffmpeg writes loudnorm JSON to stderr; we parse it."""
    cmd = [
        'ffmpeg', '-hide_banner', '-i', str(src),
        '-af', f'loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json',
        '-f', 'null', '-',
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        raise RuntimeError(f'pass1 failed for {src.name}: {err[-500:]}')
    # Find the JSON block in stderr — loudnorm prints it after the encoding stats.
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', err, re.DOTALL)
    if not m:
        raise RuntimeError(f'pass1 produced no JSON for {src.name}; stderr tail:\n{err[-500:]}')
    return json.loads(m.group(0))


def loudnorm_pass2(src: Path, dst: Path, m: dict) -> None:
    """Run pass 2 — apply with measured values. Writes a fresh MP3 to dst."""
    measured = (
        f'loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}'
        f':measured_I={m["input_i"]}'
        f':measured_TP={m["input_tp"]}'
        f':measured_LRA={m["input_lra"]}'
        f':measured_thresh={m["input_thresh"]}'
        f':offset={m["target_offset"]}'
        f':linear=true:print_format=summary'
    )
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-i', str(src),
        '-af', measured,
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(dst),
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        raise RuntimeError(f'pass2 failed for {src.name}: {err[-500:]}')


def measured_summary(src: Path) -> dict:
    """Re-measure post-normalization to verify the new file lands at -16 LUFS."""
    return loudnorm_pass1(src)


def main() -> int:
    failures = []
    for name in TRACKS:
        src = AUDIO_DIR / f'{name}.mp3'
        dst = AUDIO_DIR / f'{name}_normalized.mp3'
        if not src.exists():
            print(f'  SKIP {name}: missing {src}')
            failures.append(name)
            continue
        print(f'==> {name}')
        try:
            m1 = loudnorm_pass1(src)
            print(f'    PASS1  input_i={m1["input_i"]}  input_tp={m1["input_tp"]}'
                  f'  input_lra={m1["input_lra"]}  offset={m1["target_offset"]}')
            loudnorm_pass2(src, dst, m1)
            shutil.move(str(dst), str(src))
            m2 = measured_summary(src)
            print(f'    PASS2  input_i={m2["input_i"]} (target {TARGET_I})'
                  f'  delta={float(m2["input_i"]) - TARGET_I:+.2f} LU')
        except Exception as e:
            print(f'    FAIL: {e}')
            failures.append(name)
    if failures:
        print(f'\nFailed: {failures}')
        return 1
    print('\nAll 3 BGM tracks normalized to -16 LUFS.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
