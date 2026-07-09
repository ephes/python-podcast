"""Unit coverage for the persistent-audio-player flag plumbing.

The browser-level proof lives in tests/e2e/test_persistent_player.py; these are
cheap checks that the staging flag reaches templates and that the audio-block
override publishes a payload + inert action (not an in-body live player) when on.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.template import Context, Template
from django.test import override_settings

from python_podcast.pp.context_processors import persistent_audio_player
from python_podcast.pp.templatetags.pp_persistent_player import (
    CARD_POSTER_RENDITION_SPEC,
    cast_player_payload,
)


@override_settings(PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER=True)
def test_context_processor_enabled():
    assert persistent_audio_player(None)["persistent_audio_player"] is True


@override_settings(PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER=False)
def test_context_processor_disabled():
    assert persistent_audio_player(None)["persistent_audio_player"] is False


def test_context_processor_defaults_off_when_unset(settings):
    # Production never sets the flag; a missing setting must read as disabled.
    if hasattr(settings, "PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER"):
        del settings.PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER
    assert persistent_audio_player(None)["persistent_audio_player"] is False


def test_context_processor_exposes_session_base_template():
    # Flat TemplateView pages extend this so they follow the active theme.
    assert persistent_audio_player(None)["cast_session_base_template"].startswith("cast/")
    assert persistent_audio_player(None)["cast_session_base_template"].endswith("/base.html")


@override_settings(PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER=True)
def test_templatetag_enabled():
    out = Template("{% load pp_persistent_player %}{% pp_persistent_player_enabled as f %}{{ f }}").render(Context())
    assert out == "True"


@override_settings(PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER=False)
def test_templatetag_disabled():
    out = Template("{% load pp_persistent_player %}{% pp_persistent_player_enabled as f %}{{ f }}").render(Context())
    assert out == "False"


def test_player_payload_uses_small_rendition_for_initial_card():
    class CoverImage:
        def get_rendition(self, spec):
            assert spec == CARD_POSTER_RENDITION_SPEC
            return SimpleNamespace(url="/media/cover.max-128x128.webp")

    post = SimpleNamespace(content_type_id=1, cover_image=CoverImage(), blog=None)
    post.specific = post
    request = SimpleNamespace(build_absolute_uri=lambda url: f"https://testserver{url}")
    audio = SimpleNamespace(pk=7)
    player_payload = {
        "title": "Episode Alpha",
        "duration": 3600,
        "poster": "https://media.example/cover.max-512x512.webp",
    }

    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        return_value=player_payload,
    ):
        payload = cast_player_payload({"request": request}, audio, post)

    assert payload["poster"] == player_payload["poster"]
    assert payload["card_poster"] == "https://testserver/media/cover.max-128x128.webp"
    assert payload["duration_display"] == "1 h"


def test_persistent_play_action_partial_renders_payload_and_inert_action():
    """The shared play-action partial emits the payload + an inert action.

    (The full publish-vs-live decision per theme is exercised end-to-end with
    real audio in tests/e2e/test_persistent_player.py.)
    """
    from django.template.loader import render_to_string

    html = render_to_string(
        "cast/_persistent_play_action.html",
        {
            "payload": {
                "player_script": '<script id="cast-player-data-7" type="application/json">{}</script>',
                "player_id": "cast-player-7",
                "payload_id": "cast-player-data-7",
                "title": "Episode Alpha",
                "poster": "https://media.example/cover.max-512x512.webp",
                "card_poster": "https://media.example/cover.max-128x128.webp",
            },
            "label": "Play this episode",
        },
    )
    assert 'data-cast-play="cast-player-data-7"' in html  # inert action references the payload
    assert "cast-player-data-7" in html  # payload published (json_script id)
    # The card carries the state-mirror hooks the manager writes to.
    assert 'data-cast-idle-label="Play this episode"' in html
    assert "cast-play-card__icon--pause" in html  # pause glyph for the now-playing proxy
    assert "cast-play-card__time" in html  # live elapsed/total readout slot
    assert "Play this episode" in html
    assert 'src="https://media.example/cover.max-128x128.webp"' in html
    assert 'width="128" height="128"' in html
    assert "cover.max-512x512.webp" not in html
    assert "<cast-audio-player" not in html  # no in-body live player
    assert "<cast-transcript" not in html
