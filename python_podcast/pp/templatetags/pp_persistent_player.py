"""Template helpers for the persistent-audio-player staging proof.

The django-cast ``cast_custom_player`` inclusion tag renders its template with an
isolated context that does not carry context processors, so the persistent flag
is exposed here as a tag that reads the setting directly. ``cast_player_payload``
builds the sanitized payload + ids so a theme's audio block can PUBLISH them
(``json_script`` + an inert play action) instead of rendering an in-body player.
"""

import math
from typing import Any

from cast.player import build_player_payload
from django import template
from django.conf import settings
from django.utils.html import json_script
from django.utils.safestring import mark_safe
from django_vite.core.asset_loader import DjangoViteAssetLoader
from wagtail.images.models import SourceImageIOError

register = template.Library()

CARD_POSTER_RENDITION_SPEC = "max-128x128|format-webp"


def _card_poster_url(post: Any, request: Any, fallback: str) -> str:
    """Return a small poster for the compact page card.

    The player's payload keeps django-cast's 512 px poster for consumers that
    may render it larger. The initial page card is at most 54 px wide, so it can
    use a much smaller Wagtail rendition and avoid downloading the player-sized
    artwork before anyone starts playback.
    """
    episode = getattr(post, "specific", post)
    blog_page = getattr(post, "blog", None)
    blog = getattr(blog_page, "specific", blog_page)
    cover_image = getattr(episode, "cover_image", None)
    if cover_image is None and blog is not None:
        cover_image = getattr(blog, "cover_image", None)
    if cover_image is None:
        return fallback

    try:
        poster_url = cover_image.get_rendition(CARD_POSTER_RENDITION_SPEC).url
    except (FileNotFoundError, SourceImageIOError):
        # A cached player poster can outlive the original needed for this
        # optional smaller rendition.
        return fallback
    if request is not None and hasattr(request, "build_absolute_uri"):
        poster_url = request.build_absolute_uri(poster_url)
    return poster_url


def _format_duration(seconds: Any) -> str:
    """Render a payload duration (seconds) as a compact human label.

    Used by the episode play card ("Play episode · 45 min"). Returns "" when the
    duration is unknown so the template can omit the label entirely. Only a
    finite positive ``int``/``float`` counts as known: malformed metadata (NaN,
    infinity, booleans, strings, ``None``, zero or negative values) yields ""
    instead of failing the page render.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return ""
    if not math.isfinite(seconds) or seconds <= 0:
        return ""
    minutes = int(round(seconds / 60))
    if minutes < 1:
        minutes = 1
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


@register.simple_tag
def pp_persistent_player_enabled() -> bool:
    """Return whether the persistent-audio-player staging proof is enabled."""
    return bool(getattr(settings, "PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER", False))


@register.simple_tag
@mark_safe
def pp_vite_asset_deferred_css(path: str, app: str) -> str:
    """Render a Vite module while making its dependent CSS non-blocking.

    The custom player does not exist before the first play action, so its Vite
    stylesheet can download at print-media priority without delaying FCP/LCP.
    The module script and modulepreload tags keep django-vite's normal output.
    """
    asset_html = DjangoViteAssetLoader.instance().generate_vite_asset(path, app)
    return asset_html.replace(
        'rel="stylesheet"',
        'rel="stylesheet" media="print" onload="this.media=\'all\'"',
    )


def _payload_identity(audio: Any, post: Any) -> str:
    """Return the id suffix shared by a payload script and its play card."""
    post_pk = getattr(post, "pk", None)
    if post_pk is None:
        return f"{audio.pk}"
    return f"{audio.pk}-post-{post_pk}"


@register.simple_tag(takes_context=True)
def cast_player_payload(context: dict[str, Any], audio: Any, post: Any) -> dict[str, Any]:
    """Return the sanitized custom-player payload + ids for ``audio``.

    Use as ``{% cast_player_payload value page as payload %}``; the theme then
    renders ``{{ payload.player_script }}`` (a ``json_script``) plus an inert
    ``[data-cast-play="{{ payload.payload_id }}"]`` action. The same payload
    contract as django-cast's ``cast_custom_player`` drives the single live
    persistent player, with no in-body ``<cast-audio-player>``.

    The payload carries post context (cover poster, transcript link), so its ids name the
    audio *and* the post: ``cast-player-data-<audio pk>-post-<post pk>``. Two
    posts that reuse one audio on an overview therefore publish two distinct
    payloads, while the same post keeps one id on its detail page and on every
    list card, which is what lets a card mirror the playing dock after
    navigation. Without a saved post the audio-only django-cast id
    ``cast-player-data-<audio pk>`` is kept.
    """
    request = context.get("request")
    # Overview/list cards come from the cached repository and can supply a
    # lightweight post without a content_type, which build_player_payload's
    # `post.specific` would choke on. Re-fetch the concrete page by pk in that
    # case (detail pages pass a served, content-typed page -> no extra query).
    if post is not None and getattr(post, "content_type_id", None) is None and getattr(post, "pk", None):
        from wagtail.models import Page

        post = Page.objects.get(pk=post.pk).specific
    payload = build_player_payload(audio, post=post, request=request)
    identity = _payload_identity(audio, post)
    payload_id = f"cast-player-data-{identity}"
    poster = payload.get("poster", "")
    return {
        "player_script": json_script(payload, payload_id),
        "payload_id": payload_id,
        "player_id": f"cast-player-{identity}",
        "title": payload.get("title", ""),
        # The dock can use the player-sized payload poster after interaction;
        # the initial card gets a responsive rendition sized for its 46–54 px
        # display box. Empty poster / "" duration are omitted in the template.
        "poster": poster,
        "card_poster": _card_poster_url(post, request, poster) if poster else "",
        "duration_display": _format_duration(payload.get("duration")),
    }
