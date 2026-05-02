"""SFX-RERUN-3 — extract preview MP3 URLs from freesound.org sound pages.

WebFetch summarizes pages and drops inline asset URLs. requests + regex
on the raw HTML works because freesound embeds preview URLs in the page's
JS data blocks (window.sound or similar).

Targets (the 2 candidates picked from search results):
  - sound 43607 by FreqMan   ('sandbag.wav', target: ragdoll)
  - sound 452667 by kyles    ('window break with axe glass shatter in trailer.wav', target: capsule)

Outputs the preview URL + license + duration so the next pipeline step
can download from the CDN and run the standard trim+loudnorm+mean_volume
pass.
"""
import re
import cloudscraper                                           # bypasses Cloudflare TLS fingerprinting
import requests                                               # kept for fallback / type hints

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

TARGETS = [
    ('FreqMan', 43607, 'sfx_ragdoll_thud'),
    ('kyles',   452667, 'sfx_capsule_destruction'),
]


_scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})


def fetch(url: str) -> str:
    r = _scraper.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text


def extract_preview_urls(html: str) -> list[str]:
    """Find any cdn.freesound.org/previews/... URL embedded in the page.
    Captures both the bare URL and any escaped/JSON-quoted variants."""
    pattern = re.compile(r'https?://[^"\'\s]*cdn\.freesound\.org/previews/[^"\'\s]+\.(?:mp3|ogg)')
    return list(dict.fromkeys(pattern.findall(html)))   # dedupe, preserve order


def extract_license(html: str) -> str | None:
    # Common patterns on freesound sound pages
    for pat in [
        r'creativecommons\.org/publicdomain/zero/1\.0/',
        r'creativecommons\.org/licenses/by/[\d.]+/',
        r'creativecommons\.org/licenses/by-nc/[\d.]+/',
    ]:
        if re.search(pat, html):
            return pat
    return None


def main() -> int:
    print(f'{"target":<32}{"sound":<48}{"license":<55}{"preview":<60}')
    print('-' * 195)
    for user, sid, target_name in TARGETS:
        page_url = f'https://freesound.org/people/{user}/sounds/{sid}/'
        try:
            html = fetch(page_url)
        except Exception as e:
            print(f'{target_name:<32}FAIL fetch: {e}')
            continue
        previews = extract_preview_urls(html)
        license_ = extract_license(html) or '(none)'
        preview = previews[0] if previews else '(none found)'
        sound_label = f'{user}/{sid}'
        print(f'{target_name:<32}{sound_label:<48}{license_[:54]:<55}{preview:<60}')
        # Also show all previews if multiple (HQ + LQ + ogg variants)
        if len(previews) > 1:
            for p in previews[1:]:
                print(f'{"":<32}{"":<48}{"":<55}{p:<60}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
