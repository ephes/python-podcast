"""Query budgets for actual payload/template rendering of cached overview cards."""

import json
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cast.models import Audio, Episode, Podcast, Transcript
from cast.models.pages import PODLOVE_POSTER_RENDITION_SPEC
from cast.models.repository.serialization import deserialize_post, serialize_post
from django.contrib.contenttypes.models import ContentType
from django.core.cache import caches
from django.template import Context, Template
from django.test import RequestFactory
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.images import get_image_model
from wagtail.models import Collection, Locale, Page

from python_podcast.pp.templatetags.pp_persistent_player import CARD_POSTER_RENDITION_SPEC
from python_podcast.users.tests.factories import UserFactory

PLAYER_SPEC = PODLOVE_POSTER_RENDITION_SPEC
PLAYER_FILENAME_SPEC = PLAYER_SPEC.replace("|", "-")


def _cover(num):
    # Existing synthetic renditions need neither an encoder nor an original file.
    image = get_image_model().objects.create(
        title=f"Cover {num}", file=f"original_images/synthetic-{num}.png", width=512, height=512
    )
    for spec in (PLAYER_SPEC, CARD_POSTER_RENDITION_SPEC):
        image.get_rendition_model().objects.create(
            image=image,
            filter_spec=spec,
            file=f"images/cover-{num}.{spec.replace('|', '-')}.webp",
            width=128,
            height=128,
            focal_point_key="",
        )
    return image


@pytest.fixture
def card_rows(db):
    from django.conf import settings

    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    user = UserFactory()
    root = Page.get_first_root_node() or Page.add_root(title="Root", slug="root")
    blog = root.add_child(instance=Podcast(title="Synthetic podcast", slug="synthetic", owner=user))
    collection = Collection.get_first_root_node() or Collection.add_root(name="Root")
    audio = Audio(user=user, collection=collection, title="Shared synthetic audio", duration=timedelta(seconds=60))
    audio.save(duration=False, cache_file_sizes=False)
    transcript = Transcript(audio=audio, podlove="synthetic.json")
    # Preload audio metadata to isolate the post/cover read budget. No payload
    # builder, page lookup, image or rendition method is mocked.
    loaded_audio = SimpleNamespace(
        pk=audio.pk, title=audio.title, subtitle="", duration=audio.duration, chapters=[], transcript=transcript
    )
    episodes = []
    for num in range(20):
        episodes.append(
            blog.add_child(
                instance=Episode(
                    title=f"Episode {num}",
                    slug=f"episode-{num}",
                    owner=user,
                    podcast_audio=audio,
                    cover_image=_cover(num),
                    body=[],
                )
            )
        )
    return blog, loaded_audio, episodes


def _render(blog, audio, episodes, theme="bootstrap5"):
    posts = [deserialize_post(serialize_post(episode)) for episode in episodes]
    # Simulate another request, including cold rendition and content-type caches.
    for cache in caches.all():
        cache.clear()
    ContentType.objects.clear_cache()
    context = Context(
        {"posts": posts, "blog": blog, "audio": audio, "request": RequestFactory().get("/"), "theme": theme}
    )
    template = Template(
        "{% load pp_persistent_player %}{% for post in posts %}"
        '{% include "cast/"|add:theme|add:"/audio.html" with page=post value=audio %}'
        "{% endfor %}"
    )
    return template, context


@pytest.mark.parametrize("theme", ["pp", "bootstrap5"])
@pytest.mark.parametrize("count", [1, 20])
@pytest.mark.parametrize("shared_cover", [False, True])
def test_cached_card_pages_and_covers_have_fixed_read_budget(
    card_rows, settings, django_assert_num_queries, count, shared_cover, theme
):
    settings.PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True
    settings.CAST_AUDIO_PLAYER = "custom"
    blog, audio, episodes = card_rows
    if shared_cover:
        Episode.objects.filter(pk__in=[episode.pk for episode in episodes]).update(cover_image=episodes[0].cover_image)
    template, context = _render(blog, audio, episodes[:count], theme)
    # Cold content type + base pages + concrete episodes + covers + renditions.
    with django_assert_num_queries(5) as queries:
        html = template.render(context)
    assert not any(
        'FROM "cast_podcast"' in query["sql"] or 'FROM "cast_blog"' in query["sql"]
        for query in queries.captured_queries
    )
    scripts = re.findall(r'<script id="([^"]+)" type="application/json">(.*?)</script>', html)
    assert len(scripts) == count
    for (identity, raw_payload), episode in zip(scripts, episodes):
        payload = json.loads(raw_payload)
        cover_num = 0 if shared_cover else episodes.index(episode)
        assert identity == f"cast-player-data-{audio.pk}-post-{episode.pk}"
        assert payload["audioId"] == audio.pk
        assert payload["transcript"]["url"].endswith(f"?post_id={episode.pk}")
        assert payload["poster"] == f"http://testserver/media/images/cover-{cover_num}.{PLAYER_FILENAME_SPEC}.webp"
        assert f"http://testserver/media/images/cover-{cover_num}.max-128x128-format-webp.webp" in html


def test_cached_cards_reuse_blog_fallback_renditions(card_rows, settings, django_assert_num_queries):
    settings.PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True
    settings.CAST_AUDIO_PLAYER = "custom"
    blog, audio, episodes = card_rows
    blog.cover_image = episodes[0].cover_image
    blog.save()
    Episode.objects.filter(pk__in=[episode.pk for episode in episodes]).update(cover_image=None)
    # A fresh blog's cover relation is cold as well.
    blog = Podcast.objects.get(pk=blog.pk)
    template, context = _render(blog, audio, episodes)
    # Podcast.specific also resolves its cold content type.
    with django_assert_num_queries(6):
        html = template.render(context)
    assert html.count('src="http://testserver/media/images/cover-0.max-128x128-format-webp.webp"') == 20


def test_cached_card_missing_small_rendition_retains_player_poster(card_rows, settings):
    settings.PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True
    settings.CAST_AUDIO_PLAYER = "custom"
    blog, audio, episodes = card_rows
    image = episodes[0].cover_image
    image.renditions.filter(filter_spec=CARD_POSTER_RENDITION_SPEC).delete()
    # The original is deliberately absent; the pre-existing 512px poster survives.
    template, context = _render(blog, audio, episodes[:1])
    html = template.render(context)
    assert f'src="http://testserver/media/images/cover-0.{PLAYER_FILENAME_SPEC}.webp"' in html
