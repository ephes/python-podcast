#!/usr/bin/env python
"""Verify the persistent custom audio player against the REAL staging site.

Runs the goal's continuous-playback path against
``python-podcast.staging.django-cast.com`` (or any base URL) on the site's
default theme: set a window token, start playback through the visible play
action, store the active <audio> object, navigate via enhanced internal links
(podcast index, another episode, /about/), and assert each hop is same-document
(token survives), keeps the SAME audio object active, and that currentTime
advances while paused === false. The enhanced-nav content swap target is read
from the persistent region (theme-agnostic). Then verify an explicit episode
switch, back/forward, and run axe-core for accessibility.

Standalone script (NOT collected by pytest): talks to a live site, needs no
Django/live_server, prints a JSON result, exits non-zero on failure.

Usage:
    uv run python tests/e2e/staging_persistent_player.py \
        [--base https://python-podcast.staging.django-cast.com] \
        [--episode /show/data-science/]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from playwright.sync_api import sync_playwright

AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
# Benign View Transitions messages emitted by the theme's pagination transition
# fix; pre-existing and unrelated to the player/navigation under test.
IGNORED_ERRORS = ("Transition was skipped",)


def _audio_advancing(page):
    return page.evaluate("""() => {
            const a = window.__castPersistentAudioDebug && window.__castPersistentAudioDebug.getActiveAudio();
            return a ? {t: a.currentTime, paused: a.paused} : null;
        }""")


def _wait_advancing(page, label, results):
    before = _audio_advancing(page)
    t0 = before["t"] if before else -1
    page.wait_for_function(
        "(t0) => { const a = window.__castPersistentAudioDebug.getActiveAudio(); return a && !a.paused && a.currentTime > t0 + 0.2; }",
        arg=t0,
        timeout=12000,
    )
    results.setdefault("advancing", []).append(label)


def _same_audio(page, handle):
    return page.evaluate("(prev) => window.__castPersistentAudioDebug.getActiveAudio() === prev", handle)


def run(base, episode_path, headed=False):
    results = {"base": base, "episode": episode_path, "checks": {}, "errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            # --disable-audio-output: null audio sink so the playback clock
            # advances even if the host's real audio device is wedged.
            args=["--autoplay-policy=no-user-gesture-required", "--disable-audio-output"],
        )
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        console_errors = []

        def _on_console(m):
            if m.type == "error" and not any(s in m.text for s in IGNORED_ERRORS):
                console_errors.append(m.text)
            if "duplicate id" in m.text:
                console_errors.append(m.text)

        page.on("console", _on_console)
        page.on(
            "pageerror",
            lambda e: (
                console_errors.append(f"pageerror: {e}") if not any(s in str(e) for s in IGNORED_ERRORS) else None
            ),
        )

        # --- Episode page (default theme): publish-only + persistent region --
        page.goto(base + episode_path, wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.__castPersistentAudioDebug", timeout=15000)
        results["checks"]["region_present"] = page.locator("#cast-persistent-player").count() == 1
        # Enhanced-nav content swap target is whatever the active theme declares.
        swap = page.get_attribute("#cast-persistent-player", "data-cast-swap-target") or "paging-area"
        content_sel = "#" + swap
        results["swap_target"] = swap
        results["checks"]["no_inbody_player"] = page.locator(f"{content_sel} cast-audio-player").count() == 0
        results["checks"]["play_action_present"] = page.locator("[data-cast-play]").count() >= 1

        episode_title = page.title()
        results["episode_title"] = episode_title
        results["checks"]["episode_title_nonempty"] = bool(episode_title.strip())
        page.evaluate("() => { window.__E2E_TOKEN = 'tok-staging'; }")

        # --- Start playback through the visible action ---------------------
        page.locator("[data-cast-play]").first.click()
        page.wait_for_function("() => window.__castPersistentAudioDebug.hostCount() === 1", timeout=15000)
        page.wait_for_function(
            "() => { const a = window.__castPersistentAudioDebug.getActiveAudio(); return a && a.currentTime > 0.3 && !a.paused; }",
            timeout=15000,
        )
        audio0 = page.evaluate_handle("() => window.__castPersistentAudioDebug.getActiveAudio()")
        results["checks"]["one_audio_after_start"] = (
            page.evaluate("() => window.__castPersistentAudioDebug.audioCount()") == 1
        )

        # --- Enhanced nav to the podcast index -----------------------------
        page.click("a[href='/show/']")
        page.wait_for_url(f"{base}/show/")
        results["checks"]["index_same_document"] = page.evaluate("() => window.__E2E_TOKEN") == "tok-staging"
        results["checks"]["index_same_audio"] = _same_audio(page, audio0)
        # document.title updates on enhanced navigation (read from the response
        # <title>): the index title is non-empty and differs from the episode.
        index_title = page.title()
        results["index_title"] = index_title
        results["checks"]["title_updates_on_nav"] = bool(index_title.strip()) and index_title != episode_title
        # The index's own heading is now inside #paging-area, so enhanced nav
        # actually swaps it in (no stale chrome).
        results["checks"]["index_heading_present"] = page.locator(f"{content_sel} h1").count() >= 1
        _wait_advancing(page, "index", results)

        # Discover another episode from the index. Episode URLs look like
        # /show/<slug>/ (trailing slash, no deeper path); exclude the index, the
        # current episode, and any feed/media link (the manager intentionally
        # full-navigates those, which is verified separately).
        other = page.evaluate(
            """(args) => Array.from(document.querySelectorAll(args.sel + ' a[href^="/show/"]'))
                .map(a => a.getAttribute('href'))
                .find(h => h && h !== args.ep && h !== '/show/' && h.endsWith('/')
                           && !h.includes('feed') && h.split('/').filter(Boolean).length === 2)""",
            {"sel": content_sel, "ep": episode_path},
        )
        results["other_episode"] = other

        # --- Enhanced nav to another episode (still the first audio) -------
        if other:
            page.click(f"a[href='{other}']")
            page.wait_for_url(f"{base}{other}")
            results["checks"]["other_ep_same_audio"] = _same_audio(page, audio0)
            results["checks"]["other_ep_publish_only"] = page.locator(f"{content_sel} cast-audio-player").count() == 0
            _wait_advancing(page, "other episode", results)

            # --- Explicit episode switch: clean replacement ----------------
            switches_before = page.evaluate("() => window.__castPersistentAudioDebug.switchCount")
            page.locator("[data-cast-play]").first.click()
            page.wait_for_function(
                "(prev) => { const a = window.__castPersistentAudioDebug.getActiveAudio(); return a && a !== prev && a.currentTime > 0.3 && !a.paused; }",
                arg=audio0,
                timeout=15000,
            )
            results["checks"]["switch_increments"] = (
                page.evaluate("() => window.__castPersistentAudioDebug.switchCount") == switches_before + 1
            )
            results["checks"]["one_host_after_switch"] = (
                page.evaluate("() => window.__castPersistentAudioDebug.hostCount()") == 1
            )
            results["checks"]["one_audio_after_switch"] = (
                page.evaluate("() => window.__castPersistentAudioDebug.audioCount()") == 1
            )
            audio1 = page.evaluate_handle("() => window.__castPersistentAudioDebug.getActiveAudio()")
        else:
            results["errors"].append("no other episode found on index")
            audio1 = audio0

        # --- Enhanced nav to /about/ (flat page in the pp shell) -----------
        page.click("a[href='/about/']")
        page.wait_for_url(f"{base}/about/")
        results["checks"]["about_same_document"] = page.evaluate("() => window.__E2E_TOKEN") == "tok-staging"
        results["checks"]["about_same_audio"] = _same_audio(page, audio1)
        results["checks"]["about_in_content_shell"] = page.locator(content_sel).count() == 1
        _wait_advancing(page, "about", results)

        # --- Back/forward keeps audio advancing ----------------------------
        # (Don't wait for networkidle: real episode audio streams continuously,
        # so the network never idles. popstate -> manager re-fetch settles fast.)
        page.go_back()
        page.wait_for_url(f"{base}{other if other else episode_path}", timeout=15000)
        page.wait_for_timeout(800)
        try:
            _wait_advancing(page, "go_back", results)
            results["checks"]["audio_survives_history"] = page.evaluate("() => window.__E2E_TOKEN") == "tok-staging"
        except Exception as exc:  # noqa: BLE001
            results["checks"]["audio_survives_history"] = False
            results["errors"].append(f"history: {exc}")
        results["checks"]["scroll_top_after_back"] = page.evaluate("() => window.scrollY") == 0

        # --- Accessibility: axe-core (baseline = 0 violations) -------------
        try:
            page.goto(base + episode_path, wait_until="domcontentloaded")  # clean episode for axe
            page.wait_for_function("() => !!window.__castPersistentAudioDebug", timeout=10000)
            page.add_script_tag(url=AXE_CDN)
            time.sleep(0.5)
            axe = page.evaluate("async () => await axe.run(document, {resultTypes: ['violations']})")
            violations = axe.get("violations", [])
            results["checks"]["axe_violations"] = len(violations)
            results["axe"] = [{"id": v["id"], "impact": v.get("impact"), "nodes": len(v["nodes"])} for v in violations]
        except Exception as exc:  # noqa: BLE001
            results["errors"].append(f"axe: {exc}")

        results["console_errors"] = console_errors
        browser.close()

    failed = [k for k, v in results["checks"].items() if v is False or (k == "axe_violations" and v)]
    if console_errors:
        failed.append("console_errors")
    results["passed"] = not failed
    results["failed_checks"] = failed
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://python-podcast.staging.django-cast.com")
    ap.add_argument("--episode", default="/show/data-science/")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    results = run(args.base.rstrip("/"), args.episode, headed=args.headed)
    print(json.dumps(results, indent=2))
    sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
