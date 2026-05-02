"""SFX-RESOURCE — re-pull 3 SFX with metadata-first ytsearch3: selection.

Different from sfx_yt_dlp_batch.py:
  - Uses ytsearch3: instead of ytsearch1: (top 3 candidates)
  - Fetches metadata FIRST (--skip-download), prints all 3 candidates
  - Filters by duration ceiling (< 30s) + title-blacklist (music/song/etc.)
  - Picks first surviving candidate, then downloads JUST that one
  - Same loudnorm pass + same target dirs as the main batch

Per-target spec lives in RESOURCE_SPEC at module top — edit there, not in main().
"""
from __future__ import annotations
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

# Each entry: (output_filename, search_query, target_duration_sec, title_blacklist).
# Title blacklist is case-insensitive; if ANY blacklisted token appears in the
# candidate's title, that candidate is rejected.
RESOURCE_SPEC = [
    # SFX-RESOURCE round 2 — revised queries after vibe-failure on first re-source.
    # Each query is more specific to the desired in-game sound, asmr added to all
    # blacklists (ASMR clips are too soft/breathy for arcade-game SFX).
    # Note: sfx_pelosi_tear.mp3 from the prior round PASSED field test, so it's
    # NOT in this spec — it stays as committed.
    (
        'sfx_ragdoll_thud.mp3',
        'heavy sandbag drop floor sound effect',
        1.0,                                       # mid of 0.8-1.2s target
        ['music', 'song', 'beat', 'remix', 'soundtrack', 'asmr'],
    ),
    (
        'sfx_stairs_collapse.mp3',
        'object tumbling down wooden stairs sound effect',
        1.5,                                       # mid of 1.2-1.8s target
        ['music', 'song', 'beat', 'remix', 'soundtrack', 'asmr'],
    ),
    (
        'sfx_capsule_destruction.mp3',
        'glass window shatter break sound effect',
        1.0,                                       # mid of 0.8-1.2s target
        ['music', 'song', 'beat', 'remix', 'soundtrack', 'asmr'],
    ),
]
DURATION_CEILING_SEC = 30


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def yt_dlp_search_metadata(query: str, n: int = 3) -> list[dict]:
    """ytsearchN: + --skip-download + --print template — returns top N candidates'
    metadata WITHOUT downloading. Each dict has title, id, url, duration_sec."""
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
    """Download a single URL → mp3 in dst_dir. Returns the mp3 path or None."""
    template = str(dst_dir / '%(id)s.%(ext)s')
    cmd = [
        YT_DLP, '--no-warnings', '--quiet',
        '--extract-audio', '--audio-format', 'mp3',
        '--no-playlist',
        '--ffmpeg-location', FFMPEG_DIR,
        '--no-simulate',                                            # required when --print is in play; here it's belt-and-suspenders
        '-o', template,
        url,
    ]
    rc, out, err = run(cmd, timeout=180)
    if rc != 0:
        print(f'    DOWNLOAD FAIL: {err[-200:]}')
        return None
    mp3s = list(dst_dir.glob('*.mp3'))
    if not mp3s:
        print(f'    DOWNLOAD: no mp3 produced')
        return None
    mp3s.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return mp3s[0]


def ffmpeg_trim_loudnorm(src: Path, dst: Path, target_sec: float) -> bool:
    """Trim src to first target_sec, then loudnorm. Same params as the main batch."""
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
        print(f'    FFMPEG FAIL: {err[-200:]}')
        return False
    return True


def pick_candidate(candidates: list[dict], blacklist: list[str]) -> dict | None:
    """Walk candidates in order; return first that passes both gates:
       (a) duration < DURATION_CEILING_SEC, (b) title has no blacklisted token.
    If NO candidate passes both, fall back to the first that passes ONLY the
    blacklist filter — duration ceiling is the music-rejection heuristic, but
    foley compilations are often 60-90s and aren't music. Since we trim the
    output to a target_sec window anyway, source length doesn't actually matter
    for the final clip quality."""
    blacklist_lower = [b.lower() for b in blacklist]

    def passes_blacklist(c: dict) -> bool:
        title_lower = c['title'].lower()
        return not any(tok in title_lower for tok in blacklist_lower)

    # Strict pass: both gates
    for c in candidates:
        title_lower = c['title'].lower()
        dur = c['duration_sec']
        reasons = []
        if dur >= DURATION_CEILING_SEC:
            reasons.append(f'duration {dur:.1f}s >= ceiling {DURATION_CEILING_SEC}s')
        for tok in blacklist_lower:
            if tok in title_lower:
                reasons.append(f'title contains blacklisted token "{tok}"')
        if reasons:
            print(f'    REJECT: {c["title"][:70]}  ({c["duration_sec"]:.1f}s)  -> {"; ".join(reasons)}')
        else:
            print(f'    PICK:   {c["title"][:70]}  ({c["duration_sec"]:.1f}s)  {c["url"]}')
            return c

    # Fallback: blacklist-only (ignore duration). Catches foley compilations
    # > 30s that aren't music. Output is trim-to-target_sec anyway.
    for c in candidates:
        if passes_blacklist(c):
            print(f'    FALLBACK PICK (duration ceiling relaxed):')
            print(f'              {c["title"][:70]}  ({c["duration_sec"]:.1f}s)  {c["url"]}')
            return c

    return None


def main() -> int:
    if not SFX_DIR.exists():
        print(f'ERROR: {SFX_DIR} does not exist')
        return 1
    failures = []
    with tempfile.TemporaryDirectory() as tmp_root:
        for filename, query, target_sec, blacklist in RESOURCE_SPEC:
            dst = SFX_DIR / filename
            print(f'\n==> {filename}')
            print(f'    query: {query!r}')
            print(f'    target duration: {target_sec}s, blacklist: {blacklist}')

            print(f'  -- Fetching metadata for top 3 candidates --')
            candidates = yt_dlp_search_metadata(query, n=3)
            if not candidates:
                print(f'    NO CANDIDATES returned')
                failures.append(filename)
                continue
            for i, c in enumerate(candidates, 1):
                print(f'    [{i}] "{c["title"][:80]}"  ({c["duration_sec"]:.1f}s)  {c["url"]}')

            print(f'  -- Selecting first candidate that passes filters --')
            picked = pick_candidate(candidates, blacklist)
            if not picked:
                print(f'    NO CANDIDATE passed filters')
                failures.append(filename)
                continue

            print(f'  -- Downloading + trimming + loudnorm --')
            tmp_dir = Path(tmp_root) / filename.replace('.mp3', '')
            tmp_dir.mkdir(exist_ok=True)
            src = yt_dlp_download_url(picked['url'], tmp_dir)
            if not src:
                failures.append(filename)
                continue
            ok = ffmpeg_trim_loudnorm(src, dst, target_sec)
            if ok:
                size_kb = dst.stat().st_size / 1024
                print(f'    OK -> {dst.name} ({size_kb:.1f} KB)')
            else:
                failures.append(filename)

    print()
    print('--- Re-source results ---')
    if failures:
        print(f'FAILED: {failures}')
        return 1
    print(f'All {len(RESOURCE_SPEC)} SFX re-sourced successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
