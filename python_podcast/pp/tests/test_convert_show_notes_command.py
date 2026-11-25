from __future__ import annotations

import inspect
import json
import threading
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from cast.devdata import create_image
from cast.models import Audio, Episode, Podcast
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Collection, Locale, Page, Revision, Site

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


def _make_episode(*, slug, detail_children, num=1, overview=None, podcast_slug=None):
    owner = UserFactory()
    site = _ensure_site()
    podcast = Podcast(title=f"Podcast {num}", slug=podcast_slug or f"podcast-{slug}", owner=owner)
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
        podcast_audio=Audio.objects.create(user=podcast.owner, title=f"Episode {num} audio"),
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing_draft", [False, True])
def test_publish_reports_committed_revision_when_callback_fails(monkeypatch, existing_draft):
    episode = _make_episode(slug="callback-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    if existing_draft:
        _run("--slug", episode.slug, "--apply")
        episode.refresh_from_db()
    existing_revision_id = episode.latest_revision_id
    original_publish = Revision.publish

    def fail_after_commit():
        raise RuntimeError("synthetic private callback detail")

    def publish(self, *args, **kwargs):
        transaction.on_commit(fail_after_commit)
        return original_publish(self, *args, **kwargs)

    monkeypatch.setattr(Revision, "publish", publish)
    output = StringIO()
    with pytest.raises(CommandError) as error:
        call_command("convert_show_notes", "--slug", episode.slug, "--publish", stdout=output)

    episode.refresh_from_db()
    assert "show_note_link_list" in _detail_types(episode)
    assert episode.live_revision_id == episode.latest_revision_id
    assert episode.revisions.count() == 1
    if existing_draft:
        assert episode.live_revision_id == existing_revision_id
    assert f"committed (revision {episode.live_revision_id}, published)" in output.getvalue()
    assert "follow-up failed: RuntimeError" in output.getvalue()
    if existing_draft:
        assert f"-> published existing converted draft (revision {existing_revision_id})" in output.getvalue()
    else:
        # The committed conversion keeps its full per-episode report.
        assert "  before: " in output.getvalue()
        assert "  after:  " in output.getvalue()
        assert "show_note_link_list" in output.getvalue()
        assert f"-> changed (revision {episode.live_revision_id})" in output.getvalue()
    assert f"Revisions: {int(not existing_draft)} created, 1 published." in output.getvalue()
    assert "private callback detail" not in output.getvalue()
    assert "failed: callback-ep" not in str(error.value)
    assert "follow-up" in str(error.value)
    assert episode.slug in str(error.value)


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


def _save_overview_draft(episode, text="draft only edit", title=None):
    """Save an unpublished edit that has nothing to do with the detail conversion."""
    draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
    raw = [dict(block) for block in draft.body.raw_data]
    for block in raw:
        if block["type"] == "overview":
            block["value"] = [{"type": "heading", "value": text}]
    draft.body = draft.body.stream_block.to_python(raw)
    if title is not None:
        draft.title = title
    return draft.save_revision()


def _overview_values(page):
    return [child["value"] for block in page.body.raw_data if block["type"] == "overview" for child in block["value"]]


def _run_expecting_conflict(*args):
    out = StringIO()
    with pytest.raises(CommandError) as excinfo:
        call_command("convert_show_notes", *args, stdout=out, stderr=out)
    return out.getvalue(), str(excinfo.value)


@pytest.mark.django_db
def test_publish_refuses_conversion_draft_with_later_unrelated_edit():
    episode = _make_episode(
        slug="apply-edit-publish-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "apply-edit-publish-ep", "--apply")
    pending = _save_overview_draft(episode)

    output, error = _run_expecting_conflict("--slug", "apply-edit-publish-ep", "--publish")

    live = Episode.objects.get(pk=episode.pk)
    assert _overview_values(live) == ["overview heading"]
    assert _detail_types(live) == ["paragraph"]
    # The pending edit survives as the latest draft, including the conversion.
    assert live.has_unpublished_changes
    assert live.latest_revision_id == pending.pk
    assert live.revisions.count() == 2
    draft = _latest_revision_object(episode)
    assert _overview_values(draft) == ["draft only edit"]
    assert "show_note_link_list" in _detail_types(draft)
    assert "conflict: not published" in output
    assert "body outside the detail section" in output
    assert "1 not published (conflict)" in output
    assert "apply-edit-publish-ep" in error


@pytest.mark.django_db
def test_publish_refuses_conversion_draft_with_later_title_edit():
    episode = _make_episode(
        slug="apply-title-publish-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "apply-title-publish-ep", "--apply")
    draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
    draft.title = "Draft title"
    draft.save_revision()

    output, _ = _run_expecting_conflict("--slug", "apply-title-publish-ep", "--publish")

    live = Episode.objects.get(pk=episode.pk)
    assert live.title == "Episode 1"
    assert _detail_types(live) == ["paragraph"]
    assert "also changes title" in output


@pytest.mark.django_db
def test_publish_refuses_to_convert_on_top_of_pending_unrelated_draft():
    episode = _make_episode(
        slug="edit-then-publish-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _save_overview_draft(episode)

    output, _ = _run_expecting_conflict("--slug", "edit-then-publish-ep", "--publish")

    live = Episode.objects.get(pk=episode.pk)
    assert _overview_values(live) == ["overview heading"]
    assert _detail_types(live) == ["paragraph"]
    # --publish implies --apply: the conversion is saved as a draft on top of the pending edit.
    draft = _latest_revision_object(episode)
    assert _overview_values(draft) == ["draft only edit"]
    assert "show_note_link_list" in _detail_types(draft)
    assert live.revisions.count() == 2
    assert "changed (draft revision" in output
    assert "conflict: not published" in output


@pytest.mark.django_db
def test_publish_conflict_does_not_block_other_episodes():
    conflicted = _make_episode(
        slug="batch-conflict-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
        num=1,
    )
    clean = _make_episode(
        slug="batch-clean-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
        num=2,
    )
    _run("--apply")
    _save_overview_draft(conflicted)

    output, error = _run_expecting_conflict("--publish")

    assert _detail_types(Episode.objects.get(pk=conflicted.pk)) == ["paragraph"]
    assert "show_note_link_list" in _detail_types(Episode.objects.get(pk=clean.pk))
    assert "Revisions: 0 created, 1 published." in output
    assert "batch-conflict-ep" in error and "batch-clean-ep" not in error


@pytest.mark.django_db
@pytest.mark.parametrize("with_conflict", [False, True])
def test_publish_summary_counts_only_written_drafts_and_publications(monkeypatch, with_conflict):
    legacy_detail = [{"type": "paragraph", "value": SHOWNOTE_HTML}]
    fresh = _make_episode(slug="fresh-conversion", detail_children=legacy_detail)
    existing = _make_episode(slug="existing-conversion", detail_children=legacy_detail)
    _run("--slug", existing.slug, "--apply")
    failed = _make_episode(slug="failed-conversion", detail_children=legacy_detail)
    unchanged = _make_episode(slug="unchanged-conversion", detail_children=None)
    slugs = [fresh.slug, existing.slug, failed.slug, unchanged.slug]
    if with_conflict:
        conflict = _make_episode(slug="conflicted-conversion", detail_children=legacy_detail)
        conflict.title = "Pending synthetic edit"
        conflict.save_revision()
        slugs.append(conflict.slug)
    original_save = Episode.save_revision

    def save_revision(self, *args, **kwargs):
        revision = original_save(self, *args, **kwargs)
        if self.pk == failed.pk:
            raise RuntimeError("synthetic rollback")
        return revision

    monkeypatch.setattr(Episode, "save_revision", save_revision)
    output = StringIO()
    selectors = [arg for slug in slugs for arg in ("--slug", slug)]
    with pytest.raises(CommandError, match=r"1 episode\(s\) failed: failed-conversion"):
        call_command("convert_show_notes", "--publish", *selectors, stdout=output)

    report = output.getvalue()
    assert f"Revisions: {1 + with_conflict} created, 2 published." in report
    assert "1 skipped" in report
    assert "1 failed" in report
    assert "Applied and published revisions." not in report
    for episode in (fresh, existing):
        episode.refresh_from_db()
        assert episode.revisions.count() == 1
        assert episode.live_revision_id == episode.latest_revision_id
    assert failed.revisions.count() == unchanged.revisions.count() == 0
    if with_conflict:
        assert "1 not published (conflict)" in report
        conflict.refresh_from_db()
        assert conflict.revisions.count() == 2
        assert conflict.live_revision_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("existing_draft", [False, True])
@pytest.mark.parametrize("outcome", ["published", "scheduled", "unconfirmed"])
def test_publish_receipt_requires_revision_state(monkeypatch, existing_draft, outcome):
    episode = _make_episode(slug="publish-receipt-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    other_revision = episode.save_revision()
    scheduled_at = datetime.now(UTC) + timedelta(days=1)
    Revision.objects.filter(pk=other_revision.pk).update(approved_go_live_at=scheduled_at)
    if existing_draft:
        _run("--slug", episode.slug, "--apply")
    episode.refresh_from_db()
    revision_count = episode.revisions.count()
    submitted = []

    def publish(revision):
        submitted.append(revision.pk)
        if outcome == "published":
            Page.objects.filter(pk=episode.pk).update(live=True, live_revision_id=revision.pk)
        if outcome == "scheduled":
            Revision.objects.filter(pk=revision.pk).update(approved_go_live_at=scheduled_at)

    monkeypatch.setattr(Revision, "publish", publish)
    if outcome == "unconfirmed":
        output, error = _run_expecting_error("--slug", episode.slug, "--publish")
        assert f"publication could not be confirmed: {episode.slug}" in error
    else:
        output = _run("--slug", episode.slug, "--publish")

    episode.refresh_from_db()
    assert submitted == [episode.latest_revision_id]
    assert episode.revisions.count() == revision_count + int(not existing_draft)
    assert f"revision {episode.latest_revision_id}" in output
    assert f"Revisions: {int(not existing_draft)} created, {int(outcome == 'published')} published." in output
    assert ("1 scheduled" in output) == (outcome == "scheduled")
    assert ("publication unconfirmed" in output) == (outcome == "unconfirmed")


@pytest.mark.django_db
def test_publish_summary_excludes_scheduled_revision():
    episode = _make_episode(
        slug="scheduled-conversion", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}]
    )
    go_live_at = datetime.now(UTC) + timedelta(days=1)
    Episode.objects.filter(pk=episode.pk).update(go_live_at=go_live_at, live=False)

    output = _run("--slug", episode.slug, "--publish")

    episode.refresh_from_db()
    assert episode.live_revision_id is None
    assert episode.get_latest_revision().approved_go_live_at is not None
    assert "Revisions: 1 created, 0 published." in output


@pytest.mark.django_db(transaction=True)
def test_followup_failure_reports_scheduled_publication(monkeypatch):
    episode = _make_episode(
        slug="scheduled-callback-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}]
    )
    Episode.objects.filter(pk=episode.pk).update(go_live_at=datetime.now(UTC) + timedelta(days=1), live=False)
    original_publish = Revision.publish

    def fail_after_commit():
        raise RuntimeError("synthetic private callback detail")

    def publish(self, *args, **kwargs):
        transaction.on_commit(fail_after_commit)
        return original_publish(self, *args, **kwargs)

    monkeypatch.setattr(Revision, "publish", publish)
    output = StringIO()
    with pytest.raises(CommandError):
        call_command("convert_show_notes", "--slug", episode.slug, "--publish", stdout=output)

    episode.refresh_from_db()
    assert episode.live_revision_id is None
    assert f"committed (revision {episode.latest_revision_id}, publication scheduled)" in output.getvalue()
    assert "Revisions: 1 created, 0 published." in output.getvalue()


@pytest.mark.django_db
def test_publish_accepts_reviewed_detail_edit_in_conversion_draft():
    episode = _make_episode(
        slug="reviewed-detail-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "reviewed-detail-ep", "--apply")
    draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
    raw = [dict(block) for block in draft.body.raw_data]
    for block in raw:
        if block["type"] == "detail":
            block["value"] = [*block["value"], {"type": "paragraph", "value": "<p>reviewed</p>"}]
    draft.body = draft.body.stream_block.to_python(raw)
    draft.save_revision()

    _run("--slug", "reviewed-detail-ep", "--publish")

    live = Episode.objects.get(pk=episode.pk)
    assert "show_note_link_list" in _detail_types(live)
    assert _detail_types(live)[-1] == "paragraph"
    assert not live.has_unpublished_changes


@pytest.mark.django_db
def test_publish_accepts_detail_section_rebuilt_with_a_new_block_id():
    episode = _make_episode(
        slug="rebuilt-detail-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "rebuilt-detail-ep", "--apply")
    draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
    raw = [dict(block) for block in draft.body.raw_data]
    live_ids = [block.get("id") for block in Episode.objects.get(pk=episode.pk).body.raw_data]
    for block in raw:
        if block["type"] == "detail":
            block["id"] = "11111111-2222-3333-4444-555555555555"
    draft.body = draft.body.stream_block.to_python(raw)
    draft.save_revision()

    _run("--slug", "rebuilt-detail-ep", "--publish")

    live = Episode.objects.get(pk=episode.pk)
    assert "show_note_link_list" in _detail_types(live)
    assert [block.get("id") for block in live.body.raw_data] != live_ids
    assert not live.has_unpublished_changes


@pytest.mark.django_db
def test_publish_refuses_draft_that_reorders_sections():
    episode = _make_episode(
        slug="reordered-ep",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    _run("--slug", "reordered-ep", "--apply")
    draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
    raw = [dict(block) for block in draft.body.raw_data]
    draft.body = draft.body.stream_block.to_python(list(reversed(raw)))
    draft.save_revision()

    output, _ = _run_expecting_conflict("--slug", "reordered-ep", "--publish")

    assert [block["type"] for block in Episode.objects.get(pk=episode.pk).body.raw_data] == ["overview", "detail"]
    assert "body outside the detail section" in output


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
def test_force_reports_history_beyond_legacy_search_limit():
    from python_podcast.pp.management.commands.convert_show_notes import Command

    episode = _make_episode(slug="deep-history-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    legacy = episode.save_revision()
    _run("--slug", episode.slug, "--publish")
    published = Episode.objects.get(pk=episode.pk).live_revision
    Revision.objects.bulk_create(
        [
            Revision(
                content_type_id=published.content_type_id,
                base_content_type_id=published.base_content_type_id,
                object_id=published.object_id,
                created_at=published.created_at,
                content=published.content,
            )
            for _ in range(99)
        ]
    )

    with patch.object(Command, "_already_converted", wraps=Command._already_converted) as inspected:
        output, error = _run_expecting_error("--slug", episode.slug, "--force", "--publish")

    assert "legacy revision search limit reached (100 revisions)" in output
    assert "1 failed" in output
    assert episode.slug in error
    assert inspected.call_count == 101  # Live body and the 100 allowed revision bodies.
    stored = Episode.objects.get(pk=episode.pk)
    assert stored.live_revision_id == stored.latest_revision_id == published.pk
    assert stored.revisions.count() == 101

    legacy_page = legacy.as_object()
    legacy.delete()
    output = _run("--slug", episode.slug, "--force", "--publish")
    assert "skipped: no legacy body to re-convert" in output
    assert stored.revisions.count() == 100

    # The documented recovery: save the legacy body as a new revision.
    current = Episode.objects.get(pk=episode.pk)
    current.body = legacy_page.body
    restored = current.save_revision()
    output = _run("--slug", episode.slug, "--force", "--apply")
    assert f"source: revision {restored.pk}" in output
    stored = Episode.objects.get(pk=episode.pk)
    assert "show_note_link_list" in _detail_types(stored.get_latest_revision_as_object())


@pytest.mark.django_db
def test_slug_filter_limits_scope():
    _make_episode(slug="target-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}], num=1)
    other = _make_episode(slug="other-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}], num=2)

    _run("--slug", "target-ep", "--apply")

    assert other.revisions.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("mode", [(), ("--apply",), ("--publish",)])
def test_unknown_explicit_slugs_refuse_the_entire_selection(mode):
    episode = _make_episode(slug="selected-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])

    output, error = _run_expecting_error("--slug", episode.slug, "--slug", "typo-ep", *mode)

    assert "Unknown episode slug(s): typo-ep" in error
    assert not output
    assert episode.revisions.count() == 0
    assert _detail_types(Episode.objects.get(pk=episode.pk)) == ["paragraph"]

    _run("--slug", episode.slug, "--apply")
    assert episode.revisions.count() == 1


@pytest.mark.django_db
def test_invalid_slug_preflight_reads_only_identities():
    slugs = [
        _make_episode(
            slug=f"large-{number}",
            num=number,
            detail_children=[{"type": "paragraph", "value": "synthetic " * 10000}],
        ).slug
        for number in range(8)
    ]
    selectors = [value for slug in [*slugs, "typo-ep"] for value in ("--slug", slug)]
    statements = []

    def record_sql(execute, sql, params, many, context):
        statements.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(record_sql):
        output, error = _run_expecting_error("--apply", *selectors)

    assert not output
    assert "Unknown episode slug(s): typo-ep" in error
    selects = [sql for sql in statements if sql.startswith("SELECT") and f'"{Episode._meta.db_table}"' in sql]
    assert len(selects) == 1
    assert f'"{Episode._meta.get_field("body").column}"' not in selects[0]
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)


@pytest.mark.django_db
@pytest.mark.parametrize("mode", [(), ("--apply",), ("--publish",)])
def test_ambiguous_explicit_slug_refuses_the_entire_selection(mode):
    children = [{"type": "paragraph", "value": SHOWNOTE_HTML}]
    unique = _make_episode(slug="unique-ep", detail_children=children)
    first = _make_episode(slug="shared-ep", detail_children=children)
    second = _make_episode(slug=first.slug, detail_children=children, podcast_slug="another-podcast")

    output, error = _run_expecting_error("--slug", unique.slug, "--slug", first.slug, *mode)

    assert f"Ambiguous episode slug(s): shared-ep (IDs: {first.pk}, {second.pk})" in error
    assert not output
    for episode in (unique, first, second):
        assert episode.revisions.count() == 0

    # Repeating an unambiguous selector still processes the one matching page once.
    _run("--slug", unique.slug, "--slug", unique.slug, "--apply")
    assert unique.revisions.count() == 1


RICH_SHOWNOTE_HTML = (
    "<h2>Shownotes</h2>"
    "<h3>News</h3><ul>"
    '<li><a href="https://example.com/a">Article A</a> | plain note</li>'
    '<li><strong>Wichtig:</strong> <a href="https://example.com/sec">Security Release</a> | '
    "<code>pip install -U django</code></li>"
    "</ul>"
    '<h3><img alt="Werbung" src="https://example.com/sponsor.png"/> Werbung</h3>'
    '<ul><li><a href="https://example.com/sponsor">Sponsor</a></li></ul>'
)


def _detail_children(page):
    for block in page.body.raw_data:
        if block["type"] == "detail":
            return block["value"]
    return None


@pytest.mark.django_db
def test_apply_persists_unrepresentable_markup_in_the_revision():
    episode = _make_episode(slug="rich-ep", detail_children=[{"type": "paragraph", "value": RICH_SHOWNOTE_HTML}])

    output = _run("--slug", "rich-ep", "--apply")

    children = _detail_children(_latest_revision_object(episode))
    assert [child["type"] for child in children] == [
        "show_note_heading",
        "show_note_heading",
        "show_note_link_list",
        "paragraph",
        "paragraph",
    ]
    items = children[2]["value"]["items"]
    assert [(item["title"], item["note"]) for item in items] == [("Article A", "plain note")]
    # The formatted item and the heading with its image are stored unchanged.
    assert children[3]["value"] == (
        '<ul><li><strong>Wichtig:</strong> <a href="https://example.com/sec">Security Release</a> | '
        "<code>pip install -U django</code></li></ul>"
    )
    assert children[4]["value"] == (
        '<h3><img alt="Werbung" src="https://example.com/sponsor.png"/> Werbung</h3>'
        '<ul><li><a href="https://example.com/sponsor">Sponsor</a></li></ul>'
    )
    assert output.count("warning:") == 2
    assert "Heading contains <img>" in output


# Edits saved while the command is running


def _run_expecting_error(*args):
    out = StringIO()
    with pytest.raises(CommandError) as error:
        call_command("convert_show_notes", *args, stdout=out, stderr=out)
    return out.getvalue(), str(error.value)


def _edit_after(monkeypatch, name, edit, *, slug):
    """Run ``edit`` once, right after the command's ``name`` step for the episode ``slug``.

    At that point the command has read the episode and computed what it is going
    to write, but has not written anything yet.
    """
    from python_podcast.pp.management.commands.convert_show_notes import Command

    original = getattr(Command, name)
    is_static = isinstance(inspect.getattr_static(Command, name), staticmethod)
    pending = [edit]

    def step_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        if pending and Episode.objects.filter(slug=slug).exists():
            pending.pop()()
        return result

    monkeypatch.setattr(Command, name, staticmethod(step_then_edit) if is_static else step_then_edit)


EDITOR_DETAIL = [{"type": "paragraph", "value": "<p>Editor rewrote the detail.</p>"}]


def _editor_saves_detail(episode, *, publish=False):
    """What the Wagtail editor does: a fresh page object, a detail-only change, a new revision."""

    def edit():
        draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
        raw = [
            {**block, "value": EDITOR_DETAIL} if block["type"] == "detail" else block for block in draft.body.raw_data
        ]
        draft.body = draft.body.stream_block.to_python(raw)
        revision = draft.save_revision()
        if publish:
            revision.publish()

    return edit


def _detail_values(page):
    return [child.value.source for block in page.body if block.block_type == "detail" for child in block.value]


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["--apply", "--publish"])
def test_detail_edit_saved_during_conversion_is_not_replaced(monkeypatch, mode):
    episode = _make_episode(slug="race-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _edit_after(monkeypatch, "_convert_top", _editor_saves_detail(episode), slug="race-ep")

    output, error = _run_expecting_error("--slug", "race-ep", mode)

    stored = Episode.objects.get(pk=episode.pk)
    # The editor's revision is the only one and still the latest; nothing went live.
    assert stored.revisions.count() == 1
    assert _detail_values(stored.get_latest_revision_as_object()) == ["<p>Editor rewrote the detail.</p>"]
    assert _detail_types(stored) == ["paragraph"]
    assert _detail_values(stored) == [SHOWNOTE_HTML]
    assert stored.has_unpublished_changes is True
    assert "conflict: not converted, the episode changed while the command was running" in output
    assert "1 changed during the run (conflict)" in output
    assert "race-ep" in error
    assert "changed while the command was running" in error


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["--apply", "--publish"])
def test_detail_edit_published_during_conversion_is_not_replaced(monkeypatch, mode):
    episode = _make_episode(slug="race-live-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _edit_after(monkeypatch, "_convert_top", _editor_saves_detail(episode, publish=True), slug="race-live-ep")

    _output, error = _run_expecting_error("--slug", "race-live-ep", mode)

    stored = Episode.objects.get(pk=episode.pk)
    assert stored.revisions.count() == 1
    assert _detail_values(stored) == ["<p>Editor rewrote the detail.</p>"]
    assert stored.has_unpublished_changes is False
    assert "race-live-ep" in error


@pytest.mark.django_db
def test_force_does_not_replace_detail_edit_saved_during_conversion(monkeypatch):
    episode = _make_episode(slug="race-force-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _run("--slug", "race-force-ep", "--apply")
    _edit_after(monkeypatch, "_convert_top", _editor_saves_detail(episode), slug="race-force-ep")

    _output, error = _run_expecting_error("--slug", "race-force-ep", "--apply", "--force")

    stored = Episode.objects.get(pk=episode.pk)
    assert stored.revisions.count() == 2
    assert _detail_values(stored.get_latest_revision_as_object()) == ["<p>Editor rewrote the detail.</p>"]
    assert "race-force-ep" in error


@pytest.mark.django_db
def test_existing_conversion_draft_edited_during_publish_is_not_published(monkeypatch):
    episode = _make_episode(slug="race-draft-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _run("--slug", "race-draft-ep", "--apply")
    conversion_revision = Episode.objects.get(pk=episode.pk).latest_revision_id
    _edit_after(monkeypatch, "_unrelated_draft_changes", _editor_saves_detail(episode), slug="race-draft-ep")

    output, error = _run_expecting_error("--slug", "race-draft-ep", "--publish")

    stored = Episode.objects.get(pk=episode.pk)
    assert stored.revisions.count() == 2
    assert stored.latest_revision_id != conversion_revision
    # Neither the conversion draft nor the editor's newer draft went live.
    assert stored.live_revision_id is None
    assert _detail_values(stored) == [SHOWNOTE_HTML]
    assert "conflict: not converted" in output
    assert "race-draft-ep" in error


@pytest.mark.django_db
def test_episode_deleted_during_conversion_is_reported(monkeypatch):
    episode = _make_episode(slug="race-gone-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _edit_after(monkeypatch, "_convert_top", lambda: Episode.objects.get(pk=episode.pk).delete(), slug="race-gone-ep")

    _output, error = _run_expecting_error("--slug", "race-gone-ep", "--apply")

    assert not Episode.objects.filter(pk=episode.pk).exists()
    assert "race-gone-ep" in error


@pytest.mark.django_db
def test_edit_conflict_does_not_block_other_episodes(monkeypatch):
    raced = _make_episode(slug="race-first-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    other = _make_episode(
        slug="race-second-ep", num=2, detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}]
    )
    _edit_after(monkeypatch, "_convert_top", _editor_saves_detail(raced), slug="race-first-ep")

    output, error = _run_expecting_error("--slug", "race-first-ep", "--slug", "race-second-ep", "--publish")

    assert _detail_values(Episode.objects.get(pk=raced.pk)) == [SHOWNOTE_HTML]
    assert "show_note_link_list" in _detail_types(Episode.objects.get(pk=other.pk))
    assert "Summary: 1 changed, 1 skipped, 0 with warnings, 1 changed during the run (conflict)" in output
    assert "race-first-ep" in error
    assert "race-second-ep" not in error


@pytest.mark.django_db
def test_dry_run_reports_conversion_of_unchanged_episode_without_locking(monkeypatch):
    from python_podcast.pp.management.commands.convert_show_notes import Command

    _make_episode(slug="race-dry-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    monkeypatch.setattr(Command, "_locked_unchanged", None)

    output = _run("--slug", "race-dry-ep")

    assert "would change (dry run)" in output


@pytest.mark.django_db
def test_episode_with_a_draft_deleted_before_it_is_read_is_reported(monkeypatch):
    """The batch holds the episode as loaded; its latest revision is gone when it is read."""
    from python_podcast.pp.management.commands.convert_show_notes import Command

    gone = _make_episode(slug="race-deleted-draft-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _save_overview_draft(gone)
    other = _make_episode(
        slug="race-survivor-ep", num=2, detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}]
    )
    take_snapshot = Command._snapshot
    pending = [gone.pk]

    def delete_then_snapshot(self, episode):
        if pending and episode.pk == pending[0]:
            Episode.objects.get(pk=pending.pop()).delete()
        return take_snapshot(self, episode)

    monkeypatch.setattr(Command, "_snapshot", delete_then_snapshot)

    output, error = _run_expecting_error("--apply")

    assert not Episode.objects.filter(pk=gone.pk).exists()
    assert "show_note_link_list" in _detail_types(_latest_revision_object(other))
    assert "1 changed during the run (conflict)" in output
    assert "race-deleted-draft-ep" in error and "race-survivor-ep" not in error


def _editor_overwrites_draft_in_another_transaction(episode, *, revision_locked, release, errors):
    """An autosave in the Wagtail editor: it rewrites the latest revision, then updates the page.

    Runs in its own thread and therefore on its own database connection. After
    the revision row is written (and locked) it waits for ``release``.
    """
    save_page = Episode.save

    def pause_after_the_revision_is_written(self, *args, **kwargs):
        # ``save_revision`` writes the revision row first and the page row second.
        if threading.current_thread() is editor:
            revision_locked.set()
            release.wait(timeout=5)
        return save_page(self, *args, **kwargs)

    def save():
        try:
            with patch.object(Episode, "save", pause_after_the_revision_is_written):
                with transaction.atomic():
                    stored = Episode.objects.get(pk=episode.pk)
                    draft = stored.get_latest_revision_as_object()
                    draft.title = "Editor autosave"
                    draft.save_revision(overwrite_revision=stored.latest_revision, clean=False)
        except Exception as exc:  # noqa: BLE001 - reported to the test
            errors.append(exc)
        finally:
            revision_locked.set()
            connection.close()

    editor = threading.Thread(target=save)
    return editor


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("args", [("--publish",), ("--apply", "--force"), ("--publish", "--force")])
def test_editor_overwriting_the_draft_is_neither_blocked_nor_rolled_back(args):
    """Two real transactions: the command must not wait for the editor's revision lock."""
    episode = _make_episode(slug="race-lock-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    _run("--slug", "race-lock-ep", "--apply")
    conversion_revision = Episode.objects.get(pk=episode.pk).latest_revision_id
    revision_locked, release, errors = threading.Event(), threading.Event(), []
    editor = _editor_overwrites_draft_in_another_transaction(
        episode, revision_locked=revision_locked, release=release, errors=errors
    )
    editor.start()
    try:
        assert revision_locked.wait(timeout=10)
        assert errors == []

        output, error = _run_expecting_error("--slug", "race-lock-ep", *args)
    finally:
        release.set()
        editor.join(timeout=20)

    assert not editor.is_alive()
    # The editor's save went through: no deadlock victim, no lost edit.
    assert errors == []
    stored = Episode.objects.get(pk=episode.pk)
    assert stored.latest_revision_id == conversion_revision
    assert stored.revisions.count() == 1
    assert stored.get_latest_revision_as_object().title == "Editor autosave"
    # The command wrote nothing and published nothing.
    assert stored.live_revision_id is None
    assert _detail_values(stored) == [SHOWNOTE_HTML]
    assert "conflict: not converted" in output
    assert "race-lock-ep" in error


@pytest.mark.django_db(transaction=True)
def test_editor_save_waits_for_the_conversion_and_then_completes():
    """The other direction: the command holds the locks, an editor save arrives meanwhile."""
    from python_podcast.pp.management.commands.convert_show_notes import Command

    episode = _make_episode(slug="race-wait-ep", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    errors, started = [], threading.Event()

    def editor_saves_draft():
        try:
            started.set()
            draft = Episode.objects.get(pk=episode.pk).get_latest_revision_as_object()
            draft.title = "Saved after the conversion"
            draft.save_revision(clean=False)
        except Exception as exc:  # noqa: BLE001 - reported to the test
            errors.append(exc)
        finally:
            connection.close()

    editor = threading.Thread(target=editor_saves_draft)
    command = Command()
    stored = Episode.objects.get(pk=episode.pk)
    with command._locked_unchanged(stored, command._snapshot(stored)) as current:
        assert current is not None
        editor.start()
        assert started.wait(timeout=10)
        editor.join(timeout=1)
        # The editor's page update is waiting for the lock held here.
        assert editor.is_alive()
    editor.join(timeout=20)

    assert not editor.is_alive()
    assert errors == []
    assert Episode.objects.get(pk=episode.pk).get_latest_revision_as_object().title == "Saved after the conversion"


@pytest.mark.django_db
@pytest.mark.parametrize("explicit", [False, True])
def test_iteration_keeps_episode_hydration_bounded(monkeypatch, explicit):
    import gc
    import weakref

    from python_podcast.pp.management.commands import convert_show_notes

    identities = [
        _make_episode(
            slug=f"bounded-{number}",
            num=number,
            detail_children=[{"type": "paragraph", "value": "synthetic " * 10000}],
        )
        for number in range(8)
    ]
    hydrated = weakref.WeakSet()
    original = Episode.from_db

    def from_db(cls, *args, **kwargs):
        episode = original(*args, **kwargs)
        hydrated.add(episode)
        return episode

    seen_pks = []

    def process(self, episode, **kwargs):
        gc.collect()
        assert len(hydrated) <= 3, "selection retained more than a batch of episode bodies"
        seen_pks.append(episode.pk)
        return convert_show_notes.EpisodeResult(episode.slug, episode.pk, "skipped")

    monkeypatch.setattr(Episode, "from_db", classmethod(from_db))
    monkeypatch.setattr(convert_show_notes, "EPISODE_BATCH_SIZE", 2)
    monkeypatch.setattr(convert_show_notes.Command, "_process_episode", process)
    selectors = [value for episode in reversed(identities) for value in ("--slug", episode.slug)] if explicit else []
    assert "8 skipped" in _run(*selectors)
    assert seen_pks == [episode.pk for episode in identities]


@pytest.mark.django_db
def test_archive_selection_closes_each_cursor_and_respects_initial_horizon(monkeypatch):
    from python_podcast.pp.management.commands import convert_show_notes

    initial_pks = [_make_episode(slug=f"archive-{number}", detail_children=None).pk for number in range(5)]
    open_cursors = set()
    selection_queries = []
    seen_pks = []
    open_during_conversion = []

    def track_selection(execute, sql, params, many, context):
        if sql.startswith("SELECT") and f'"{Episode._meta.db_table}"' in sql:
            cursor = context["cursor"]
            close_cursor = cursor.close
            open_cursors.add(cursor)
            selection_queries.append(sql)

            def close():
                open_cursors.remove(cursor)
                return close_cursor()

            cursor.close = close
        return execute(sql, params, many, context)

    def process(self, episode, **kwargs):
        seen_pks.append(episode.pk)
        open_during_conversion.append(len(open_cursors))
        if len(seen_pks) == 2:
            selected_before_insert = len(selection_queries)
            late = _make_episode(slug="archive-late", detail_children=None)
            assert late.pk > initial_pks[-1]
            del selection_queries[selected_before_insert:]
        return convert_show_notes.EpisodeResult(episode.slug, episode.pk, "skipped")

    monkeypatch.setattr(convert_show_notes, "EPISODE_BATCH_SIZE", 2)
    monkeypatch.setattr(convert_show_notes.Command, "_process_episode", process)
    with connection.execute_wrapper(track_selection):
        _run()

    assert open_during_conversion == [0] * len(seen_pks)
    assert seen_pks == initial_pks
    assert sum("LIMIT 2" in sql for sql in selection_queries) == 3


@pytest.mark.django_db
def test_force_uses_stable_revision_identity_and_content_receipt():
    import hashlib

    episode = _make_episode(slug="stable-source", detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}])
    first = episode.save_revision()
    raw = list(episode.body.raw_data)
    # Non-ASCII content: the documented canonical form is UTF-8 JSON, not \u escapes.
    raw[1]["value"][0]["value"] = SHOWNOTE_HTML.replace("Article A", "Neuester synthetischer Ärtikel – ü")
    episode.body = episode.body.stream_block.to_python(raw)
    second = episode.save_revision()
    episode.revisions.filter(pk=second.pk).update(created_at=first.created_at)
    _run("--slug", episode.slug, "--publish")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert "Ärtikel" in canonical
    expected_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    for flags in [(), (), ("--apply",), ()]:
        output = _run("--slug", episode.slug, "--force", *flags)
        assert f"source: revision {second.pk}, sha256={expected_digest}" in output


@pytest.mark.django_db
def test_failure_emits_committed_progress_and_continues_independent_episodes(monkeypatch):
    from python_podcast.pp.management.commands.convert_show_notes import Command

    episodes = [
        _make_episode(
            slug=f"receipt-{number}", num=number, detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}]
        )
        for number in range(3)
    ]
    original = Command._process_episode
    original_save = Episode.save_revision
    output = StringIO()

    def process(self, episode, **kwargs):
        if episode.pk == episodes[1].pk:
            committed = Episode.objects.get(pk=episodes[0].pk).latest_revision_id
            assert f"revision {committed}" in output.getvalue(), "receipt was buffered beyond its transaction"
        return original(self, episode, **kwargs)

    def save_revision(self, *args, **kwargs):
        revision = original_save(self, *args, **kwargs)
        if self.pk == episodes[1].pk:
            raise RuntimeError("synthetic private failure detail must not be printed")
        return revision

    monkeypatch.setattr(Episode, "save_revision", save_revision)
    monkeypatch.setattr(Command, "_process_episode", process)
    with pytest.raises(CommandError, match="receipt-1"):
        call_command("convert_show_notes", "--apply", stdout=output)
    receipt = output.getvalue()
    assert "failed: RuntimeError" in receipt
    assert "1 failed" in receipt
    assert "private failure detail" not in receipt
    assert episodes[0].revisions.count() == 1
    assert episodes[1].revisions.count() == 0
    assert episodes[2].revisions.count() == 1
    monkeypatch.setattr(Command, "_process_episode", original)
    monkeypatch.setattr(Episode, "save_revision", original_save)
    assert "1 changed, 2 skipped" in _run("--apply")


@pytest.mark.django_db
def test_dry_run_report_keeps_block_counts_and_order():
    episode = _make_episode(
        slug="block-order",
        detail_children=[{"type": "paragraph", "value": SHOWNOTE_HTML}, {"type": "paragraph", "value": SHOWNOTE_HTML}],
    )
    episode.save_revision()
    output = _run("--slug", episode.slug)
    assert "  before: paragraph, paragraph" in output
