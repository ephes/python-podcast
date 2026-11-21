"""Template helpers for the persistent-audio-player staging proof.

The django-cast ``cast_custom_player`` inclusion tag renders its template with an
isolated context that does not carry context processors, so the persistent flag
is exposed here as a tag that reads the setting directly. ``cast_player_payload``
builds the sanitized payload + ids so a theme's audio block can PUBLISH them
(``json_script`` + an inert play action) instead of rendering an in-body player.
"""

import math
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from cast.models import Blog, Post
from cast.models.pages import PODLOVE_POSTER_RENDITION_SPEC
from cast.player import build_player_payload
from django import template
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import router
from django.db.models import Prefetch, QuerySet, prefetch_related_objects
from django.utils.html import json_script
from django.utils.safestring import mark_safe
from django_vite.core.asset_loader import DjangoViteAssetLoader
from wagtail.images import get_image_model
from wagtail.images.models import SourceImageIOError
from wagtail.models import Page

register = template.Library()

CARD_POSTER_RENDITION_SPEC = "max-128x128|format-webp"


def _cover_prefetch(using: str | None = None) -> Prefetch:
    image_model = get_image_model()
    specs = (PODLOVE_POSTER_RENDITION_SPEC, CARD_POSTER_RENDITION_SPEC)
    images = image_model.objects.all()
    if using is None:
        images = images.prefetch_renditions(*specs)
    else:
        # Use Wagtail's rendition prefetch attribute with an explicit alias
        # for both queries. A router can override Django's instance hint.
        renditions = image_model.get_rendition_model().objects.using(using).filter(filter_spec__in=specs)
        images = images.using(using).prefetch_related(
            Prefetch("renditions", queryset=renditions, to_attr="prefetched_renditions")
        )
    return Prefetch("cover_image", queryset=images)


def _page_database(page: Any) -> str | None:
    return getattr(getattr(page, "_state", None), "db", None)


def _routed_card_pages(queryset: QuerySet, using: str) -> dict[int, Page]:
    # Wagtail's specific() sends its concrete-model queries through unbound
    # managers, even when the outer Page queryset has an explicit database.
    ids_by_type = defaultdict(list)
    for pk, content_type_id in queryset.values_list("pk", "content_type_id"):
        ids_by_type[content_type_id].append(pk)

    pages = {}
    content_types = ContentType.objects.db_manager(using)
    for content_type_id, ids in ids_by_type.items():
        try:
            content_type = content_types.get_for_id(content_type_id)
        except ContentType.DoesNotExist:
            continue
        model = content_type.model_class()
        if model is not None and issubclass(model, Post):
            pages.update(model.objects.using(using).prefetch_related(_cover_prefetch(using)).in_bulk(ids))
    return pages


def _payload_post(context: Any, post: Any) -> Any:
    """Resolve only the displayed cached cards, sharing pages within this request."""
    if post is None or not getattr(post, "pk", None):
        return post
    blog = context.get("blog")
    page_url = getattr(post, "page_url", None)
    using = None
    episode = None
    if getattr(post, "content_type_id", None) is None:
        posts = context.get("posts", ())
        owner_database = _page_database(blog) or _page_database(context.get("page"))
        if owner_database is None and isinstance(posts, QuerySet):
            owner_database = posts.db
        using = _page_database(post) or owner_database
        request = context.get("request")
        if request is not None:
            if not hasattr(request, "_pp_player_pages"):
                request._pp_player_pages = {}
            by_database = request._pp_player_pages
        else:
            by_database = context.setdefault("_pp_player_pages", {})
        pages = by_database.setdefault((using is not None, using or router.db_for_read(Page)), {})

        if post.pk not in pages:
            has_audio = getattr(context.get("repository"), "has_audio_by_id", {})
            ids = {
                card.pk
                for card in posts
                if getattr(card, "pk", None)
                and getattr(card, "content_type_id", None) is None
                and has_audio.get(card.pk) is not False
                and (_page_database(card) or owner_database) == using
            }
            ids.add(post.pk)
            unresolved = ids - pages.keys()
            queryset = Page.objects.filter(pk__in=unresolved)
            resolved: dict[int, Page | None] = dict.fromkeys(unresolved)
            if using is None:
                queryset = queryset.specific().prefetch_related(_cover_prefetch(), for_specific_subqueries=True)
                resolved.update((page.pk, page) for page in queryset)
            else:
                resolved.update(_routed_card_pages(queryset.using(using), using))
            pages.update(resolved)
        post = pages[post.pk]
        if post is None:
            return None
        if using is not None:
            episode = post

    if episode is None:
        episode = getattr(post, "specific", post)
    # The pinned cast payload builder eagerly reads post.blog, even with an
    # explicit episode cover. Supply its public duck-typed context separately
    # from the concrete episode, avoiding ancestor reads and private cast caches.
    if getattr(episode, "cover_image", None) is not None:
        blog = None
    elif using is not None:
        if not isinstance(blog, Blog) or _page_database(blog) != using or not episode.is_child_of(blog):
            blog = Blog.objects.using(using).parent_of(episode).first()
        if blog is not None:
            prefetch_related_objects([blog], _cover_prefetch(using))
            blog = SimpleNamespace(specific=blog)
    else:
        blog = blog or getattr(post, "blog", None)
        blog = getattr(blog, "specific", blog)
        if blog is not None and hasattr(blog, "_meta"):
            prefetch_related_objects([blog], _cover_prefetch())
    return SimpleNamespace(pk=post.pk, specific=episode, blog=blog, page_url=page_url)


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
def cast_player_payload(context: dict[str, Any], audio: Any, post: Any) -> dict[str, Any] | None:
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
    A cached post whose page has been deleted has no playable payload.
    Repeated blocks in one render reuse the card data with an empty script.
    """
    request = context.get("request")
    resolved_post = _payload_post(context, post)
    if resolved_post is None and post is not None:
        return None
    post = resolved_post
    identity = _payload_identity(audio, post)
    rendered = context.get("_pp_player_payloads")
    if rendered is not None and identity in rendered:
        return rendered[identity]

    payload = build_player_payload(audio, post=post, request=request)
    payload_id = f"cast-player-data-{identity}"
    poster = payload.get("poster", "")
    card = {
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
    if rendered is not None:
        rendered[identity] = {**card, "player_script": ""}
    return card
