"""Convert inline-base64 JPG sprites in index.html to standalone PNGs with real alpha
channels via rembg, then verify each output actually has transparent pixels.

Usage:
    python3 scripts/convert_sprites_to_png.py
    python3 scripts/convert_sprites_to_png.py --models u2net,isnet-general-use,silueta
    python3 scripts/convert_sprites_to_png.py --names antifa,briefcase

Behavior:
  1. Parse `spriteData = { NAME: 'data:image/jpeg;base64,...', ... }` from index.html.
  2. For each sprite name:
       a. Decode base64 -> JPG bytes -> save to scripts/_extracted_jpgs/NAME.jpg.
       b. Run rembg.remove() with the first model in --models that produces a valid output.
       c. Save result as <project_root>/sprites/NAME.png.
       d. Verify: re-open the PNG, confirm RGBA mode, count alpha<255 pixels.
          FAIL if pixel count is 0 or < 5% of total pixels.
  3. Print summary. Exit non-zero if any failures.

Failures the user must hand-cut go in MANUAL CONVERSION NEEDED list.
"""
from __future__ import annotations
import argparse
import base64
import io
import os
import re
import sys
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML = PROJECT_ROOT / 'index.html'
EXTRACTED_DIR = Path(__file__).parent / '_extracted_jpgs'
OUTPUT_DIR = PROJECT_ROOT / 'sprites'

DEFAULT_MODELS = ['u2net', 'isnet-general-use', 'silueta']
MIN_ALPHA_PCT = 5.0     # minimum % of pixels that must be transparent (alpha < 255) to pass

# spriteData entry pattern. Uses non-greedy capture for the base64 payload
# (the payload contains no apostrophes so the closing quote is unambiguous).
SPRITE_LINE_RE = re.compile(
    r"^\s*(\w+)\s*:\s*['\"]data:image/jpeg;base64,([A-Za-z0-9+/=]+)['\"]\s*,?\s*$"
)


def parse_sprites(html_path: Path) -> list[tuple[str, bytes]]:
    sprites: list[tuple[str, bytes]] = []
    with open(html_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = SPRITE_LINE_RE.match(line)
            if not m:
                continue
            name, b64 = m.group(1), m.group(2)
            try:
                jpg_bytes = base64.b64decode(b64, validate=True)
            except Exception as e:
                print(f"  ERROR: could not base64-decode {name}: {e}", file=sys.stderr)
                continue
            sprites.append((name, jpg_bytes))
    return sprites


def verify_alpha(png_path: Path) -> tuple[bool, int, int, str]:
    """Return (passed, alpha_count, total_pixels, message)."""
    try:
        with Image.open(png_path) as im:
            if im.mode != 'RGBA':
                return False, 0, 0, f"mode is {im.mode}, expected RGBA"
            alpha = im.split()[-1]
            total = alpha.size[0] * alpha.size[1]
            # Count pixels with alpha < 255
            histogram = alpha.histogram()
            alpha_count = sum(histogram[:255])
            pct = (alpha_count / total) * 100.0 if total else 0.0
            if alpha_count == 0:
                return False, 0, total, f"0 transparent pixels"
            if pct < MIN_ALPHA_PCT:
                return False, alpha_count, total, f"only {pct:.2f}% transparent (need >{MIN_ALPHA_PCT}%)"
            return True, alpha_count, total, f"{alpha_count} transparent ({pct:.1f}%)"
    except Exception as e:
        return False, 0, 0, f"open/inspect failed: {e}"


def remove_bg_with_model(jpg_bytes: bytes, model: str) -> bytes:
    session = new_session(model)
    return remove(jpg_bytes, session=session)


def process(name: str, jpg_bytes: bytes, models: list[str], jpg_dir: Path, png_dir: Path) -> tuple[bool, str]:
    jpg_path = jpg_dir / f"{name}.jpg"
    png_path = png_dir / f"{name}.png"
    jpg_path.write_bytes(jpg_bytes)

    last_err = ""
    for model in models:
        try:
            png_bytes = remove_bg_with_model(jpg_bytes, model)
        except Exception as e:
            last_err = f"rembg model={model} crashed: {e}"
            print(f"  WARN: {name} {last_err}")
            continue
        png_path.write_bytes(png_bytes)
        passed, alpha_count, total, msg = verify_alpha(png_path)
        if passed:
            print(f"  OK : {name}.JPG -> {name}.png  model={model}  {msg}  total={total}")
            return True, model
        else:
            last_err = f"{msg} (model={model})"
            print(f"  TRY-FAIL: {name} model={model} -> {msg}")
    # all models failed
    print(f"  FAIL: {name}.png — {last_err}")
    return False, last_err


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', default=','.join(DEFAULT_MODELS),
                        help='comma-separated list of rembg models to try in order')
    parser.add_argument('--names', default='', help='comma-separated subset of sprite names (default: all)')
    args = parser.parse_args()

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sprites = parse_sprites(INDEX_HTML)
    if not sprites:
        print("ERROR: no sprites parsed from spriteData", file=sys.stderr)
        return 1

    if args.names:
        wanted = {n.strip() for n in args.names.split(',') if n.strip()}
        sprites = [(n, b) for (n, b) in sprites if n in wanted]
        if not sprites:
            print(f"ERROR: --names filter matched zero sprites", file=sys.stderr)
            return 1

    models = [m.strip() for m in args.models.split(',') if m.strip()]
    print(f"Converting {len(sprites)} sprites using models {models}")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    for name, jpg_bytes in sprites:
        ok, info = process(name, jpg_bytes, models, EXTRACTED_DIR, OUTPUT_DIR)
        if ok:
            successes.append(name)
        else:
            failures.append((name, info))

    print()
    print(f"Converted {len(successes)} / {len(sprites)} sprites successfully.")
    if failures:
        print(f"Failures: {[n for n, _ in failures]}")
        print()
        print("MANUAL CONVERSION NEEDED for: " + ', '.join(n for n, _ in failures))
        print("Drop hand-cut PNG files into the sprites/ directory with the same names.")
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
