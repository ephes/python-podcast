#!/usr/bin/env python
"""Goal check against the REAL staging site: navigation + overview-list player.

Verifies the two goal criteria on python-podcast.staging.django-cast.com:

1. Site navigation works while the persistent dock is open — body padding
   tracks the dock's real height (even with the transcript sheet expanded), the
   bottom pagination sits above the dock, and paginating via htmx keeps the
   audio playing.
2. The overview-list episode player is improved — each list episode renders a
   play card; the active episode's card mirrors global playback state
   (data-cast-state, pause glyph, live elapsed/total readout) and acts as a
   pause/resume proxy.

Standalone script (NOT collected by pytest). Prints JSON, exits non-zero on
failure, and writes screenshots next to this file (staging-goal-*.png).

Usage:
    uv run python tests/e2e/staging_goal_check.py \
        [--base https://python-podcast.staging.django-cast.com]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).parent


def run(base: str, headed: bool = False) -> dict:
    results: dict = {"base": base, "checks": {}, "errors": []}
    checks = results["checks"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=["--disable-audio-output"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on(
            "console",
            lambda m: (
                results["errors"].append(f"{m.type}: {m.text}")
                if m.type == "error" and "Transition was skipped" not in m.text
                else None
            ),
        )
        page.on("pageerror", lambda e: results["errors"].append(f"pageerror: {e}"))

        # --- Overview list: play cards render per episode -------------------
        page.goto(base + "/show/", wait_until="networkidle")
        page.wait_for_function("() => !!window.__castPersistentAudioDebug")
        card_count = page.locator(".cast-play-card[data-cast-episode-payload]").count()
        checks["list_play_cards"] = card_count >= 2
        results["card_count"] = card_count
        page.screenshot(path=str(SHOTS / "staging-goal-1-cards-idle.png"), full_page=False)

        # --- Start an episode from an overview card -------------------------
        first_btn = page.locator("[data-cast-play]").first
        first_payload = first_btn.get_attribute("data-cast-play")
        first_btn.click()
        page.wait_for_function(
            "() => { const a = window.__castPersistentAudioDebug.getActiveAudio();"
            " return a && a.currentTime > 0.3 && !a.paused; }",
            timeout=15000,
        )
        page.wait_for_function(
            "(id) => window.__castPersistentAudioDebug.cardStates()[id] === 'playing'", arg=first_payload
        )
        checks["card_mirrors_playing"] = True
        checks["eq_badge_visible"] = page.locator(
            ".cast-play-card[data-cast-state='playing'] .cast-play-card__eq"
        ).first.is_visible()
        page.wait_for_function(
            '() => { const el = document.querySelector(".cast-play-card[data-cast-state] .cast-play-card__time");'
            " return el && !el.hidden && /\\d/.test(el.textContent); }"
        )
        checks["live_time_readout"] = True
        only_one_active = page.evaluate(
            "() => Object.values(window.__castPersistentAudioDebug.cardStates())"
            ".filter((v) => v !== null).length === 1"
        )
        checks["only_active_card_mirrors"] = only_one_active
        page.screenshot(path=str(SHOTS / "staging-goal-2-card-playing.png"), full_page=False)

        # --- Card acts as pause/resume proxy ---------------------------------
        audio = page.evaluate_handle("() => window.__castPersistentAudioDebug.getActiveAudio()")
        page.locator(".cast-play-card[data-cast-state] [data-cast-play]").first.click()
        page.wait_for_function("() => window.__castPersistentAudioDebug.getActiveAudio().paused")
        # The card attribute follows the async `pause` event — wait, don't sample.
        page.wait_for_function(
            "(id) => window.__castPersistentAudioDebug.cardStates()[id] === 'paused'", arg=first_payload
        )
        checks["card_pause_proxy"] = page.evaluate(
            "(prev) => window.__castPersistentAudioDebug.getActiveAudio() === prev", audio
        )
        page.locator(".cast-play-card[data-cast-state] [data-cast-play]").first.click()
        page.wait_for_function("() => !window.__castPersistentAudioDebug.getActiveAudio().paused")
        checks["card_resume_proxy"] = True

        # --- Reservation: body padding tracks the dock height ----------------
        checks["dock_height_reserved"] = page.evaluate(
            "() => { const inner = document.querySelector('.cast-dock__inner');"
            " const pad = parseFloat(getComputedStyle(document.body).paddingBottom);"
            " return !!inner && pad >= inner.getBoundingClientRect().height; }"
        )

        # --- Open transcript sheet: reservation grows, pagination clear ------
        pad_before = page.evaluate("() => parseFloat(getComputedStyle(document.body).paddingBottom)")
        page.locator("#cast-persistent-player cast-transcript .cast-panel__toggle").click()
        page.wait_for_selector("#cast-persistent-player .cast-transcript__cue")
        page.wait_for_function(
            "(p0) => parseFloat(getComputedStyle(document.body).paddingBottom) > p0 + 40", arg=pad_before
        )
        checks["reservation_grows_with_sheet"] = True
        page.evaluate(
            "() => window.scrollTo({ top: document.documentElement.scrollHeight, left: 0, behavior: 'instant' })"
        )
        page.wait_for_function("() => window.scrollY > 0")
        geometry = page.evaluate(
            "() => { const links = Array.from(document.querySelectorAll('a[href*=\"?page=\"]'));"
            " const last = links[links.length - 1];"
            " const dock = document.querySelector('.cast-dock__inner');"
            " if (!last || !dock) return { ok: false, links: links.length };"
            " const lr = last.getBoundingClientRect(); const dr = dock.getBoundingClientRect();"
            " return { ok: lr.bottom <= dr.top + 1, linkBottom: lr.bottom, dockTop: dr.top }; }"
        )
        checks["pagination_above_dock"] = geometry.get("ok") is True
        results["geometry"] = geometry
        page.screenshot(path=str(SHOTS / "staging-goal-3-sheet-open-pagination.png"), full_page=False)

        # --- Minimize: one-row strip, space shrinks, audio keeps playing -----
        pad_expanded = page.evaluate("() => parseFloat(getComputedStyle(document.body).paddingBottom)")
        page.locator(".cast-dock__minify").click()
        page.wait_for_function("() => window.__castPersistentAudioDebug.isMinimized()")
        checks["minimize_hides_panels"] = page.locator("#cast-persistent-player cast-transcript").is_hidden()
        page.wait_for_function(
            "(p0) => parseFloat(getComputedStyle(document.body).paddingBottom) < p0 - 40", arg=pad_expanded
        )
        checks["minimize_shrinks_reservation"] = True
        checks["minimize_keeps_audio"] = page.evaluate(
            "(prev) => { const a = window.__castPersistentAudioDebug.getActiveAudio();"
            " return a === prev && !a.paused; }",
            audio,
        )
        page.screenshot(path=str(SHOTS / "staging-goal-5-minimized.png"), full_page=False)
        page.locator(".cast-dock__minify").click()
        page.wait_for_function("() => !window.__castPersistentAudioDebug.isMinimized()")
        checks["restore_preserves_sheet"] = page.locator(
            "#cast-persistent-player .cast-transcript__cue"
        ).first.is_visible()

        # --- Paginate while playing: audio survives, state re-applies --------
        page.locator('a[href$="?page=2"]').last.click()
        page.wait_for_url("**page=2**")
        page.wait_for_function(
            "() => { const a = window.__castPersistentAudioDebug.getActiveAudio(); return a && !a.paused; }"
        )
        checks["pagination_keeps_audio"] = page.evaluate(
            "(prev) => window.__castPersistentAudioDebug.getActiveAudio() === prev", audio
        )
        page.locator('a[href$="?page=1"]').last.click()
        page.wait_for_function(
            "(id) => window.__castPersistentAudioDebug.cardStates()[id] === 'playing'", arg=first_payload
        )
        checks["state_reapplied_after_swap"] = True

        # --- Episode detail card also mirrors --------------------------------
        detail_href = page.evaluate(
            '() => { const card = document.querySelector(".cast-play-card[data-cast-state]");'
            " const article = card && card.closest('article, .card, li, section, div');"
            " const a = article && article.querySelector('a[href*=\"/show/\"]');"
            " return a ? a.getAttribute('href') : null; }"
        )
        if detail_href:
            page.click(f'a[href="{detail_href}"]')
            page.wait_for_function(
                "(id) => window.__castPersistentAudioDebug.cardStates()[id] === 'playing'", arg=first_payload
            )
            checks["detail_card_mirrors_after_nav"] = True
            page.screenshot(path=str(SHOTS / "staging-goal-4-detail-card-playing.png"), full_page=False)

        # --- The originally broken episode (Tag 1) now has a transcript ------
        page.goto(base + "/show/live-von-der-djangocon-europe-2025-in-dublin-tag-1/", wait_until="networkidle")
        page.wait_for_function("() => !!window.__castPersistentAudioDebug")
        page.locator("[data-cast-play]").first.click()
        page.wait_for_function(
            "() => { const a = window.__castPersistentAudioDebug.getActiveAudio();"
            " return a && a.currentTime > 0.3 && !a.paused; }",
            timeout=15000,
        )
        page.locator("#cast-persistent-player cast-transcript .cast-panel__toggle").click()
        page.wait_for_selector("#cast-persistent-player .cast-transcript__cue", timeout=15000)
        tag1_cues = page.locator("#cast-persistent-player .cast-transcript__cue").count()
        checks["tag1_transcript_has_cues"] = tag1_cues > 100
        results["tag1_cues"] = tag1_cues
        page.screenshot(path=str(SHOTS / "staging-goal-6-tag1-transcript.png"), full_page=False)

        browser.close()

    results["passed"] = all(v is True for v in checks.values()) and not results["errors"]
    results["failed_checks"] = [k for k, v in checks.items() if v is not True]
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://python-podcast.staging.django-cast.com")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    res = run(args.base.rstrip("/"), headed=args.headed)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["passed"] else 1)
