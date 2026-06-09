"""Browser-level verification of the django-cast custom audio player.

Runs against the local editable django-cast + cast-bootstrap5 with
CAST_AUDIO_PLAYER="custom" (config.settings.e2e). Uses deterministic local
fixture data: an episode with a real synthesized MP3, an inline transcript, and
chapters. Verifies play/playback, transcript active-cue change + auto-scroll,
range seeking, and transcript/chapter highlight updates in a real browser.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from playwright.sync_api import expect

NUM_CUES = 12
CLIP_SECONDS = 12


def _synth_audio(ext: str, codec: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"clip.{ext}"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=330:duration={CLIP_SECONDS}",
                "-c:a",
                codec,
                str(out),
            ],
            check=True,
        )
        return out.read_bytes()


@pytest.fixture
def episode_path(live_server, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    from _helpers import ensure_site
    from cast.devdata import create_episode, create_podcast
    from cast.models import Audio
    from cast.models.audio import ChapterMark
    from django.contrib.auth import get_user_model
    from wagtail.models import Collection

    user = get_user_model().objects.create_user("e2e-user", password="password")
    site = ensure_site()  # robust against the live_server transactional flush
    root_collection = Collection.get_first_root_node() or Collection.add_root(name="Root")

    # Both formats are real synthesized 12s clips so the browser can play either
    # source to completion (m4a is listed first; mp3 is the fallback).
    audio = Audio(
        user=user,
        title="E2E Episode Audio",
        collection=root_collection,
        mp3=SimpleUploadedFile("clip.mp3", _synth_audio("mp3", "libmp3lame"), content_type="audio/mpeg"),
        m4a=SimpleUploadedFile("clip.m4a", _synth_audio("m4a", "aac"), content_type="audio/mp4"),
    )
    audio.save()  # computes duration via ffprobe

    # Inline transcript: NUM_CUES one-second cues with distinct text.
    cues = [
        {
            "start_ms": i * 1000,
            "end_ms": (i + 1) * 1000,
            "text": f"This is transcript cue number {i}.",
        }
        for i in range(NUM_CUES)
    ]
    from cast.devdata import create_transcript

    create_transcript(audio=audio, podlove={"transcripts": cues})

    ChapterMark.objects.create(audio=audio, start="00:00:00.000", title="Chapter One")
    ChapterMark.objects.create(audio=audio, start="00:00:06.000", title="Chapter Two")

    podcast = create_podcast(owner=user, site=site)
    body = [
        {"type": "overview", "value": [{"type": "audio", "value": audio.id}]},
        {"type": "detail", "value": [{"type": "heading", "value": "detail heading"}]},
    ]
    episode = create_episode(blog=podcast, podcast_audio=audio, body=json.dumps(body))
    episode.live = True
    episode.save()
    episode.save_revision().publish()

    return episode.url


def _current_time(page):
    return page.evaluate("() => document.querySelector('cast-audio-player audio').currentTime")


@pytest.mark.e2e
def test_custom_player_in_browser(page, live_server, episode_path):
    errors = []
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    # Verify on every selectable server-rendered theme so custom-mode asset
    # gating is covered for each (one episode, navigated twice — no DB flush).
    for theme in ("bootstrap5", "pp"):
        _verify_player(page, f"{live_server.url}{episode_path}?theme={theme}", theme)
    assert errors == []


def _verify_player(page, url, theme):
    page.goto(url)

    # The custom player asset is the one included (not Podlove) and it upgrades.
    assert page.locator("script[src*=customPlayer]").count() == 1
    assert page.locator("script[src*=podlovePlayer]").count() == 0
    assert page.evaluate("() => !!customElements.get('cast-audio-player')")

    player = page.locator("cast-audio-player")
    expect(player).to_be_visible()
    play_button = page.locator(".cast-player__play")
    expect(play_button).to_be_visible()

    # Shrink the transcript scroll container so auto-scroll is observable
    # (only ~1 cue fits, so any later active cue must scroll into view).
    page.add_style_tag(content=".cast-transcript__cues { max-height: 36px !important; overflow-y: auto !important; }")

    # The transcript starts folded on load (shipped revision-4 behavior) and is
    # fetched lazily, so open it before asserting the rendered cues.
    page.locator("cast-transcript .cast-panel__toggle").click()

    # Transcript and chapters rendered from the controller.
    cues = page.locator(".cast-transcript__cue")
    expect(cues).to_have_count(NUM_CUES)
    chapters = page.locator(".cast-chapters__button")
    expect(chapters).to_have_count(2)

    # --- Play: verify playback time advances and the label flips ---
    expect(play_button).to_have_attribute("aria-label", "Play")
    play_button.click()
    expect(play_button).to_have_attribute("aria-label", "Pause")
    page.wait_for_function(
        "() => document.querySelector('cast-audio-player audio').currentTime > 0.3",
        timeout=8000,
    )
    assert _current_time(page) > 0.3

    # --- Active transcript cue advances and scrolls into view during playback ---
    # Wait until the active cue is no longer the first one.
    page.wait_for_function(
        """() => {
            const active = document.querySelector('.cast-transcript__cue[aria-current="true"]');
            return active && Number(active.dataset.start) >= 3;
        }""",
        timeout=10000,
    )
    # active cue is scrolled into view (visible within the constrained container)
    page.wait_for_function(
        """() => {
            const c = document.querySelector('.cast-transcript__cues');
            const a = document.querySelector('.cast-transcript__cue[aria-current="true"]');
            if (!c || !a) return false;
            const cr = c.getBoundingClientRect(), ar = a.getBoundingClientRect();
            return ar.bottom <= cr.bottom + 1 && ar.top >= cr.top - 1;
        }""",
        timeout=4000,
    )

    page.locator(".cast-player__play").click()  # pause for deterministic seeking
    expect(play_button).to_have_attribute("aria-label", "Play")

    # --- Seek via the range and verify transcript + chapter highlight update ---
    def seek(seconds):
        page.locator(".cast-player__seek").evaluate(
            "(el, v) => { el.value = String(v); el.dispatchEvent(new Event('input', {bubbles:true})); }",
            seconds,
        )

    seek(2)
    active = page.locator('.cast-transcript__cue[aria-current="true"]')
    expect(active).to_have_attribute("data-start", "2")
    # chapter one (start 0) is current at t=2
    expect(chapters.nth(0)).to_have_attribute("aria-current", "true")

    seek(7)
    expect(page.locator('.cast-transcript__cue[aria-current="true"]')).to_have_attribute("data-start", "7")
    # chapter two (start 6) is current at t=7
    expect(chapters.nth(1)).to_have_attribute("aria-current", "true")

    # --- Seek near the end scrolls the active cue into view ---
    seek(11)
    expect(page.locator('.cast-transcript__cue[aria-current="true"]')).to_have_attribute("data-start", "11")
    scroll_top_end = page.evaluate("() => document.querySelector('.cast-transcript__cues').scrollTop")
    assert scroll_top_end > 0

    page.screenshot(path=f"tests/e2e/custom-player-{theme}.png")
