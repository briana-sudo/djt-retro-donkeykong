"""SFX-RERUN-3 — probe freesound.org access patterns. Read-only diagnostic.

Tests in order of decreasing convenience:
  1. API search WITHOUT token → expect 401, just confirms it's gated
  2. Public search page HTML scrape → check structure / accessibility
  3. CDN preview URL guessability — if a sound ID + user_id can be obtained
     from the HTML, the LQ-mp3 preview URL pattern is open and downloadable
     without auth (https://cdn.freesound.org/previews/<thousands>/<id>_<u>-lq.mp3)

Reports what's possible. Decides nothing — caller picks next step.
"""
from __future__ import annotations
import re
import sys
import urllib.request
import urllib.error
import urllib.parse


def http_get(url: str, timeout: int = 30) -> tuple[int, str, dict]:
    """Returns (status_code, body_text, response_headers). Never raises."""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; KCC-DJTRetroDK/1.0)',
        'Accept': '*/*',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', errors='replace')
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace') if e.fp else ''
        return e.code, body, dict(e.headers) if e.headers else {}
    except Exception as e:
        return 0, f'{type(e).__name__}: {e}', {}


def probe_api_no_token() -> None:
    print('=== Probe 1: freesound API without token ===')
    url = 'https://freesound.org/apiv2/search/text/?query=sandbag+drop'
    status, body, hdrs = http_get(url)
    print(f'  status: {status}')
    print(f'  body[:300]: {body[:300]!r}')


def probe_search_page(query: str) -> str | None:
    print(f'\n=== Probe 2: search page HTML for query={query!r} ===')
    encoded = urllib.parse.quote_plus(query)
    url = f'https://freesound.org/search/?q={encoded}&f=duration:[0.5 TO 10]&s=score+desc'
    print(f'  URL: {url}')
    status, body, hdrs = http_get(url)
    print(f'  status: {status}')
    print(f'  content-type: {hdrs.get("Content-Type", "?")}')
    print(f'  body length: {len(body)} chars')
    # Look for sound result patterns. freesound.org markup typically has
    # <a href="/people/<user>/sounds/<id>/">. Capture first 5.
    matches = re.findall(r'/people/([^/]+)/sounds/(\d+)/', body)
    seen = []
    for user, sid in matches:
        if (user, sid) in seen:
            continue
        seen.append((user, sid))
        if len(seen) >= 5:
            break
    print(f'  unique sound links found: {len(seen)}')
    for user, sid in seen:
        print(f'    sound id={sid}  user={user}  page=https://freesound.org/people/{user}/sounds/{sid}/')
    return body if status == 200 else None


def probe_sound_detail_page(user: str, sound_id: str) -> None:
    """Pull a single sound detail page and look for: numeric user_id (for
    preview URL construction), license, duration, preview URLs."""
    print(f'\n=== Probe 3: sound detail page id={sound_id} user={user} ===')
    url = f'https://freesound.org/people/{user}/sounds/{sound_id}/'
    print(f'  URL: {url}')
    status, body, hdrs = http_get(url)
    print(f'  status: {status}')
    if status != 200:
        print(f'  cannot proceed')
        return
    # Look for preview URL hint in the HTML
    preview_matches = re.findall(r'https?://cdn\.freesound\.org/previews/[^"\']+', body)
    print(f'  preview URLs found in page: {len(preview_matches)}')
    for p in preview_matches[:3]:
        print(f'    {p}')
    # Look for license info
    license_match = re.search(r'(Creative Commons[^<\n]{0,80}|Public Domain|CC0|CC BY[^<\n]{0,40})', body)
    if license_match:
        print(f'  license hint: {license_match.group(1)[:80]}')
    # Duration hint
    dur_match = re.search(r'(\d+\.\d+)\s*(?:seconds?|s)\b', body)
    if dur_match:
        print(f'  duration hint: {dur_match.group(1)}s')


def main() -> int:
    probe_api_no_token()
    body = probe_search_page('sandbag drop floor')
    if body:
        # Extract first sound + try detail-page probe
        m = re.search(r'/people/([^/]+)/sounds/(\d+)/', body)
        if m:
            probe_sound_detail_page(m.group(1), m.group(2))
    print('\n=== Probe complete. ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
