#!/usr/bin/env python
"""Staging check: anonymous comment self-editing and deletion.

Drives the REAL staging site (python-podcast.staging.django-cast.com): posts a
comment on an episode, then verifies the session owner can edit it (text updates,
``(edited)`` marker appears) and delete it (the comment is removed) through the
new author-edits UI.

Standalone script (NOT collected by pytest). Prints JSON, exits non-zero on
failure, and writes screenshots next to this file (comment-*.png).

Usage:
    uv run python tests/e2e/staging_comment_edit_check.py \
        [--base https://python-podcast.staging.django-cast.com] [--headed]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).parent
POST_PATH = "/show/platonismus-und-python-data-class-builders/"


def run(base: str, headed: bool = False) -> dict:
    results: dict = {"base": base, "checks": {}, "errors": []}
    checks = results["checks"]
    # Natural, topical text so the site's spam filter classifies it as ham (a
    # moderated/hidden comment is intentionally not editable). The edit must also
    # be ham, because editing re-runs the spam/moderation pipeline.
    token = str(int(time.time()))[-6:]
    posted_text = (
        f"Sehr schoene Folge zu Data Classes, vielen Dank euch beiden! Die "
        f"Erklaerung zum Auto-Sentinel fand ich besonders hilfreich. (qa-{token})"
    )
    edited_text = (
        f"Sehr schoene Folge zu Data Classes, vielen Dank! Nachtrag: die "
        f"Field-Builder-Beispiele waren super. (qa-{token})"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("console", lambda m: results["errors"].append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: results["errors"].append(f"pageerror: {e}"))
        page.on("dialog", lambda d: d.accept())  # auto-accept the delete confirm()

        page.goto(base + POST_PATH, wait_until="networkidle")

        # --- Post a comment -------------------------------------------------
        form = page.locator("form.js-comments-form").first
        form.locator('[name="name"]').fill("Jochen QA")
        form.locator('[name="email"]').fill("qa@wersdoerfer.de")
        form.locator('[name="comment"]').fill(posted_text)
        form.locator('input[name="post"]').click()

        comment = page.locator(".comment-item", has_text=f"qa-{token}").first
        comment.wait_for(state="visible", timeout=20000)
        cid = comment.get_attribute("id")  # e.g. "c123"
        checks["comment_posted"] = bool(cid)

        # The comment must be public (survives the moderation pipeline) AND owned,
        # i.e. it carries the owner controls. If the spam filter hid it there are
        # no controls by design, so this is the real feature signal.
        checks["edit_control_present"] = comment.locator(".comment-edit-link").count() == 1
        checks["delete_control_present"] = comment.locator(".comment-delete-link").count() == 1
        checks["raw_source_present"] = comment.locator("textarea.comment-raw").count() == 1
        page.screenshot(path=str(SHOTS / "comment-1-posted.png"), full_page=False)

        # --- Edit -----------------------------------------------------------
        comment.locator(".comment-edit-link").click()
        editor = comment.locator(".comment-edit-form textarea")
        editor.wait_for(state="visible", timeout=10000)
        checks["editor_prefilled"] = editor.input_value().strip() == posted_text
        editor.fill(edited_text)
        comment.locator(".comment-edit-save").click()

        # Same node id, swapped in place; wait for the new text + (edited) marker.
        page.locator(f"#{cid}", has_text="Nachtrag").wait_for(state="visible", timeout=20000)
        edited = page.locator(f"#{cid}")
        checks["edit_applied"] = edited.locator(":scope", has_text="Nachtrag").count() == 1
        checks["edited_marker_shown"] = edited.locator(".comment-edited-flag").count() == 1
        page.screenshot(path=str(SHOTS / "comment-2-edited.png"), full_page=False)

        # --- Delete ---------------------------------------------------------
        edited.locator(".comment-delete-link").click()
        page.locator(f"#{cid}").wait_for(state="detached", timeout=20000)
        checks["delete_applied"] = page.locator(f"#{cid}").count() == 0
        page.screenshot(path=str(SHOTS / "comment-3-deleted.png"), full_page=False)

        browser.close()

    results["ok"] = all(checks.values()) and not results["errors"]
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://python-podcast.staging.django-cast.com")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    res = run(args.base, args.headed)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)
