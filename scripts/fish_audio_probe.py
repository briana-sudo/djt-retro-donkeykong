"""One-shot probe: confirm whether the FISH_API_KEY can reach any endpoint at all.
Used to triage 402 Payment Required: if list_models also 402s, no API access on
this account; if list_models succeeds, the key is valid and only TTS is gated.
"""
import os
import sys
from fish_audio_sdk import Session

key = os.environ.get('FISH_API_KEY')
if not key:
    print('FISH_API_KEY env var not set')
    sys.exit(1)

s = Session(key)
try:
    page = s.list_models(page_size=1, page_number=1)
    total = getattr(page, 'total', 'unknown')
    print(f'LIST_MODELS OK -> total models visible = {total}')
    items = getattr(page, 'items', None)
    if items:
        m = items[0]
        print(f'  sample id = {m.id}')
        print(f'  sample title = {getattr(m, "title", "?")}')
    print('Conclusion: API key authenticates successfully on read endpoints.')
    print('The 402 on TTS is a TTS-specific billing gate, not a key auth problem.')
except Exception as e:
    print(f'LIST_MODELS FAIL: {e}')
    print('Conclusion: API key cannot reach any endpoint — likely tier/account issue.')
    sys.exit(1)
