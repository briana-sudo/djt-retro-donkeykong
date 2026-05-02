"""AUDIO-VOICE-TEST — Fish Audio TTS generation pipeline.

Reads FISH_API_KEY from env. Takes a list of (text, reference_id, output_path)
tuples; for each, calls Fish Audio's streaming TTS endpoint and writes the raw
mp3 chunks to a temp file, then runs an ffmpeg loudnorm pass to normalize to the
project's standard target (-16 LUFS / -1.5 dBTP / 11 LU range — same as
audio_3h_loudnorm.py for BGM consistency).

Idempotent: skips any output_path that already exists. Re-running won't
re-bill the Fish Audio API.

Usage:
    set FISH_API_KEY=<key>
    py scripts/fish_audio_generate.py phase1   # 6 test files, audio/sfx/test/
    py scripts/fish_audio_generate.py phase2   # 15 production files, audio/sfx/

Phase 1 outputs go to audio/sfx/test/ (separate folder so Brian can listen
and reject without polluting the production audio/sfx/ directory). Phase 2
outputs go to audio/sfx/ directly.
"""
from __future__ import annotations
import os
import sys
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SFX_DIR      = PROJECT_ROOT / 'audio' / 'sfx'
TEST_DIR     = SFX_DIR / 'test'
FFMPEG       = r'C:\Users\brian\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-124279-g0f6ba39122-win64-gpl\bin\ffmpeg.exe'

# AUDIO-VOICE-TEST — 3 candidate Trump voice models from fish.audio/discovery,
# ranked by Brian. Phase 1 generates test clips on all 3; Phase 2 uses only the
# winning model.
CANDIDATE_MODELS = [
    ('5196af35', '5196af35f6ff4a0dbf541793fc9f2157', 'Donald J. Trump (Noise reduction) by SHIB'),
    ('e58b0d7e', 'e58b0d7efca34eb38d5c4985e378abcb', 'POTUS 47 - Trump by Reaction Vid'),
    ('4457d0e6', '4457d0e6cc6745ae970231ba902c6b3d', 'Donald J Trump by yownhisaeden'),
]

PHASE1_PHRASES = [
    ('Fake news!', 'fakenews'),
    ('Loser!',     'loser'),
]

# AUDIO-BATCH Phase 2 — winning model picked by Brian after Phase 1 listening:
# 5196af35f6ff4a0dbf541793fc9f2157 = Donald J. Trump (Noise reduction) by SHIB.
WINNING_MODEL_ID = '5196af35f6ff4a0dbf541793fc9f2157'

# Phase 2 production phrases — 15 total. INTRO/CUTSCENE entries prepend emotion-
# tag prefix per Brian's spec; if the model ignores the tag, the prefix may be
# spoken literally — Brian flags those in field test for surgical re-source.
# Each tuple: (text_to_synthesize, output_filename_without_extension).
PHASE2_PHRASES = [
    # Death lines (5)
    ('Loser!',                          'trump_loser'),
    ('Sad!',                            'trump_sad'),
    ('Fake news!',                      'trump_fakenews'),
    ('Weak!',                           'trump_weak'),         # SHARED with taunts — generate ONCE
    ('Witch hunt!',                     'trump_witchhunt'),
    # In-game taunts (8 — trump_weak above is shared)
    ('Crooked Dems!',                   'trump_crooked_dems'),
    ('Nasty!',                          'trump_nasty'),
    ('Worst ever!',                     'trump_worst_ever'),
    ('Disgraceful!',                    'trump_disgraceful'),
    ('Pathetic losers!',                'trump_pathetic_losers'),
    ('Totally corrupt!',                'trump_totally_corrupt'),
    ('Democrats hate America!',         'trump_democrats_hate_america'),
    ('Radical left mob!',               'trump_radical_left_mob'),
    # Intro/cutscene (2 — emotion-tag attempt)
    ('(angry, emphatic) Fake news!',    'trump_fakenews_intro'),
    ('(angry, emphatic) Witch hunt!',   'trump_witchhunt_cutscene'),
]

# REPORTER-CLIPS — 3 press-chaos voice clips, each on a DIFFERENT Fish Audio
# voice model (varied reporter voices for the press scrum overlay). Picked by
# Brian from fish.audio/discovery — different speakers per clip so the press
# layer doesn't sound like one person echoing themselves.
# Each tuple: (text, reference_id, output_filename_without_extension, voice_label).
REPORTER_CLIPS = [
    ("You can't win!",                  'a00ddfe2c5754b019ad2de0b5b709ce8',
     'reporter_you_cant_win',           'USA female reporter'),
    ("What about Russia?",              '6972ae9185854c03bcbff1f84a570b2a',
     'reporter_what_about_russia',      'Reporter ABC News - M'),
    ("One more question, Mr. Trump!",   '80b0962985d244eca7d96d91985618c0',
     'reporter_one_more_question',      'REPORTER - male urgent'),
]


def loudnorm(src_path: Path, dst_path: Path) -> bool:
    """Single-pass ffmpeg loudnorm to project standard. Returns True on success.
    Single-pass (not the 2-pass measure-then-apply used by audio_3h_loudnorm.py)
    because TTS output is short + already roughly consistent volume per session;
    2-pass would be overkill and slower for 6-15 short clips.
    """
    cmd = [
        FFMPEG, '-y', '-hide_banner', '-loglevel', 'error',
        '-i', str(src_path),
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(dst_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f'    LOUDNORM FAIL: {proc.stderr[-300:]}')
        return False
    return True


def generate_clip(session, text: str, reference_id: str, dst_path: Path) -> bool:
    """Stream TTS audio from Fish Audio to a temp mp3, then loudnorm to dst_path.
    Returns True on success.
    """
    if dst_path.exists():
        print(f'    SKIP (exists): {dst_path.name}')
        return True
    from fish_audio_sdk import TTSRequest
    # Fish Audio streams raw mp3 chunks. Write to a temp file first, then
    # loudnorm-pass into the final dst_path.
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        tmp_path = Path(tmp.name)
        try:
            for chunk in session.tts(TTSRequest(text=text, reference_id=reference_id)):
                tmp.write(chunk)
            tmp.flush()
        except Exception as e:
            print(f'    TTS API FAIL: {e}')
            return False
    try:
        if tmp_path.stat().st_size == 0:
            print(f'    EMPTY MP3 from API (probably bad model_id or auth)')
            return False
        ok = loudnorm(tmp_path, dst_path)
        return ok
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def phase1():
    """Generate 6 test files: 3 candidate models × 2 phrases each."""
    api_key = os.environ.get('FISH_API_KEY')
    if not api_key:
        print('FISH_API_KEY env var not set. Aborting.')
        return 1
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    from fish_audio_sdk import Session
    session = Session(api_key)
    results = []
    for short, model_id, label in CANDIDATE_MODELS:
        print(f'\n==> {short} ({label})')
        for phrase_text, phrase_short in PHASE1_PHRASES:
            dst = TEST_DIR / f'{short}_{phrase_short}.mp3'
            print(f'  - "{phrase_text}" -> {dst.name}')
            ok = generate_clip(session, phrase_text, model_id, dst)
            if ok and dst.exists():
                size_kb = dst.stat().st_size / 1024
                results.append((dst.name, size_kb, True))
            else:
                results.append((dst.name, 0, False))
    print('\n--- Phase 1 results ---')
    for name, size_kb, ok in results:
        status = 'OK' if ok else 'FAIL'
        print(f'  [{status}] {name}  ({size_kb:.1f} KB)')
    fail_count = sum(1 for _, _, ok in results if not ok)
    return 1 if fail_count else 0


def phase2():
    """Generate 15 production Trump voice clips on the winning model."""
    api_key = os.environ.get('FISH_API_KEY')
    if not api_key:
        print('FISH_API_KEY env var not set. Aborting.')
        return 1
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    from fish_audio_sdk import Session
    session = Session(api_key)
    print(f'\n==> Phase 2 — model {WINNING_MODEL_ID} (SHIB Donald J. Trump Noise Reduction)')
    print(f'    {len(PHASE2_PHRASES)} clips to generate\n')
    results = []
    for text, name_short in PHASE2_PHRASES:
        dst = SFX_DIR / f'{name_short}.mp3'
        print(f'  - "{text}" -> {dst.name}')
        ok = generate_clip(session, text, WINNING_MODEL_ID, dst)
        if ok and dst.exists():
            size_kb = dst.stat().st_size / 1024
            results.append((dst.name, size_kb, True))
        else:
            results.append((dst.name, 0, False))
    print('\n--- Phase 2 results ---')
    for name, size_kb, ok in results:
        status = 'OK' if ok else 'FAIL'
        print(f'  [{status}] {name}  ({size_kb:.1f} KB)')
    fail_count = sum(1 for _, _, ok in results if not ok)
    return 1 if fail_count else 0


def reporters():
    """Generate 3 press-chaos reporter clips, each on a different voice model."""
    api_key = os.environ.get('FISH_API_KEY')
    if not api_key:
        print('FISH_API_KEY env var not set. Aborting.')
        return 1
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    from fish_audio_sdk import Session
    session = Session(api_key)
    print(f'\n==> Reporter clips — {len(REPORTER_CLIPS)} clips, mixed voices\n')
    results = []
    for text, reference_id, name_short, voice_label in REPORTER_CLIPS:
        dst = SFX_DIR / f'{name_short}.mp3'
        print(f'  - "{text}"  ({voice_label})  -> {dst.name}')
        ok = generate_clip(session, text, reference_id, dst)
        if ok and dst.exists():
            size_kb = dst.stat().st_size / 1024
            results.append((dst.name, size_kb, True))
        else:
            results.append((dst.name, 0, False))
    print('\n--- Reporter clips results ---')
    for name, size_kb, ok in results:
        status = 'OK' if ok else 'FAIL'
        print(f'  [{status}] {name}  ({size_kb:.1f} KB)')
    fail_count = sum(1 for _, _, ok in results if not ok)
    return 1 if fail_count else 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: py scripts/fish_audio_generate.py {phase1|phase2}')
        sys.exit(2)
    arg = sys.argv[1]
    if arg == 'phase1':
        sys.exit(phase1())
    elif arg == 'phase2':
        sys.exit(phase2())
    elif arg == 'reporters':
        sys.exit(reporters())
    else:
        print(f'Unknown phase: {arg}')
        sys.exit(2)
