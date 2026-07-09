"""Verify the *beautified* persistent player is live on real staging.

Companion to ``staging_persistent_player.py`` (which proves continuous playback).
This script proves the visual beautification is actually deployed and applied on
``python-podcast.staging.django-cast.com``:

- the staging-gated ``persistent-player.css`` is served and linked;
- episode pages/cards render the episode *play card* (poster + labelled pill);
- starting an episode builds a docked player that is **lifted out of document
  flow** — ``position: fixed`` pinned to the bottom (the fix for "the player
  renders below the pagination") — with the dock chrome (poster, title, close)
  and the live transport;
- the one-host invariant still holds and the console is clean.

Run against staging (writes screenshots + a JSON evidence blob to --out)::

    DJANGO_SETTINGS_MODULE= uv run python tests/e2e/staging_beautification.py \
        [--base https://python-podcast.staging.django-cast.com] [--out /tmp/staging-shots]

Exit code is 0 only if every assertion passes; non-zero on the first failure.
It is intentionally NOT collected by pytest (no test_ name, needs the network).
"""

import argparse
import json
import pathlib
import sys
import urllib.request

from playwright.sync_api import sync_playwright

REGION = "#cast-persistent-player"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://python-podcast.staging.django-cast.com")
    ap.add_argument("--out", default="/tmp/staging-shots")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ev: dict = {"base": base}
    failures: list[str] = []

    def check(name: str, ok: bool, detail=None) -> None:
        ev[name] = detail if detail is not None else ok
        if not ok:
            failures.append(f"{name} (got {detail!r})")

    # 1) The staging-gated CSS is served and contains the beautification rules.
    try:
        with urllib.request.urlopen(base + "/static/css/persistent-player.min.css", timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        check("css_status", r.status == 200, r.status)
        check("css_fixed_dock", ".cast-persistent" in body and "position: fixed" in body)
        check("css_play_card", ".cast-play-card" in body)
    except Exception as e:  # noqa: BLE001
        check("css_fetch", False, repr(e))

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 860}, device_scale_factor=2)
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        pg.goto(base, wait_until="networkidle")
        check("manager_loaded", pg.evaluate("() => !!window.__castPersistentAudioDebug"))
        check(
            "css_linked",
            pg.evaluate("() => !!document.querySelector('link[href*=\"persistent-player\"]')"),
        )
        check("play_cards", pg.locator(".cast-play-card").count() > 0, pg.locator(".cast-play-card").count())
        pg.wait_for_selector("[data-cast-play]", timeout=15000)
        pg.screenshot(path=str(out / "staging-idle.png"))

        # 2) Start an episode -> the docked player.
        pg.locator("[data-cast-play]").first.click()
        pg.wait_for_function(
            "() => window.__castPersistentAudioDebug && window.__castPersistentAudioDebug.hostCount() === 1",
            timeout=15000,
        )
        pg.wait_for_timeout(900)

        def q(expr):
            return pg.evaluate(expr)

        check(
            "dock_position_fixed",
            q(f"() => getComputedStyle(document.querySelector('{REGION}')).position") == "fixed",
            q(f"() => getComputedStyle(document.querySelector('{REGION}')).position"),
        )
        check(
            "dock_bottom_0",
            q(f"() => getComputedStyle(document.querySelector('{REGION}')).bottom") == "0px",
            q(f"() => getComputedStyle(document.querySelector('{REGION}')).bottom"),
        )
        check("dock_inner", q(f"() => !!document.querySelector('{REGION} .cast-dock__inner')"))
        check("dock_poster", q(f"() => !!document.querySelector('{REGION} .cast-dock__poster')"))
        check("dock_close", q(f"() => !!document.querySelector('{REGION} .cast-dock__close')"))
        check("dock_transport", q(f"() => !!document.querySelector('{REGION} .cast-player__transport')"))
        title_text = q(
            f"() => {{ const t=document.querySelector('{REGION} .cast-dock__title');"
            " return t ? t.textContent.trim() : ''; }"
        )
        check("dock_title", len(title_text) > 0, title_text[:60])
        check(
            "host_count_1",
            q("() => window.__castPersistentAudioDebug.hostCount()") == 1,
            q("() => window.__castPersistentAudioDebug.hostCount()"),
        )
        check(
            "audio_count_1",
            q("() => window.__castPersistentAudioDebug.audioCount()") == 1,
            q("() => window.__castPersistentAudioDebug.audioCount()"),
        )
        check("body_dock_open", q("() => document.body.classList.contains('cast-dock-open')"))
        pg.screenshot(path=str(out / "staging-dock.png"))

        check("no_console_errors", len(errors) == 0, errors)
        b.close()

    ev["failures"] = failures
    (out / "staging-beautification-evidence.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print(json.dumps(ev, indent=2, ensure_ascii=False))
    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\nPASS: beautified persistent player verified live on staging.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
