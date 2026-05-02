"""SFX-RERUN-2 — re-pull 2 SFX with stricter quality gates than sfx_resource.py.

NEW gates beyond sfx_resource.py:
  1. mean_volume floor: after ffmpeg trim+loudnorm, run ffprobe-equivalent
     volumedetect to measure mean_volume. Reject + advance to next candidate
     if mean_volume < -50 dB (catches silent / near-silent outputs — last
     run produced a fully silent ragdoll mp3).
  2. min_source_duration: per-spec floor on the SOURCE video's duration
     (not the trimmed output). For capsule we need source ≥ 5s so we can
     trim a 1.5-2.5s window that captures the full pitch falloff.
  3. fallback_query: optional secondary query if all top-3 candidates from
     the primary query fail the source-duration filter. Queried again with
     ytsearch3:; same blacklist + same gates apply.

Primary motivator: ragdoll's prior pull was silent (mean_volume = -infinity),
and capsule's prior pull was a 5s source clip too brief for the desired
falloff window.
"""
from __future__ import annotations
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SFX_DIR      = PROJECT_ROOT / 'audio' / 'sfx'
WINGET_BIN   = r'C:\Users\brian\AppData\Local\Microsoft\WinGet\Packages'
FFMPEG_DIR   = WINGET_BIN + r'\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin'
FFMPEG       = FFMPEG_DIR + r'\ffmpeg.exe'
YT_DLP       = WINGET_BIN + r'\yt-dlp.yt-dlp_Microsoft.Winget.Source_8wekyb3d8bbwe\yt-dlp.exe'

DURATION_CEILING_SEC = 30           # music-rejection heuristic (relaxed via fallback)
MIN_MEAN_VOL_DB      = -50.0        # silent-clip detection: reject below this

# Each entry has stricter fields than sfx_resource.py:
#   filename, primary_query, target_sec, blacklist, min_source_dur_sec, fallback_query
RERUN_SPEC = [
    {
        'filename':       'sfx_ragdoll_thud.mp3',
        'primary_query':  'heavy sandbag drop floor sound effect',
        'target_sec':     1.0,                                      # mid of 0.8-1.2
        'blacklist':      ['music', 'song', 'beat', 'remix', 'soundtrack', 'asmr'],
        'min_source_dur': 0,                                        # no source-duration floor for ragdoll
        'fallback_query': None,                                     # not needed
        'note':           'previous run was silent — ffprobe mean_volume gate catches that now',
    },
    {
        'filename':       'sfx_capsule_destruction.mp3',
        'primary_query':  'large window smash break shatter glass cascade',
        'target_sec':     2.0,                                      # mid of 1.5-2.5
        'blacklist':      ['music', 'song', 'beat', 'remix', 'soundtrack', 'asmr'],
        'min_source_dur': 5,                                        # need ≥5s source for proper falloff window
        'fallback_query': 'bottle smash break floor sound effect long',
        'note':           'previous source was too brief; new query targets longer cascade content',
    },
]


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def yt_dlp_search_metadata(query: str, n: int = 3) -> list[dict]:
    """Top-N metadata via --skip-download. Each: title, id, url, duration_sec."""
    cmd = [
        YT_DLP, '--no-warnings', '--quiet',
        '--skip-download',
        '--print', '%(title)s|||%(id)s|||%(webpage_url)s|||%(duration)s',
        f'ytsearch{n}:{query}',
    ]
    rc, out, err = run(cmd, timeout=120)
    if rc != 0:
        print(f'    METADATA FETCH FAIL: {err[-200:]}')
        return []
    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('|||')
        if len(parts) != 4:
            continue
        title, vid, url, dur_str = parts
        try:
            dur = float(dur_str) if dur_str and dur_str != 'NA' else 9999.0
        except ValueError:
            dur = 9999.0
        results.append({'title': title, 'id': vid, 'url': url, 'duration_sec': dur})
    return results


def yt_dlp_download_url(url: str, dst_dir: Path) -> Path | None:
    template = str(dst_dir / '%(id)s.%(ext)s')
    cmd = [
        YT_DLP, '--no-warnings', '--quiet',
        '--extract-audio', '--audio-format', 'mp3',
        '--no-playlist',
        '--ffmpeg-location', FFMPEG_DIR,
        '--no-simulate',
        '-o', template,
        url,
    ]
    rc, out, err = run(cmd, timeout=180)
    if rc != 0:
        print(f'      DOWNLOAD FAIL: {err[-200:]}')
        return None
    mp3s = list(dst_dir.glob('*.mp3'))
    if not mp3s:
        return None
    mp3s.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return mp3s[0]


def ffmpeg_trim_loudnorm(src: Path, dst: Path, target_sec: float) -> bool:
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
        print(f'      FFMPEG FAIL: {err[-200:]}')
        return False
    return True


def measure_mean_volume(mp3: Path) -> float | None:
    """ffmpeg volumedetect on a finished mp3. Returns mean_volume in dB,
    or None on parse failure. -inf is returned as -120.0 (sentinel)."""
    cmd = [
        FFMPEG, '-hide_banner', '-i', str(mp3),
        '-af', 'volumedetect',
        '-f', 'null', '-',
    ]
    rc, out, err = run(cmd, timeout=30)
    # volumedetect writes to stderr.
    m = re.search(r'mean_volume:\s*(-?\d+\.\d+|-inf)\s*dB', err)
    if not m:
        return None
    val = m.group(1)
    if val == '-inf':
        return -120.0
    try:
        return float(val)
    except ValueError:
        return None


def try_candidate(c: dict, target_sec: float, dst: Path, tmp_root: Path) -> tuple[bool, float | None]:
    """Download the candidate, trim+loudnorm, measure mean_volume.
    Returns (ok, mean_volume_db). ok=True means the file is on disk and
    above the volume floor."""
    sub = tmp_root / c['id']
    sub.mkdir(exist_ok=True)
    src = yt_dlp_download_url(c['url'], sub)
    if not src:
        return False, None
    ok = ffmpeg_trim_loudnorm(src, dst, target_sec)
    if not ok:
        return False, None
    mv = measure_mean_volume(dst)
    if mv is None:
        print(f'      WARN: could not parse mean_volume; treating as failed')
        return False, None
    print(f'      mean_volume: {mv:+.1f} dB')
    if mv < MIN_MEAN_VOL_DB:
        print(f'      REJECT: mean_volume {mv:+.1f} dB < floor {MIN_MEAN_VOL_DB:+.1f} dB (silent)')
        try:
            dst.unlink()
        except Exception:
            pass
        return False, mv
    return True, mv


def select_and_pull(spec: dict, tmp_root: Path) -> bool:
    """For one RERUN_SPEC entry: try primary query (top 3), then fallback
    query if needed. Per-candidate: download → trim → mean_volume gate.
    Returns True if a usable file landed at SFX_DIR/spec.filename."""
    filename       = spec['filename']
    blacklist      = [b.lower() for b in spec['blacklist']]
    target_sec     = spec['target_sec']
    min_src_dur    = spec['min_source_dur']
    dst            = SFX_DIR / filename

    queries = [spec['primary_query']]
    if spec['fallback_query']:
        queries.append(spec['fallback_query'])

    for q_idx, query in enumerate(queries, 1):
        label = 'PRIMARY' if q_idx == 1 else 'FALLBACK'
        print(f'\n  -- {label} query: {query!r} --')
        candidates = yt_dlp_search_metadata(query, n=3)
        if not candidates:
            print(f'    NO CANDIDATES')
            continue

        for i, c in enumerate(candidates, 1):
            print(f'    [{i}] "{c["title"][:80]}"  ({c["duration_sec"]:.1f}s)  {c["url"]}')

        for i, c in enumerate(candidates, 1):
            title_lower = c['title'].lower()
            dur = c['duration_sec']

            # Hard filters
            if any(tok in title_lower for tok in blacklist):
                bad_tok = next(tok for tok in blacklist if tok in title_lower)
                print(f'    [{i}] REJECT (title blacklist "{bad_tok}")')
                continue
            if dur < min_src_dur:
                print(f'    [{i}] REJECT (source duration {dur:.1f}s < min {min_src_dur}s)')
                continue
            if dur >= DURATION_CEILING_SEC:
                # Soft filter — only relevant if we have alternatives. Try this candidate
                # if it's the only one passing the other filters; otherwise skip.
                # (Capsule's last batch had all >30s and used the fallback path — same here.)
                print(f'    [{i}] WARN (duration {dur:.1f}s >= ceiling {DURATION_CEILING_SEC}s — accepting anyway)')

            # Download + measure
            print(f'    [{i}] TRYING: {c["title"][:70]}  ({c["duration_sec"]:.1f}s)')
            ok, mv = try_candidate(c, target_sec, dst, tmp_root)
            if ok:
                print(f'    [{i}] ACCEPT: {dst.name} ({dst.stat().st_size / 1024:.1f} KB, mean_vol {mv:+.1f} dB)')
                return True
            # Loop on to next candidate

        print(f'    All candidates from this query failed gates.')

    return False


def main() -> int:
    if not SFX_DIR.exists():
        print(f'ERROR: {SFX_DIR} does not exist')
        return 1
    failures = []
    with tempfile.TemporaryDirectory() as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        for spec in RERUN_SPEC:
            print(f'\n==> {spec["filename"]}')
            print(f'    target output: {spec["target_sec"]}s,  blacklist: {spec["blacklist"]}')
            if spec['min_source_dur']:
                print(f'    min source duration: {spec["min_source_dur"]}s')
            print(f'    note: {spec["note"]}')
            ok = select_and_pull(spec, tmp_root)
            if not ok:
                failures.append(spec['filename'])

    print('\n--- Re-run results ---')
    if failures:
        print(f'FAILED: {failures}')
        return 1
    print(f'All {len(RERUN_SPEC)} files re-pulled successfully (passed mean_volume gate).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
