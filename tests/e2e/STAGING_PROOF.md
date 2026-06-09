# Persistent Audio Player — Staging Proof (completion evidence)

Goal: prove on `python-podcast.staging.django-cast.com` that the custom audio
player keeps playing across internal navigation, behind a staging-only flag,
with production unchanged. Spec/PRD: django-cast
`backlog/2026-06-08-persistent-player-staging.md`. Now extended to the
**bootstrap5** theme (the site's default) with **per-episode play actions on the
overview**.

## What was built (python-podcast only; django-cast & cast-bootstrap5 unchanged)

- `PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER` flag: ON in `staging.py`/`local.py`/
  `e2e.py`, **pinned False in `production.py`**.
- Works on **both** server-rendered themes, gated on custom-player mode:
  - **bootstrap5** (staging default): persistent region in `cast/bootstrap5/base.html`
    (`{% block modal %}`, outside `#main-content`); enhanced-nav swap target
    `main-content`. The index identity (`h1` + description) is rendered inside
    `#main-content` in persistent mode so it swaps too.
  - **pp**: persistent region outside `#paging-area`; swap target `paging-area`.
- The single live `<cast-audio-player>` lives OUTSIDE the swap boundary. Episode
  detail pages AND **overview/list cards** publish a sanitized `json_script`
  payload + an inert play action (`cast/<theme>/audio.html` + the
  `cast_player_payload` tag + the shared `cast/_persistent_play_action.html`),
  so any episode can be started from the overview.
- `persistent-player.js` (dependency-free): keeps one player alive across
  enhanced navigation, discovers each page's/card's payload, switches episodes
  only on an explicit play, progressively enhances internal links (excluding
  external/download/non-HTTP/`#fragment`/feed/media/admin/account/api/comments/
  forms/existing-htmx), updates `document.title`, scrolls to top, moves focus to
  the first visible `h1` in the swap target (else the target), and re-fetches on
  back/forward (region untouched, so audio keeps advancing). The swap-target id
  is read from the region's `data-cast-swap-target` (theme-agnostic). Diagnostics
  on `window.__castPersistentAudioDebug`.

## Evidence (all green)

- **Real staging Playwright** (`staging_persistent_player.py` on the default
  bootstrap5 theme, all checks pass): publish-only episode pages; start through
  the visible action → one host/`<audio>`; enhanced nav to index → another
  episode → `/about/` keeps the SAME `<audio>` object active in the SAME document
  with `currentTime` advancing and `paused === false`; explicit switch is clean
  (switch +1, one host, one `<audio>`); `document.title` updates; the index `h1`
  is present inside the swap region; back keeps audio advancing with scroll-top;
  **axe-core 0 violations**; **0 console errors**. The overview shows a play
  action per episode.
- **Local staging-equivalent e2e** (`test_persistent_player.py`,
  parametrized over **pp + bootstrap5**, 2 tests each) + unit
  (`test_persistent_player_config.py`): pass. Transcript/chapter panels work on
  the active player and are not refetched by navigation. e2e default-excluded
  from `pytest`; run via `just test-e2e`.
- **django-cast `just check`**: pass (lint + typecheck + tests, 100% coverage).
- **Deploy hygiene**: `pyproject`/`uv.lock` pin django-cast/cast-bootstrap5;
  production keeps the flag off.

## Staging defaults

On staging the `show` blog + site `TemplateBaseDirectory` are set to `bootstrap5`
(reversible staging-DB settings) so the persistent player is the default visit
experience. Production is a separate site/DB, unaffected.

## Beautification verified live on staging (2026-06-10)

The persistent player was beautified (commit *"Persistent player: beautiful
fixed bottom dock, play card, and view-transition morph"*) and **deployed to
staging** via `just deploy-staging` (Ansible rsync of the working tree +
`collectstatic`; `staging: ok=117 changed=8 failed=0`). The change is python-podcast
only and stays gated behind `PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER`; production
(Podlove, flag pinned `False`) is untouched.

`tests/e2e/staging_beautification.py` re-runs against the real site and asserts
the beautification is genuinely live; the recorded run against
`https://python-podcast.staging.django-cast.com` (2026-06-10) passed every check:

```json
{
  "css_status": 200, "css_fixed_dock": true, "css_play_card": true,
  "manager_loaded": true, "css_linked": true, "play_cards": 5,
  "dock_position_fixed": "fixed", "dock_bottom_0": "0px",
  "dock_inner": true, "dock_poster": true, "dock_close": true,
  "dock_transport": true, "dock_title": "Data Science",
  "host_count_1": 1, "audio_count_1": 1, "body_dock_open": true,
  "no_console_errors": [], "failures": []
}
```

Key facts proven on the live site: the staging-gated `persistent-player.css` is
served (200) and linked; episode cards render the play card; starting an episode
builds a dock that is `position: fixed` pinned to `bottom: 0` (lifted out of flow
— no longer "below the pagination") with poster/title/close + the live transport;
the one-host invariant holds (`hostCount === 1`, `audioCount === 1`) and the
console is error-free. Screenshots: `staging-idle.png`, `staging-dock.png`.

## Known, accepted-out-of-scope item

The `[tool.uv.sources]` refs (`cast-bootstrap5` → `feat/custom-player-rev4`,
`django-cast` → `develop`) are shared by staging + production installs and
predate this work. Production behaviour is unchanged (Podlove,
`CAST_AUDIO_PLAYER != "custom"`, persistent flag pinned `False`). A production
rollout must revert these to release/main refs first — tracked in the django-cast
follow-ups note. Not a defect of this slice.
