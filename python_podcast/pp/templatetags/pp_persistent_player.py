"""Template helpers for the persistent-audio-player staging proof.

The django-cast ``cast_custom_player`` inclusion tag renders its template with an
isolated context that does not carry context processors, so the persistent flag
is exposed here as a tag that reads the setting directly. ``cast_player_payload``
builds the sanitized payload + ids so a theme's audio block can PUBLISH them
(``json_script`` + an inert play action) instead of rendering an in-body player.
"""

import math
from types import SimpleNamespace
from typing import Any

from cast.models.pages import PODLOVE_POSTER_RENDITION_SPEC
from cast.player import build_player_payload
from django import template
from django.conf import settings
from django.db.models import Prefetch, prefetch_related_objects
from django.utils.html import json_script
from django.utils.safestring import mark_safe
from django_vite.core.asset_loader import DjangoViteAssetLoader
from wagtail.images import get_image_model
from wagtail.images.models import SourceImageIOError
from wagtail.models import Page

register = template.Library()

CARD_POSTER_RENDITION_SPEC = "max-128x128|format-webp"


def _cover_prefetch() -> Prefetch:
    images = get_image_model().objects.prefetch_renditions(PODLOVE_POSTER_RENDITION_SPEC, CARD_POSTER_RENDITION_SPEC)
    return Prefetch("cover_image", queryset=images)


def _payload_post(context: Any, post: Any) -> Any:
    """Resolve only the displayed cached cards, sharing pages within this request."""
    if post is None or not getattr(post, "pk", None):
        return post
    if getattr(post, "content_type_id", None) is None:
        request = context.get("request")
        if request is not None:
            if not hasattr(request, "_pp_player_pages"):
                request._pp_player_pages = {}
            pages = request._pp_player_pages
        else:
            pages = context.setdefault("_pp_player_pages", {})
        if post.pk not in pages:
            ids = {card.pk for card in context.get("posts", ()) if getattr(card, "pk", None)}
            ids.add(post.pk)
            queryset = (
                Page.objects.filter(pk__in=ids - pages.keys())
                .specific()
                .prefetch_related(_cover_prefetch(), for_specific_subqueries=True)
            )
            pages.update((page.pk, page) for page in queryset)
        if post.pk not in pages:
            raise Page.DoesNotExist(f"Player post {post.pk} no longer exists")
        post = pages[post.pk]

    episode = getattr(post, "specific", post)
    blog = None
    # The pinned cast payload builder eagerly reads post.blog, even with an
    # explicit episode cover. Supply its public duck-typed context separately
    # from the concrete episode, avoiding ancestor reads and private cast caches.
    if getattr(episode, "cover_image", None) is None:
        blog = context.get("blog") or getattr(post, "blog", None)
        blog = getattr(blog, "specific", blog)
        if blog is not None and hasattr(blog, "_meta"):
            prefetch_related_objects([blog], _cover_prefetch())
    return SimpleNamespace(pk=post.pk, specific=episode, blog=blog)


def _card_poster_url(post: Any, request: Any, fallback: str) -> str:
    """Return a small poster for the compact page card.

    The player's payload keeps django-cast's 512 px poster for consumers that
    may render it larger. The initial page card is at most 54 px wide, so it can
    use a much smaller Wagtail rendition and avoid downloading the player-sized
    artwork before anyone starts playback.
    """
    episode = getattr(post, "specific", post)
    cover_image = getattr(episode, "cover_image", None)
    if cover_image is None:
        blog_page = getattr(post, "blog", None)
        blog = getattr(blog_page, "specific", blog_page)
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
    post = _payload_post(context, post)
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
