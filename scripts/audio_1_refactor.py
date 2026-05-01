"""AUDIO-1 surgical refactor: replace synth music infrastructure with Howler-based version.

Operates on index.html. Idempotent — running twice is a no-op (anchors are gone after first run).

Regions replaced:
  1. L996-L1218  — synth schedulers + state-machine header comment
  2. L1220-1228  — MUSIC_STATES enum (add YMCA)
  3. L1230-1274  — computeDesiredMusic (add YMCA + dance condition)
  4. L1276-1322  — transitionToMusic (Howler version)
  5. L1324-1366  — tickBGM (simplified)
  6. L1368-1624  — _bgmScheduleMachoMan + cue functions + duck/unduck/fade helpers (deleted)
  7. L810-857    — playYmcaNote / startYmca / stopYmca (deleted; Howler handles YMCA)

Anchors used (search-and-replace on text, not line numbers, so future edits don't break this).
"""
from pathlib import Path
import re

SRC = Path(__file__).parent.parent / 'index.html'
text = SRC.read_text(encoding='utf-8')

# ---- 1. Replace synth scheduler block + state-machine header (~L996-L1219) ----
# Old block start: section header for N-FIX-2 BACKGROUND MUSIC.
# Old block end: the line BEFORE `const MUSIC_STATES = {`.
# New content: SOUND_LIBRARY, BGM rotation globals, AUDIO-1 section header.
SYNTH_BLOCK_START = "// ─────────────────────────────────────────────\n//  N-FIX-2 — BACKGROUND MUSIC (3-song Trump rally rotation)"
SYNTH_BLOCK_END_BEFORE = "const MUSIC_STATES = {"

start_idx = text.find(SYNTH_BLOCK_START)
end_idx = text.find(SYNTH_BLOCK_END_BEFORE, start_idx)
assert start_idx != -1 and end_idx != -1, "synth block anchors not found"

new_block_1 = """// ─────────────────────────────────────────────
//  AUDIO-1 — HOWLER.JS MUSIC PLAYBACK
// ─────────────────────────────────────────────
// MP3 files in /audio/ replace the synth music scheduling that lived in N-FIX-2 through
// N-FIX-9. Howler handles cross-browser playback (incl. iOS Safari unlock), looping, fade
// in/out, and end-of-track events. The state machine architecture from N-FIX-7 is preserved:
// computeDesiredMusic maps game state → desired music; transitionToMusic owns the swap.
//
// SOUND_LIBRARY keys map MUSIC_STATES values via SOUND_MAP (defined inside transitionToMusic).
// Looping songs (BGM rotation, escalator, Macho Man, YMCA) loop indefinitely; one-shot songs
// (Ave Maria, Nessun Dorma) play to end and stop.
const SOUND_LIBRARY = {
  ymca:         new Howl({ src: ['audio/ymca.mp3'],         loop: true,  volume: 0.7 }),
  macho_man:    new Howl({ src: ['audio/macho_man.mp3'],    loop: true,  volume: 0.7 }),
  greenwood:    new Howl({ src: ['audio/greenwood.mp3'],    loop: true,  volume: 0.6 }),
  queen:        new Howl({ src: ['audio/queen.mp3'],        loop: true,  volume: 0.6 }),
  brown:        new Howl({ src: ['audio/brown.mp3'],        loop: true,  volume: 0.6 }),
  free_world:   new Howl({ src: ['audio/free_world.mp3'],   loop: true,  volume: 0.6 }),
  ave_maria:    new Howl({ src: ['audio/ave_maria.mp3'],    loop: false, volume: 0.7 }),
  nessun_dorma: new Howl({ src: ['audio/nessun_dorma.mp3'], loop: false, volume: 0.7 }),
};
let currentlyPlayingSound = null;

// BGM rotation: 3 songs cycle on song-end. bgmRotationIdx persists across cutscene/death
// transitions so the rotation resumes from where it left off.
const BGM_ROTATION_SONGS = ['greenwood', 'queen', 'brown'];
let bgmRotationIdx = 0;

"""

text = text[:start_idx] + new_block_1 + text[end_idx:]

# ---- 2. Replace MUSIC_STATES enum (add YMCA) ----
OLD_ENUM = """const MUSIC_STATES = {
  SILENT:        'silent',
  ESCALATOR:     'escalator',
  AVE_MARIA:     'aveMaria',
  NESSUN_DORMA:  'nessunDorma',
  MACHO_MAN:     'machoMan',
  BGM_ROTATION:  'bgmRotation',
};"""
NEW_ENUM = """const MUSIC_STATES = {
  SILENT:        'silent',
  ESCALATOR:     'escalator',
  AVE_MARIA:     'aveMaria',
  NESSUN_DORMA:  'nessunDorma',
  MACHO_MAN:     'machoMan',
  YMCA:          'ymca',
  BGM_ROTATION:  'bgmRotation',
};"""
assert OLD_ENUM in text, "MUSIC_STATES enum not found"
text = text.replace(OLD_ENUM, NEW_ENUM, 1)

# ---- 3. Replace computeDesiredMusic ----
# Find the function start, replace whole function.
OLD_COMPUTE = """// Map state → desired music. Single source of truth. tickBGM compares against currentMusic
// and calls transitionToMusic on mismatch.
function computeDesiredMusic() {
  // Cutscenes — Nessun Dorma plays through PHASE3 / SCORE / BETWEEN; silent during the
  // earlier black/dialogue phases. (Spec listed SCORE as silent but the operatic synth
  // tail across SCORE→BETWEEN is what was originally designed; preserving that here.)
  if (state === 'CUTSCENE_PHASE3' || state === 'CUTSCENE_SCORE' || state === 'CUTSCENE_BETWEEN') {
    return MUSIC_STATES.NESSUN_DORMA;
  }
  if (state === 'CUTSCENE_FADE_IN' || state === 'CUTSCENE_PHASE1') {
    return MUSIC_STATES.SILENT;
  }
  // WIN_FREEZE / GAME_OVER / GAMEOVER_PENDING — silent. Death-dance (DEATH_REACTION) — silent.
  if (state === 'WIN_FREEZE' || state === 'GAME_OVER' || state === 'GAMEOVER_PENDING' ||
      state === 'DEATH_REACTION') {
    return MUSIC_STATES.SILENT;
  }
  // Intro chain. ESCALATOR music plays under INTRO_BLACK / INTRO_TITLE / INTRO_ESCALATOR.
  // INTRO_STAIRS swaps to AVE_MARIA. SHATTER and TAUNT are silent (crash SFX dominates).
  if (state === 'INTRO_BLACK' || state === 'INTRO_TITLE' || state === 'INTRO_ESCALATOR') {
    return MUSIC_STATES.ESCALATOR;
  }
  if (state === 'INTRO_STAIRS') {
    return MUSIC_STATES.AVE_MARIA;
  }
  if (state === 'INTRO_SHATTER' || state === 'INTRO_TAUNT') {
    return MUSIC_STATES.SILENT;
  }
  // GAMEPLAY — death-dance keeps BGM silent until the dance ends (bgmDeathMuted gates this).
  // Antifa wave overrides BGM rotation with Macho Man.
  if (state === 'GAMEPLAY') {
    if (bgmDeathMuted) return MUSIC_STATES.SILENT;
    let antifaCount = 0;
    if (typeof helpers !== 'undefined') {
      for (const h of helpers) { if (h.type === 'ANTIFA') { antifaCount++; break; } }
    }
    if (antifaCount > 0) return MUSIC_STATES.MACHO_MAN;
    return MUSIC_STATES.BGM_ROTATION;
  }
  // PAUSED — preserve whatever was playing (no swap during pause).
  if (state === 'PAUSED') {
    return currentMusic;
  }
  return MUSIC_STATES.SILENT;
}"""

NEW_COMPUTE = """// Map state → desired music. Single source of truth. tickBGM compares against currentMusic
// and calls transitionToMusic on mismatch.
function computeDesiredMusic() {
  // AUDIO-1 — death dance plays YMCA whenever the dance is DANCING, regardless of game state.
  // Highest priority (overrides DEATH_REACTION/PENDING/GAMEPLAY/etc.). When dance ends, the
  // normal state-based mapping resumes — restoring BGM_ROTATION on respawn or SILENT on
  // game-over. This single rule replaces the bgmDeathMuted flag from N-FIX-5/6.
  if (typeof dtjDanceState !== 'undefined' && dtjDanceState === 'DANCING') {
    return MUSIC_STATES.YMCA;
  }
  // Cutscenes — Nessun Dorma plays through PHASE3 / SCORE / BETWEEN; silent during the
  // earlier black/dialogue phases.
  if (state === 'CUTSCENE_PHASE3' || state === 'CUTSCENE_SCORE' || state === 'CUTSCENE_BETWEEN') {
    return MUSIC_STATES.NESSUN_DORMA;
  }
  if (state === 'CUTSCENE_FADE_IN' || state === 'CUTSCENE_PHASE1') {
    return MUSIC_STATES.SILENT;
  }
  // WIN_FREEZE / GAME_OVER / GAMEOVER_PENDING — silent (when dance not active; dance is
  // gated above). DEATH_REACTION — silent until dance triggers, then YMCA via the rule above.
  if (state === 'WIN_FREEZE' || state === 'GAME_OVER' || state === 'GAMEOVER_PENDING' ||
      state === 'DEATH_REACTION') {
    return MUSIC_STATES.SILENT;
  }
  // Intro chain. ESCALATOR music plays under INTRO_BLACK / INTRO_TITLE / INTRO_ESCALATOR.
  // INTRO_STAIRS swaps to AVE_MARIA. SHATTER and TAUNT are silent (crash SFX dominates).
  if (state === 'INTRO_BLACK' || state === 'INTRO_TITLE' || state === 'INTRO_ESCALATOR') {
    return MUSIC_STATES.ESCALATOR;
  }
  if (state === 'INTRO_STAIRS') {
    return MUSIC_STATES.AVE_MARIA;
  }
  if (state === 'INTRO_SHATTER' || state === 'INTRO_TAUNT') {
    return MUSIC_STATES.SILENT;
  }
  // GAMEPLAY — Antifa wave overrides BGM rotation with Macho Man.
  if (state === 'GAMEPLAY') {
    let antifaCount = 0;
    if (typeof helpers !== 'undefined') {
      for (const h of helpers) { if (h.type === 'ANTIFA') { antifaCount++; break; } }
    }
    if (antifaCount > 0) return MUSIC_STATES.MACHO_MAN;
    return MUSIC_STATES.BGM_ROTATION;
  }
  // PAUSED — preserve whatever was playing (no swap during pause).
  if (state === 'PAUSED') {
    return currentMusic;
  }
  return MUSIC_STATES.SILENT;
}"""

assert OLD_COMPUTE in text, "computeDesiredMusic not found verbatim"
text = text.replace(OLD_COMPUTE, NEW_COMPUTE, 1)

# ---- 4. Replace transitionToMusic ----
# Find the entire function and surrounding comment block.
OLD_TRANSITION_PATTERN = re.compile(
    r"// Apply the music change\..*?(?=// State-machine-driven scheduler)",
    re.DOTALL,
)
match = OLD_TRANSITION_PATTERN.search(text)
assert match, "transitionToMusic block not found"

NEW_TRANSITION = """// AUDIO-1 — apply the music change. Stops the currently-playing Howl with a 200ms fade-out,
// then plays the new sound at volume 0 and fades it up to its target volume over 200ms.
// SOUND_MAP translates MUSIC_STATES values to SOUND_LIBRARY keys. BGM_ROTATION is special-
// cased to delegate to startBgmRotation, which subscribes to the song's 'end' event so each
// 3-song cycle advances naturally without timers. SILENT just stops the current sound.
function transitionToMusic(newMusic) {
  if (newMusic === currentMusic) return;
  const FADE_MS = 200;
  // Stop current sound with fade.
  if (currentlyPlayingSound && SOUND_LIBRARY[currentlyPlayingSound]) {
    const stopRef = currentlyPlayingSound;
    const sound   = SOUND_LIBRARY[stopRef];
    sound.off('end');                                 // detach any rotation-end handler
    sound.fade(sound.volume(), 0, FADE_MS);
    setTimeout(() => sound.stop(), FADE_MS + 50);
  }
  currentMusic = newMusic;
  currentlyPlayingSound = null;
  if (newMusic === MUSIC_STATES.SILENT) return;
  // BGM_ROTATION delegates to its own helper so the 'end' event chain is set up.
  if (newMusic === MUSIC_STATES.BGM_ROTATION) {
    startBgmRotation();
    return;
  }
  // SOUND_MAP defined inline so it picks up live MUSIC_STATES values.
  const SOUND_MAP = {
    [MUSIC_STATES.ESCALATOR]:    'free_world',
    [MUSIC_STATES.AVE_MARIA]:    'ave_maria',
    [MUSIC_STATES.NESSUN_DORMA]: 'nessun_dorma',
    [MUSIC_STATES.MACHO_MAN]:    'macho_man',
    [MUSIC_STATES.YMCA]:         'ymca',
  };
  const SOUND_DEFAULT_VOLUMES = {
    free_world:   0.6,
    ave_maria:    0.7,
    nessun_dorma: 0.7,
    macho_man:    0.7,
    ymca:         0.7,
  };
  const soundKey = SOUND_MAP[newMusic];
  if (soundKey && SOUND_LIBRARY[soundKey]) {
    const sound = SOUND_LIBRARY[soundKey];
    sound.off('end');
    sound.volume(0);
    sound.play();
    sound.fade(0, SOUND_DEFAULT_VOLUMES[soundKey] || 0.7, FADE_MS);
    currentlyPlayingSound = soundKey;
  }
}

// AUDIO-1 — BGM rotation helper. Plays the current rotation song, subscribes to its 'end'
// event to advance bgmRotationIdx and recurse. Idempotent: re-calling stops any previous
// 'end' handler before subscribing fresh. tickBGM never advances rotation — it's purely
// event-driven on song-end, which means natural song duration determines rotation timing.
function startBgmRotation() {
  const songKey = BGM_ROTATION_SONGS[bgmRotationIdx];
  const sound   = SOUND_LIBRARY[songKey];
  if (!sound) return;
  sound.off('end');                                   // clear any previous handler
  sound.volume(0);
  sound.play();
  sound.fade(0, 0.6, 200);
  currentlyPlayingSound = songKey;
  sound.once('end', () => {
    bgmRotationIdx = (bgmRotationIdx + 1) % BGM_ROTATION_SONGS.length;
    if (currentMusic === MUSIC_STATES.BGM_ROTATION) startBgmRotation();
  });
}

"""

text = text[:match.start()] + NEW_TRANSITION + text[match.end():]

# ---- 5. Replace tickBGM body (simplified — Howler manages context) ----
OLD_TICKBGM_PATTERN = re.compile(
    r"// State-machine-driven scheduler\..*?\nfunction tickBGM\(\) \{.*?\n\}\n",
    re.DOTALL,
)
match = OLD_TICKBGM_PATTERN.search(text)
assert match, "tickBGM block not found"

NEW_TICKBGM = """// AUDIO-1 — state-machine-driven scheduler. Each frame: ask what music SHOULD play, swap
// if needed via transitionToMusic. Howler manages its own audio context internally and
// handles cross-browser unlock; no per-frame note scheduling needed. PAUSED bails so music
// doesn't switch during pause.
function tickBGM() {
  if (state === 'PAUSED') return;
  const desired = computeDesiredMusic();
  if (desired !== currentMusic) {
    transitionToMusic(desired);
  }
}
"""

text = text[:match.start()] + NEW_TICKBGM + text[match.end():]

# ---- 6. Delete trailing synth scheduler functions (MACHO_MAN / cues / duck/unduck/fade) ----
# From `const MACHO_MAN_DUR` through end of `bgmFadeIn` function.
TRAIL_START = "// ─────────────────────────────────────────────\n//  N-FIX-5 — MACHO MAN (Village People) Antifa-wave music"
TRAIL_END_PATTERN = re.compile(
    r"function bgmFadeIn\(durSec, targetLevel\) \{[^}]*\}\n",
    re.DOTALL,
)
trail_start_idx = text.find(TRAIL_START)
assert trail_start_idx != -1, "MACHO MAN section header not found"
trail_match = TRAIL_END_PATTERN.search(text, trail_start_idx)
assert trail_match, "bgmFadeIn end not found"
trail_end_idx = trail_match.end()

# Replace with a brief comment marker.
TRAIL_REPLACEMENT = """// AUDIO-1 — Macho Man synth + intro/cutscene cue functions + duckBGM/unduckBGM/bgmFadeOut/
// bgmFadeIn helpers all DELETED. Howler owns playback and fade timing. The state machine
// (computeDesiredMusic + transitionToMusic) drives swaps from a single per-frame tick.

"""

text = text[:trail_start_idx] + TRAIL_REPLACEMENT + text[trail_end_idx:]

# ---- 7. Delete YMCA synth (playYmcaNote / startYmca / stopYmca) ----
YMCA_SYNTH_PATTERN = re.compile(
    r"// L — YMCA synth\..*?function stopYmca\(\) \{[^}]*\}\n",
    re.DOTALL,
)
match = YMCA_SYNTH_PATTERN.search(text)
assert match, "YMCA synth block not found"

YMCA_REPLACEMENT = """// AUDIO-1 — playYmcaNote / startYmca / stopYmca DELETED. Howler plays audio/ymca.mp3
// during DEATH_REACTION/PENDING when dtjDanceState === 'DANCING' (computeDesiredMusic rule).

"""

text = text[:match.start()] + YMCA_REPLACEMENT + text[match.end():]

# Write back.
SRC.write_text(text, encoding='utf-8', newline='\n')
print(f"AUDIO-1 surgery complete. New file size: {len(text)} chars")
