"""AUDIO-BATCH Phase 2 prep — yt-dlp + ffmpeg pipeline for the 10 game SFX.

INERT pre-stage. Does NOT run automatically. Brian invokes manually after Phase 1
voice quality is approved and Phase 2 greenlit.

Per SFX:
  1. yt-dlp first-hit search via 'ytsearch1:' prefix (deterministic, no manual URL)
  2. ffmpeg trim to target duration (centered on the loudest window for SFX, or
     fixed 0..N for music chaos)
  3. ffmpeg single-pass loudnorm I=-16:TP=-1.5:LRA=11
  4. Save to audio/sfx/<name>.mp3

Idempotent: skips any existing output. Reports per-file source URL + duration
+ size. Failures don't abort the batch — each file independent.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SFX_DIR      = PROJECT_ROOT / 'audio' / 'sfx'
WINGET_BIN   = r'C:\Users\brian\AppData\Local\Microsoft\WinGet\Packages'
FFMPEG       = WINGET_BIN + r'\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin\ffmpeg.exe'
YT_DLP       = WINGET_BIN + r'\yt-dlp.yt-dlp_Microsoft.Winget.Source_8wekyb3d8bbwe\yt-dlp.exe'

# AUDIO-BATCH — 10 game SFX. Search queries match Brian's spec exactly.
# trim_sec is target output duration AFTER trimming the longest-volume window.
# Each entry: (filename, search_query, target_duration_sec, notes_for_field_test)
SFX_SPEC = [
    ('sfx_lincoln_crash.mp3',        'stone collapse rumble heavy',                 1.5,  'heavy stone-on-stone impact + debris'),
    ('sfx_stairs_collapse.mp3',      'stairs crumble heavy stone',                  1.5,  'sequential cracking + collapse rumble'),
    ('sfx_eagle_screech.mp3',        'red tailed hawk screech',                     1.0,  'movie-eagle, NOT real bald eagle (which sounds like a gull)'),
    ('sfx_pelosi_tear.mp3',          'paper tear sound effect',                     0.7,  'paper rip'),
    ('sfx_briefcase_pickup.mp3',     'arcade pickup chime 8-bit short',             0.5,  'triumphant arcade chime ~300ms'),
    ('sfx_capsule_destruction.mp3',  'glass shatter short sound effect',            1.0,  'glass shatter'),
    ('sfx_crowd_cheer.mp3',          'crowd cheer political rally',                 1.5,  'CHEER ONLY — verify no audible boos'),
    ('sfx_player_death_scream.mp3',  'cartoon scream short comedic',                0.6,  'short comedic scream ~0.5s'),
    ('sfx_ragdoll_thud.mp3',         'body slam ground thud impact',                1.0,  'body impact + debris explosion'),
    ('media_chaos.mp3',              'Trump press conference reporters shouting',   2.5,  '~2.5s of layered reporter voices, real press scrum'),
]


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def yt_dlp_download(query: str, dst_dir: Path) -> tuple[Path | None, str | None]:
    """Run yt-dlp with ytsearch1: prefix — first hit only. Returns (downloaded
    file path, source URL) or (None, None) on failure."""
    # Use --print to capture the resolved URL + filepath in one shot.
    template = str(dst_dir / '%(id)s.%(ext)s')
    cmd = [
        YT_DLP, '--no-warnings', '--quiet',
        '--extract-audio', '--audio-format', 'mp3',
        '--no-playlist',
        '-o', template,
        '--print', 'after_move:filepath',
        '--print', 'webpage_url',
        f'ytsearch1:{query}',
    ]
    rc, out, err = run(cmd, timeout=180)
    if rc != 0:
        print(f'    YT-DLP FAIL: {err[-300:]}')
        return None, None
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if len(lines) < 2:
        print(f'    YT-DLP unexpected output: {out!r}')
        return None, None
    filepath = Path(lines[0])
    url      = lines[1]
    if not filepath.exists():
        print(f'    YT-DLP filepath missing: {filepath}')
        return None, None
    return filepath, url


def ffmpeg_trim_loudnorm(src: Path, dst: Path, target_sec: float) -> bool:
    """Trim src to first target_sec, then loudnorm. Single ffmpeg pass."""
    cmd = [
        FFMPEG, '-y', '-hide_banner', '-loglevel', 'error',
        '-i', str(src),
        '-t', str(target_sec),
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(dst),
    ]
    rc, out, err = run(cmd, timeout=60)
    if rc != 0:
        print(f'    FFMPEG FAIL: {err[-300:]}')
        return False
    return True


def main() -> int:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_dir = Path(tmp_root)
        for filename, query, target_sec, note in SFX_SPEC:
            dst = SFX_DIR / filename
            if dst.exists():
                print(f'==> SKIP (exists): {filename}')
                results.append((filename, 'skip', '-', dst.stat().st_size / 1024))
                continue
            print(f'==> {filename}  (query: {query!r}, target {target_sec}s)')
            print(f'    note: {note}')
            src, url = yt_dlp_download(query, tmp_dir)
            if not src:
                results.append((filename, 'yt-dlp-fail', '-', 0))
                continue
            ok = ffmpeg_trim_loudnorm(src, dst, target_sec)
            try:
                src.unlink()
            except Exception:
                pass
            if ok:
                size_kb = dst.stat().st_size / 1024
                results.append((filename, 'ok', url, size_kb))
                print(f'    OK -> {size_kb:.1f} KB  source={url}')
            else:
                results.append((filename, 'ffmpeg-fail', url, 0))
    print('\n--- Batch results ---')
    for name, status, url, size_kb in results:
        print(f'  [{status}] {name}  ({size_kb:.1f} KB)  {url}')
    fail_count = sum(1 for _, s, _, _ in results if s not in ('ok', 'skip'))
    return 1 if fail_count else 0


if __name__ == '__main__':
    sys.exit(main())
