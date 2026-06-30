from __future__ import annotations

import json
from io import StringIO

import pytest
from cast.devdata import create_image
from cast.models import Episode, Podcast
from django.conf import settings
from django.core.management import call_command
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Collection, Locale, Page, Site

from python_podcast.users.tests.factories import UserFactory


def _ensure_site():
    if not Collection.objects.exists():
        Collection.add_root(name="Root")
    site = Site.objects.first()
    if site is not None:
        return site
    language_code = get_supported_content_language_variant(settings.LANGUAGE_CODE)
    locale, _ = Locale.objects.get_or_create(language_code=language_code)
    root = Page.get_first_root_node()
    if root is None:
        root = Page.add_root(title="Root", locale=locale)
    return Site.objects.create(hostname="testserver", port=80, root_page=root, is_default_site=True)


def _make_episode(*, slug, detail_children, num=1, overview=None):
    owner = UserFactory()
    site = _ensure_site()
    podcast = Podcast(title=f"Podcast {num}", slug=f"podcast-{slug}", owner=owner)
    site.root_page.add_child(instance=podcast)
    overview_value = overview if overview is not None else [{"type": "heading", "value": "overview heading"}]
    body = []
    if overview_value is not None:
        body.append({"type": "overview", "value": overview_value})
    if detail_children is not None:
        body.append({"type": "detail", "value": detail_children})
    episode = Episode(
        title=f"Episode {num}",
        slug=slug,
        owner=podcast.owner,
        body=json.dumps(body),
    )
    podcast.add_child(instance=episode)
    return episode


def _run(*args):
    out = StringIO()
    call_command("convert_show_notes", *args, stdout=out, stderr=out)
    return out.getvalue()


def _detail_types(page):
    for block in page.body:
        if block.block_type == "detail":
            return [child.block_type for child in block.value]
    return None


def _latest_revision_object(episode):
    # Reload to pick up the latest_revision pointer written by the command.
    return Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()


SHOWNOTE_HTML = (
    "<h2>Shownotes</h2>"
    '<p>Unsere E-Mail: <a href="mailto:hallo@example.com">hallo@example.com</a></p>'
    "<h3>News</h3><ul>"
    '<li><a href="https://example.com/a">Article A</a></li>'
    '<li>April:&nbsp;<a href="https://example.com/b">B</a>&nbsp;|&nbsp;<a href="https://example.com/c">C</a></li>'
    "</ul>"
)


@pytest.mark.django_db
def test_dry_run_does_not_write():
    episode = _make_episode(slug="dry-run-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    output = _run("--slug", "dry-run-ep")

    assert episode.revisions.count() == 0
    assert _detail_types(Episode.objects.get(pk=episode.pk)) == ["paragraph"]
    assert "dry-run-ep" in output
    assert "dry run" in output.lower()


@pytest.mark.django_db
def test_apply_creates_revision_and_converts():
    episode = _make_episode(slug="apply-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    _run("--slug", "apply-ep", "--apply")

    assert episode.revisions.count() == 1
    revised = _latest_revision_object(episode)
    types = _detail_types(revised)
    assert "show_note_heading" in types
    assert "show_note_link_list" in types
    # Live page body stays untouched until published.
    assert _detail_types(Episode.objects.get(pk=episode.pk)) == ["paragraph"]


@pytest.mark.django_db
def test_publish_updates_live_body():
    episode = _make_episode(slug="publish-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    _run("--slug", "publish-ep", "--publish")

    live_types = _detail_types(Episode.objects.get(pk=episode.pk))
    assert "show_note_link_list" in live_types


@pytest.mark.django_db
def test_idempotent_skips_already_converted():
    _make_episode(slug="idem-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    _run("--slug", "idem-ep", "--apply")
    episode = Episode.objects.get(slug="idem-ep")
    revisions_after_first = episode.revisions.count()

    output = _run("--slug", "idem-ep", "--apply")

    assert episode.revisions.count() == revisions_after_first
    assert "already" in output.lower()


@pytest.mark.django_db
def test_publish_after_apply_publishes_existing_draft():
    episode = _make_episode(
        slug="apply-then-publish-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )

    _run("--slug", "apply-then-publish-ep", "--apply")
    # Live body is still the legacy paragraph at this point.
    assert _detail_types(Episode.objects.get(pk=episode.pk)) == ["paragraph"]

    output = _run("--slug", "apply-then-publish-ep", "--publish")

    # The previously created draft must now be live, and no extra revision spawned.
    live_types = _detail_types(Episode.objects.get(pk=episode.pk))
    assert "show_note_link_list" in live_types
    assert Episode.objects.get(pk=episode.pk).revisions.count() == 1
    assert "publish" in output.lower()


@pytest.mark.django_db
def test_publish_does_not_publish_unrelated_draft():
    episode = _make_episode(
        slug="unrelated-draft-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "unrelated-draft-ep", "--publish")  # live is now converted

    # Create an unrelated, unpublished draft (an overview edit).
    ep = Episode.objects.get(pk=episode.pk)
    raw = ep.body.raw_data
    for block in raw:
        if block["type"] == "overview":
            block["value"] = [{"type": "heading", "value": "draft only edit"}]
    ep.body = ep.body.stream_block.to_python(raw)
    ep.save_revision()

    output = _run("--slug", "unrelated-draft-ep", "--publish")

    assert "already" in output.lower()
    # the unrelated draft must not have been pushed live
    live_overview = [
        child["value"]
        for block in Episode.objects.get(pk=episode.pk).body.raw_data
        if block["type"] == "overview"
        for child in block["value"]
    ]
    assert "draft only edit" not in live_overview


@pytest.mark.django_db
def test_force_preserves_current_overview():
    episode = _make_episode(
        slug="force-overview-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
        overview=[{"type": "heading", "value": "overview v1"}],
    )
    # Legacy revision in history: overview v1 + legacy detail.
    episode.save_revision().publish()
    _run("--slug", "force-overview-ep", "--publish")

    # Edit the overview to v2 on the live page (the detail is already converted).
    ep = Episode.objects.get(pk=episode.pk)
    raw = ep.body.raw_data
    for block in raw:
        if block["type"] == "overview":
            block["value"] = [{"type": "heading", "value": "overview v2"}]
    ep.body = ep.body.stream_block.to_python(raw)
    ep.save_revision().publish()

    # --force re-converts the detail from the legacy revision, but must keep the
    # current overview (v2), not revert it to the legacy revision's v1.
    _run("--slug", "force-overview-ep", "--apply", "--force")

    revised = _latest_revision_object(episode)
    overview_headings = [
        child["value"]
        for block in revised.body.raw_data
        if block["type"] == "overview"
        for child in block["value"]
        if child["type"] == "heading"
    ]
    assert overview_headings == ["overview v2"]
    assert "show_note_link_list" in _detail_types(revised)


@pytest.mark.django_db
def test_preserves_sibling_image_block():
    _ensure_site()  # create the root collection before building an image
    image = create_image()
    episode = _make_episode(
        slug="sibling-ep",
        detail_children=[
            {"type": "paragraph", "value": SHOWNOTE_HTML},
            {"type": "image", "value": image.pk},
        ],
    )

    _run("--slug", "sibling-ep", "--apply")

    revised = _latest_revision_object(episode)
    types = _detail_types(revised)
    assert "image" in types
    assert "show_note_link_list" in types
    # the image block keeps pointing at the same image id in the raw data
    detail = next(block for block in revised.body.raw_data if block["type"] == "detail")
    image_values = [child["value"] for child in detail["value"] if child["type"] == "image"]
    assert image_values == [image.pk]


@pytest.mark.django_db
def test_skips_episode_without_detail():
    _make_episode(slug="no-detail-ep", detail_children=None)

    output = _run("--slug", "no-detail-ep", "--apply")

    assert "no-detail-ep" in output
    assert "no detail" in output.lower()
    assert Episode.objects.get(slug="no-detail-ep").revisions.count() == 0


@pytest.mark.django_db
def test_ambiguous_item_preserved_with_warning():
    # A nested sub-item with multiple links cannot be flattened safely.
    html = (
        "<h3>News</h3><ul>"
        "<li>Sprachen<ul>"
        '<li><a href="https://example.com/v">vlang</a> | <a href="https://example.com/z">zig</a></li>'
        "</ul></li>"
        "</ul>"
    )
    episode = _make_episode(slug="ambiguous-ep", detail_children=[{"type": "paragraph", "value": html}])

    output = _run("--slug", "ambiguous-ep", "--apply")

    revised = _latest_revision_object(episode)
    types = _detail_types(revised)
    assert "show_note_heading" in types
    assert "show_note_link_list" not in types
    assert "warning" in output.lower()


@pytest.mark.django_db
def test_force_reconverts_already_converted_draft():
    episode = _make_episode(slug="force-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    _run("--slug", "force-ep", "--apply")
    assert episode.revisions.count() == 1

    # Without --force a second apply is a no-op.
    output_plain = _run("--slug", "force-ep", "--apply")
    assert "already" in output_plain.lower()
    assert Episode.objects.get(pk=episode.pk).revisions.count() == 1

    # With --force it re-converts from the original legacy body and writes again.
    output_force = _run("--slug", "force-ep", "--apply", "--force")
    assert "would change" not in output_force.lower()
    revised = _latest_revision_object(episode)
    assert "show_note_link_list" in _detail_types(revised)
    assert Episode.objects.get(pk=episode.pk).revisions.count() == 2


@pytest.mark.django_db
def test_force_recovers_legacy_body_after_publish():
    episode = _make_episode(
        slug="force-published-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    # Record the legacy body as a published revision, then publish a conversion.
    episode.save_revision().publish()
    _run("--slug", "force-published-ep", "--publish")
    assert "show_note_link_list" in _detail_types(Episode.objects.get(pk=episode.pk))

    # --force must find the legacy revision and re-convert from it, not from the
    # already-converted live body.
    _run("--slug", "force-published-ep", "--apply", "--force")

    revised = _latest_revision_object(episode)
    assert "show_note_link_list" in _detail_types(revised)


@pytest.mark.django_db
def test_slug_filter_limits_scope():
    _make_episode(slug="target-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}], num=1)
    other = _make_episode(slug="other-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}], num=2)

    _run("--slug", "target-ep", "--apply")

    assert other.revisions.count() == 0
