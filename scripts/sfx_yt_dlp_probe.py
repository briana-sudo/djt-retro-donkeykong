"""One-shot probe — run yt-dlp via subprocess.run with the same args the batch
script uses, but WITHOUT --quiet, to see what's failing silently."""
import subprocess
import tempfile
from pathlib import Path

WINGET_BIN = r'C:\Users\brian\AppData\Local\Microsoft\WinGet\Packages'
FFMPEG_DIR = WINGET_BIN + r'\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin'
YT_DLP     = WINGET_BIN + r'\yt-dlp.yt-dlp_Microsoft.Winget.Source_8wekyb3d8bbwe\yt-dlp.exe'

with tempfile.TemporaryDirectory() as tmp_root:
    tmp_dir = Path(tmp_root) / 'pelosi'
    tmp_dir.mkdir()
    template = str(tmp_dir / '%(id)s.%(ext)s')
    cmd = [
        YT_DLP, '--no-warnings',
        '--extract-audio', '--audio-format', 'mp3',
        '--no-playlist',
        '--ffmpeg-location', FFMPEG_DIR,
        '-o', template,
        '--print', 'webpage_url',
        'ytsearch1:paper tear sound effect',
    ]
    print('CMD:', ' '.join(repr(c) for c in cmd))
    print()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=180)
    print(f'returncode: {proc.returncode}')
    print(f'--- STDOUT ---')
    print(proc.stdout)
    print(f'--- STDERR ---')
    print(proc.stderr)
    print(f'--- DIR CONTENTS ---')
    for p in tmp_dir.iterdir():
        print(f'  {p.name}  ({p.stat().st_size} bytes)')
    print(f'--- TMP_ROOT CONTENTS ---')
    for p in Path(tmp_root).rglob('*'):
        if p.is_file():
            print(f'  {p.relative_to(tmp_root)}  ({p.stat().st_size} bytes)')
