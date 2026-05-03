"""SFX-RERUN-3 — download identified freesound.org previews + standard pipeline.

Tool change from yt-dlp: yt-dlp returns YouTube videos, which means tutorials,
vlogs, and people TALKING about sounds rank higher than the sounds themselves.
freesound.org returns sound files by definition. Two failed yt-dlp attempts
(silent-source ragdoll, talking-head capsule) drove this switch.

Per-target spec was identified manually via freesound.org search + WebFetch
prompt parsing. The hard parts (TLS-fingerprint bot detection, preview URL
discovery) were solved in scripts/freesound_extract_preview.py — this script
just downloads from the discovered URLs and runs the standard pipeline.

If freesound CDN is also bot-protected we'll find out here; the spec's final
fallback is "report back, do NOT re-run yt-dlp" — that path triggers if
download or any subsequent step fails.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cloudscraper

PROJECT_ROOT = Path(__file__).parent.parent
SFX_DIR      = PROJECT_ROOT / 'audio' / 'sfx'
WINGET_BIN   = r'C:\Users\brian\AppData\Local\Microsoft\WinGet\Packages'
FFMPEG       = WINGET_BIN + r'\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin\ffmpeg.exe'

MIN_MEAN_VOL_DB = -50.0

# Each entry: filename, hq_preview_url, target_sec, sound_page_url, license, author
TARGETS = [
    {
        'filename':   'sfx_ragdoll_thud.mp3',
        'preview':    'https://cdn.freesound.org/previews/43/43607_92661-hq.mp3',
        'target_sec': 1.0,                                     # mid of 0.8-1.2
        'page':       'https://freesound.org/people/FreqMan/sounds/43607/',
        'license':    'CC-BY 4.0',
        'author':     'FreqMan',
        'title':      'sandbag.wav',
        'src_dur':    1.746,
    },
    {
        'filename':   'sfx_capsule_destruction.mp3',
        'preview':    'https://cdn.freesound.org/previews/452/452667_612689-hq.mp3',
        'target_sec': 2.0,                                     # mid of 1.5-2.5
        'page':       'https://freesound.org/people/kyles/sounds/452667/',
        'license':    'CC0 (Public Domain)',
        'author':     'kyles',
        'title':      'window break with axe glass shatter in trailer.wav',
        'src_dur':    6.756,
    },
    # SFX-RERUN-5 — player death scream, MASCULINE PAINED GRUNT (Brian's
    # revised spec rejected the cartoon vibe). Picked from 3 CC0 candidates
    # under "male grunt pain hit" search; chose MrFossy as #1 ranked + most
    # explicit name match (AdultMale_PainGrunts pack). Backups for future
    # iteration if needed: EvilOldScratch/667697 (Strong_Male_Grunt1) and
    # miksmusic/497713 (Punch Grunt 1, CC-BY).
    {
        'filename':   'sfx_player_death_scream.mp3',
        'preview':    'https://cdn.freesound.org/previews/547/547209_129727-hq.mp3',
        'target_sec': 0.7,                                     # mid of 0.5-0.9
        'page':       'https://freesound.org/people/MrFossy/sounds/547209/',
        'license':    'CC0 (Public Domain)',
        'author':     'MrFossy',
        'title':      'Voice_AdultMale_PainGrunts_09.wav',
        'src_dur':    0.0,                                     # not measured pre-download; reported by ffprobe post
    },
    # SIREN-SOURCE — police/emergency siren loop for siren_loop.mp3 (FBI badge
    # weapon audio, P-WEAPON-1 wiring follows after Brian field-tests standalone).
    # chripei/393666 picked from 2 candidates: CC0 (no attribution) + explicitly
    # designed loop ("WaHi siren to loop") + NYC emergency vehicle context.
    # target_sec=2.85 keeps just under source 2.899s to preserve author-crafted
    # loop boundaries — trimming to literal "1-2s" spec would slice mid-wave and
    # break the loop. Brian's "looping: no abrupt gap" requirement supersedes the
    # ~1-2s duration approximate. Backup: Lalks/336894 (CC-BY 3.0, 1.7s ambulance).
    {
        'filename':   'siren_loop.mp3',
        'preview':    'https://cdn.freesound.org/previews/393/393666_1617412-hq.mp3',
        'target_sec': 2.85,
        'page':       'https://freesound.org/people/chripei/sounds/393666/',
        'license':    'CC0 (Public Domain)',
        'author':     'chripei',
        'title':      'WaHi siren to loop.mp3',
        'src_dur':    2.899,
    },
    # INTRO_TAUNT-V3 — USA chant for crowd_usa_chant.mp3 (eagle-entry / RNC stage
    # rally vibe). Picked from 3 candidates returned by "USA chant" search.
    # FlatHill/324752 chosen: CC0 (no attribution), explicit title match for
    # "USA Chant" (Rugby World Cup context — neutral sports rally vs the
    # politically-charged protest alternatives). Loops in-game so target trim
    # captures a clean rhythmic loop.
    {
        'filename':   'crowd_usa_chant.mp3',
        'preview':    'https://cdn.freesound.org/previews/324/324752_3839718-hq.mp3',
        'target_sec': 4.0,                                     # mid of 3.0-5.0 spec range
        'page':       'https://freesound.org/people/FlatHill/sounds/324752/',
        'license':    'CC0 (Public Domain)',
        'author':     'FlatHill',
        'title':      'JAPAN VS USA RWC Chant',
        'src_dur':    0.0,                                     # not measured pre-download
    },
]


_scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})


def download_preview(url: str, dst: Path) -> bool:
    print(f'      downloading: {url}')
    try:
        r = _scraper.get(url, timeout=60, stream=True, allow_redirects=True)
        r.raise_for_status()
        with open(dst, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        size_kb = dst.stat().st_size / 1024
        print(f'      downloaded: {size_kb:.1f} KB')
        return True
    except Exception as e:
        print(f'      DOWNLOAD FAIL: {type(e).__name__}: {e}')
        return False


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def ffmpeg_trim_loudnorm(src: Path, dst: Path, target_sec: float) -> bool:
    cmd = [
        FFMPEG, '-y', '-hide_banner', '-loglevel', 'error',
        '-i', str(src),
        '-t', str(target_sec),
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(dst),
    ]
    rc, out, err = run(cmd)
    if rc != 0:
        print(f'      FFMPEG FAIL: {err[-200:]}')
        return False
    return True


def measure_mean_volume(mp3: Path) -> float | None:
    cmd = [FFMPEG, '-hide_banner', '-i', str(mp3), '-af', 'volumedetect', '-f', 'null', '-']
    _, _, err = run(cmd, timeout=30)
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


def main() -> int:
    if not SFX_DIR.exists():
        print(f'ERROR: {SFX_DIR} does not exist')
        return 1
    failures = []
    with tempfile.TemporaryDirectory() as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        for t in TARGETS:
            print(f'\n==> {t["filename"]}')
            dst_pre = SFX_DIR / t['filename']
            if dst_pre.exists():
                print(f'    SKIP (already exists, {dst_pre.stat().st_size / 1024:.1f} KB) — '
                      f'delete the file first to force re-pull')
                continue
            print(f'    title:    {t["title"]}')
            print(f'    author:   {t["author"]}')
            print(f'    license:  {t["license"]}')
            print(f'    page:     {t["page"]}')
            print(f'    src_dur:  {t["src_dur"]}s   target output: {t["target_sec"]}s')

            tmp_src = tmp_root / f'{t["filename"]}.tmp'
            if not download_preview(t['preview'], tmp_src):
                failures.append(t['filename'])
                continue

            dst = SFX_DIR / t['filename']
            ok = ffmpeg_trim_loudnorm(tmp_src, dst, t['target_sec'])
            if not ok:
                failures.append(t['filename'])
                continue

            mv = measure_mean_volume(dst)
            if mv is None:
                print(f'      WARN: could not parse mean_volume; treating as failed')
                failures.append(t['filename'])
                continue
            print(f'      mean_volume: {mv:+.1f} dB')
            if mv < MIN_MEAN_VOL_DB:
                print(f'      REJECT: silent (mean_volume {mv:+.1f} dB < {MIN_MEAN_VOL_DB:+.1f} dB)')
                try:
                    dst.unlink()
                except Exception:
                    pass
                failures.append(t['filename'])
                continue

            size_kb = dst.stat().st_size / 1024
            print(f'      ACCEPT: {dst.name}  {size_kb:.1f} KB  (mean_vol {mv:+.1f} dB)')

    print('\n--- freesound pipeline results ---')
    if failures:
        print(f'FAILED: {failures}')
        return 1
    print(f'All {len(TARGETS)} files downloaded + processed successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
