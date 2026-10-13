"""Unit coverage for the persistent-audio-player flag plumbing.

The browser-level proof lives in tests/e2e/test_persistent_player.py; these are
cheap checks that the staging flag reaches templates and that the audio-block
override publishes a payload + inert action (not an in-body live player) when on.
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.template import Context, Template
from django.test import override_settings
from wagtail.images.models import SourceImageIOError

from python_podcast.pp.context_processors import persistent_audio_player
from python_podcast.pp.templatetags.pp_persistent_player import (
    CARD_POSTER_RENDITION_SPEC,
    cast_player_payload,
    pp_vite_asset_deferred_css,
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


def test_vite_player_stylesheet_is_non_render_blocking():
    vite_html = (
        '<link rel="stylesheet" href="/static/custom-player.css">\n'
        '<script type="module" src="/static/custom-player.js"></script>'
    )
    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.DjangoViteAssetLoader.instance"
    ) as loader_instance:
        loader_instance.return_value.generate_vite_asset.return_value = vite_html
        html = pp_vite_asset_deferred_css("src/audio/custom-player.ts", "cast")

    assert 'media="print"' in html
    assert "onload=\"this.media='all'\"" in html
    assert '<script type="module" src="/static/custom-player.js"></script>' in html


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


def _post(pk, **kwargs):
    post = SimpleNamespace(pk=pk, content_type_id=1, cover_image=None, blog=None, **kwargs)
    post.specific = post
    return post


@pytest.mark.parametrize("use_blog_cover", [False, True])
@pytest.mark.parametrize("error", [FileNotFoundError, SourceImageIOError])
def test_player_card_uses_cached_poster_when_original_is_missing(use_blog_cover, error):
    from django.template.loader import render_to_string

    class CoverImage:
        def get_rendition(self, spec):
            assert spec == CARD_POSTER_RENDITION_SPEC
            raise error("original cover is missing")

    post = _post(11)
    if use_blog_cover:
        post.blog = SimpleNamespace(cover_image=CoverImage())
    else:
        post.cover_image = CoverImage()
    poster = "https://media.example/cover.max-512x512.webp"
    request = SimpleNamespace(build_absolute_uri=lambda url: pytest.fail("fallback is already absolute"))
    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        return_value={"title": "Episode Alpha", "poster": poster},
    ):
        payload = cast_player_payload({"request": request}, SimpleNamespace(pk=7), post)
    html = render_to_string("cast/_persistent_play_action.html", {"payload": payload})

    assert payload["poster"] == payload["card_poster"] == poster
    assert f'src="{poster}"' in html
    assert json.loads(re.search(r"<script[^>]*>(.*?)</script>", html).group(1))["poster"] == poster


def test_player_card_does_not_hide_unexpected_rendition_errors():
    post = _post(11)
    post.cover_image = SimpleNamespace(get_rendition=Mock(side_effect=RuntimeError("unexpected")))
    with (
        patch(
            "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
            return_value={"poster": "https://media.example/cover.webp"},
        ),
        pytest.raises(RuntimeError, match="unexpected"),
    ):
        cast_player_payload({}, SimpleNamespace(pk=7), post)


def _fake_payload(audio, post=None, request=None):
    # Like django-cast, the title comes from the audio; the poster depends on the post.
    poster = f"https://media.example/post-{post.pk}.webp" if getattr(post, "pk", None) else ""
    return {"title": "Shared Audio", "duration": 60, "poster": poster}


def _render_cards(audio, posts):
    from django.template.loader import render_to_string

    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        side_effect=_fake_payload,
    ):
        payloads = [cast_player_payload({}, audio, post) for post in posts]
    html = "".join(render_to_string("cast/_persistent_play_action.html", {"payload": payload}) for payload in payloads)
    return payloads, html


def test_posts_sharing_one_audio_publish_distinct_payloads():
    """Two overview cards for different posts must not share a payload id.

    persistent-player.js resolves a play action with getElementById, so a shared
    id made the second card load the first post's poster and transcript link.
    """
    audio = SimpleNamespace(pk=7)
    payloads, html = _render_cards(audio, [_post(11, title="Episode Alpha"), _post(12, title="Episode Beta")])

    assert [payload["payload_id"] for payload in payloads] == [
        "cast-player-data-7-post-11",
        "cast-player-data-7-post-12",
    ]
    assert [payload["player_id"] for payload in payloads] == ["cast-player-7-post-11", "cast-player-7-post-12"]
    script_ids = re.findall(r'<script id="([^"]+)" type="application/json">', html)
    assert script_ids == ["cast-player-data-7-post-11", "cast-player-data-7-post-12"]
    for payload, post_pk in zip(payloads, [11, 12]):
        script = re.search(rf'<script id="{payload["payload_id"]}" type="application/json">(.*?)</script>', html)
        assert json.loads(script.group(1))["poster"] == f"https://media.example/post-{post_pk}.webp"
        # Every hook of one card names that card's own payload.
        assert html.count(f'data-cast-play="{payload["payload_id"]}"') == 1
        assert html.count(f'data-cast-episode-payload="{payload["payload_id"]}"') == 1
        assert html.count(f'data-cast-player-id="{payload["player_id"]}"') == 1


def test_same_post_keeps_one_payload_id_on_detail_page_and_list_card():
    audio = SimpleNamespace(pk=7)
    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        side_effect=_fake_payload,
    ):
        detail = cast_player_payload({}, audio, _post(11, title="Episode Alpha"))
        with patch("wagtail.models.Page.objects") as page_objects:
            # Cached overview repositories hand out a lightweight post without a content type.
            page_objects.get.return_value.specific = _post(11, title="Episode Alpha")
            card = cast_player_payload({}, audio, SimpleNamespace(pk=11, content_type_id=None))

    page_objects.get.assert_called_once_with(pk=11)
    assert detail["payload_id"] == card["payload_id"] == "cast-player-data-7-post-11"
    assert detail["player_id"] == card["player_id"] == "cast-player-7-post-11"
    assert card["poster"] == detail["poster"] == "https://media.example/post-11.webp"


@pytest.mark.parametrize("post", [None, SimpleNamespace(pk=None, content_type_id=None, title="unsaved")])
def test_payload_without_saved_post_keeps_audio_only_identity(post):
    audio = SimpleNamespace(pk=7)
    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        side_effect=_fake_payload,
    ):
        payload = cast_player_payload({}, audio, post)

    assert payload["payload_id"] == "cast-player-data-7"
    assert payload["player_id"] == "cast-player-7"
    assert '<script id="cast-player-data-7" type="application/json">' in payload["player_script"]


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


@pytest.mark.parametrize(
    "seconds",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        0,
        0.0,
        -30,
        None,
        "3600",
        "",
        [3600],
    ],
)
def test_format_duration_omits_label_for_unknown_or_malformed_values(seconds):
    from python_podcast.pp.templatetags.pp_persistent_player import _format_duration

    assert _format_duration(seconds) == ""


@pytest.mark.parametrize(
    ("seconds", "label"),
    [
        (1, "1 min"),
        (29.4, "1 min"),
        (90, "2 min"),
        (2700, "45 min"),
        (3570.0, "1 h"),
        (3600, "1 h"),
        (5400, "1 h 30 min"),
        (7260.5, "2 h 1 min"),
    ],
)
def test_format_duration_keeps_known_positive_labels(seconds, label):
    from python_podcast.pp.templatetags.pp_persistent_player import _format_duration

    assert _format_duration(seconds) == label


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), True])
def test_cast_player_payload_survives_malformed_duration(duration):
    from python_podcast.pp.templatetags.pp_persistent_player import cast_player_payload

    post = SimpleNamespace(pk=3, content_type_id=1, cover_image=None, blog=None)
    with patch(
        "python_podcast.pp.templatetags.pp_persistent_player.build_player_payload",
        return_value={"title": "Episode", "duration": duration, "poster": "https://media.example/p.webp"},
    ):
        payload = cast_player_payload({"request": None}, SimpleNamespace(pk=7), post)

    assert payload["duration_display"] == ""
