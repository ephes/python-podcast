"""Convert legacy episode detail shownotes into structured show-note blocks.

The command is conservative and safe to run repeatedly:

* It only rewrites the ``detail`` body section.
* It only converts ``paragraph`` children whose HTML actually contains shownote
  structure; every other child (``image``, ``audio``, ...) is preserved verbatim.
* Ambiguous content is preserved as a paragraph with a warning rather than being
  converted in a lossy way (see ``pp.show_notes.converter``).
* It is idempotent: a detail that already contains ``show_note_*`` blocks is
  skipped.

By default the command performs a dry run and writes nothing. Use ``--apply`` to
create a Wagtail draft revision and ``--publish`` to publish that revision.

``--publish`` only ever puts the conversion live. If the draft differs from the
live page in anything but the ``detail`` section (an overview edit, a changed
title, ...), publishing it would put those unrelated edits live as well. Such an
episode is reported as a conflict: the draft is kept, nothing is published and
the command exits with an error.

A conversion is bound to the page state it was computed from. Before a revision
is saved or published the command locks the page row, reads the episode again
and compares it with that state (latest and live revision, publication flags,
draft and live content). An episode that was edited, published, unpublished or
deleted in between is reported as a conflict: nothing is written for it, the
editor's revision stays the latest one and the command exits with an error. Run
the command again to convert it from its current content.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from cast.models import Episode
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from wagtail.models import Page

from python_podcast.pp.show_notes.converter import ConvertedBlock, convert_paragraph_html

SHOW_NOTE_TYPES = frozenset({"show_note_heading", "show_note_link_list", "show_note_sponsor"})

# Page fields that describe the publication state of the page rather than its
# content. A revision stores the values from the moment it was saved, so they
# legitimately differ from the live row and say nothing about pending edits.
REVISION_BOOKKEEPING_FIELDS = frozenset(
    {
        "live",
        "has_unpublished_changes",
        "first_published_at",
        "last_published_at",
        "live_revision",
        "latest_revision",
        "latest_revision_created_at",
        "draft_title",
        "url_path",
        "path",
        "depth",
        "numchild",
        "locked",
        "locked_at",
        "locked_by",
        "comments",
        "wagtail_admin_comments",
    }
)


@dataclass
class EpisodeResult:
    slug: str
    pk: int
    status: str  # "changed" | "skipped"
    reason: str = ""
    before_types: list[str] = field(default_factory=list)
    after_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    revision_pk: int | None = None
    # Why --publish was refused: the unrelated parts of the draft that differ from live.
    publish_conflict: list[str] = field(default_factory=list)
    # The episode changed between reading it and writing the conversion; nothing was written.
    edit_conflict: bool = False


@dataclass(frozen=True)
class EpisodeSnapshot:
    """The page state a conversion is computed from."""

    latest_revision_id: int | None
    live_revision_id: int | None
    live: bool
    has_unpublished_changes: bool
    draft_content: str
    live_content: str


class Command(BaseCommand):
    help = "Convert legacy episode detail shownotes into structured show-note blocks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes by creating a Wagtail draft revision. Without this flag the command is a dry run.",
        )
        parser.add_argument(
            "--publish",
            action="store_true",
            help=(
                "Publish the created revision. Implies --apply. Refused for an episode whose draft "
                "also contains unpublished changes outside the detail section."
            ),
        )
        parser.add_argument(
            "--slug",
            action="append",
            dest="slugs",
            default=[],
            metavar="SLUG",
            help="Limit conversion to the episode with this slug. May be given multiple times.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Re-convert from the original legacy body (the most recent "
                "unconverted version, taken from revision history if needed), "
                "ignoring the 'already converted' guard. Use to regenerate "
                "conversions after the converter has been improved."
            ),
        )

    def handle(self, *args, **options):
        publish = options["publish"]
        apply = options["apply"] or publish
        force = options["force"]
        slugs = options["slugs"]

        episodes = Episode.objects.all()
        if slugs:
            episodes = episodes.filter(slug__in=slugs)
        episodes = episodes.order_by("pk")

        results = [self._process_episode(episode, apply=apply, publish=publish, force=force) for episode in episodes]

        for result in results:
            self._report(result)

        self._report_summary(results, apply=apply, publish=publish)

        errors = []
        conflicts = [result.slug for result in results if result.publish_conflict]
        if conflicts:
            errors.append(
                f"{len(conflicts)} episode(s) were not published because their draft contains unrelated "
                f"unpublished changes: {', '.join(conflicts)}. Nothing was published for them and their pending "
                "edits are kept; review and publish the drafts in the Wagtail admin."
            )
        edit_conflicts = [result.slug for result in results if result.edit_conflict]
        if edit_conflicts:
            errors.append(
                f"{len(edit_conflicts)} episode(s) changed while the command was running and were left "
                f"untouched: {', '.join(edit_conflicts)}. Nothing was written for them; run the command again "
                "to convert them from their current content."
            )
        if errors:
            raise CommandError(" ".join(errors))

    # -- per-episode ----------------------------------------------------
    def _process_episode(self, episode: Episode, *, apply: bool, publish: bool, force: bool) -> EpisodeResult:
        # The detail conversion source: normally the latest revision (the current
        # draft) so the command stays idempotent; with --force, the original
        # legacy body (most recent unconverted version) so a previously converted
        # episode can be regenerated by an improved converter.
        #
        # Everything below is computed from the episode as it is now. The snapshot
        # identifies that state; it is checked again, under the page lock, before
        # anything is written.
        snapshot = self._snapshot(episode) if apply else None
        if force:
            raw_top = self._legacy_raw_top(episode)
            if raw_top is None:
                return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no legacy body to re-convert")
        else:
            raw_top = episode.get_latest_revision_as_object().body.raw_data
        detail_blocks = [block for block in raw_top if block["type"] == "detail"]

        if not detail_blocks:
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no detail section")

        if not force and self._already_converted(detail_blocks):
            # The latest draft is already converted. When publishing, push that
            # draft live -- but only if the live page is still legacy, i.e. the
            # pending change really is our conversion and not an unrelated draft.
            live_detail = [block for block in episode.body.raw_data if block["type"] == "detail"]
            live_converted = bool(live_detail) and self._already_converted(live_detail)
            if publish and episode.has_unpublished_changes and not live_converted:
                revision = episode.get_latest_revision()
                unrelated = self._unrelated_draft_changes(episode, revision.as_object())
                if unrelated:
                    # A later edit was saved on top of the conversion draft (or the
                    # conversion was applied on top of a pending edit). Publishing the
                    # latest revision would put that edit live too.
                    return EpisodeResult(
                        episode.slug,
                        episode.pk,
                        "skipped",
                        reason="converted draft not published",
                        revision_pk=revision.pk,
                        publish_conflict=unrelated,
                    )
                with self._locked_unchanged(episode, snapshot) as current:
                    if current is None:
                        return self._edit_conflict(episode)
                    current.get_latest_revision().publish()
                return EpisodeResult(
                    episode.slug,
                    episode.pk,
                    "changed",
                    reason="published existing converted draft",
                    revision_pk=revision.pk,
                )
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="already converted")

        before_types = [child["type"] for block in detail_blocks for child in block["value"]]

        new_top, after_types, warnings, changed = self._convert_top(raw_top)
        if not changed:
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no convertible shownote HTML")

        result = EpisodeResult(
            episode.slug,
            episode.pk,
            "changed",
            before_types=before_types,
            after_types=after_types,
            warnings=warnings,
        )

        if apply:
            # Always edit the latest-revision object so other unpublished draft
            # changes (overview edits, page fields) are preserved. Only the
            # detail section is swapped in -- with --force the converted detail
            # comes from the legacy body while everything else stays current.
            #
            # The conversion was computed from the snapshot. It is written only if
            # the episode, read again under its row lock, is still in that state:
            # a detail edit saved in the meantime is never replaced by the older
            # conversion, and nothing is merged into or recomputed from it here.
            with self._locked_unchanged(episode, snapshot) as current:
                if current is None:
                    return self._edit_conflict(episode)
                target = current.get_latest_revision_as_object()
                # Checked before the conversion is merged in: whatever differs from the
                # live page now is somebody else's pending edit.
                unrelated = self._unrelated_draft_changes(current, target) if publish else []
                merged_top = self._merge_detail(target.body.raw_data, new_top)
                target.body = target.body.stream_block.to_python(merged_top)
                revision = target.save_revision()
                result.revision_pk = revision.pk
                if unrelated:
                    result.publish_conflict = unrelated
                elif publish:
                    revision.publish()

        return result

    # -- concurrent edits -----------------------------------------------
    @staticmethod
    def _content(page: Episode) -> str:
        # Normalised the way a revision stores it, so the same content compares
        # equal whether it comes from the page row or from a revision.
        return json.dumps(page.serializable_data(), cls=DjangoJSONEncoder, sort_keys=True)

    def _snapshot(self, episode: Episode) -> EpisodeSnapshot:
        """Identify the state of ``episode``: its revision pointers, flags and content."""
        return EpisodeSnapshot(
            latest_revision_id=episode.latest_revision_id,
            live_revision_id=episode.live_revision_id,
            live=episode.live,
            has_unpublished_changes=episode.has_unpublished_changes,
            draft_content=self._content(episode.get_latest_revision_as_object()),
            live_content=self._content(episode),
        )

    @contextmanager
    def _locked_unchanged(self, episode: Episode, snapshot: EpisodeSnapshot):
        """Yield the current episode while holding its row lock, or ``None`` on a conflict.

        Saving a draft or publishing in the editor updates the page row. Holding
        the lock until the block ends makes those wait, and reading the episode
        again under the lock sees every edit committed since ``snapshot`` was
        taken. ``None`` is yielded when the episode no longer exists or is not in
        the snapshot's state any more; the caller must then write nothing.
        """
        with transaction.atomic():
            if Page.objects.select_for_update().filter(pk=episode.pk).first() is None:
                yield None
                return
            current = Episode.objects.filter(pk=episode.pk).first()
            if current is None or self._snapshot(current) != snapshot:
                yield None
                return
            yield current

    @staticmethod
    def _edit_conflict(episode: Episode) -> EpisodeResult:
        return EpisodeResult(
            episode.slug,
            episode.pk,
            "skipped",
            reason="changed while the command was running",
            edit_conflict=True,
        )

    @staticmethod
    def _unrelated_draft_changes(episode: Episode, draft: Episode) -> list[str]:
        """Name what differs between the live page and ``draft`` outside the detail section.

        An empty list means publishing ``draft`` changes nothing but the detail
        section, so it is safe to publish as "the conversion".
        """

        def content(page: Episode) -> dict:
            # Normalise the way a revision stores it (e.g. datetimes lose their
            # microseconds), otherwise an untouched field looks changed.
            return json.loads(json.dumps(page.serializable_data(), cls=DjangoJSONEncoder))

        live_data = content(episode)
        draft_data = content(draft)
        ignored = REVISION_BOOKKEEPING_FIELDS | {"body"}
        changed = sorted(
            key
            for key in live_data.keys() | draft_data.keys()
            if key not in ignored and live_data.get(key) != draft_data.get(key)
        )

        def outside_detail(raw: list[dict]) -> list[dict]:
            # A detail section is only a placeholder that keeps the section order.
            # Its block id is ignored too: rebuilding the section in the editor
            # gives it a new id without changing anything outside of it.
            return [{"type": "detail"} if block["type"] == "detail" else block for block in raw]

        if outside_detail(list(episode.body.raw_data)) != outside_detail(list(draft.body.raw_data)):
            changed.append("body outside the detail section")
        return changed

    @staticmethod
    def _merge_detail(target_raw: list[dict], converted_top: list[dict]) -> list[dict]:
        """Splice the converted detail block(s) into the target's current body.

        Non-detail blocks (``overview`` etc.) are taken from ``target_raw`` so
        they are never reverted, even when the conversion source is an older
        revision (``--force``).
        """
        converted_details = [block for block in converted_top if block["type"] == "detail"]
        merged: list[dict] = []
        index = 0
        for block in target_raw:
            if block["type"] == "detail" and index < len(converted_details):
                converted = converted_details[index]
                merged.append({"type": "detail", "value": converted["value"], "id": block.get("id")})
                index += 1
            else:
                merged.append(block)
        return merged

    @staticmethod
    def _already_converted(detail_blocks: list[dict]) -> bool:
        return any(child["type"] in SHOW_NOTE_TYPES for block in detail_blocks for child in block["value"])

    def _legacy_raw_top(self, episode: Episode) -> list[dict] | None:
        """Return the most recent body that has not yet been converted.

        Prefers the live body when it is still legacy, otherwise scans revisions
        newest-first for the last version whose detail has no ``show_note_*``
        blocks. Returns ``None`` if every version is already converted.
        """
        live = episode.body.raw_data
        live_detail = [block for block in live if block["type"] == "detail"]
        if live_detail and not self._already_converted(live_detail):
            return live

        for revision in episode.revisions.order_by("-created_at"):
            body = revision.content.get("body")
            if body is None:
                continue
            raw = json.loads(body) if isinstance(body, str) else body
            detail = [block for block in raw if block["type"] == "detail"]
            if detail and not self._already_converted(detail):
                return raw
        return None

    def _convert_top(self, raw_top: list[dict]) -> tuple[list[dict], list[str], list[str], bool]:
        new_top: list[dict] = []
        after_types: list[str] = []
        warnings: list[str] = []
        changed = False

        for block in raw_top:
            if block["type"] != "detail":
                new_top.append(block)
                continue

            new_children: list[dict] = []
            for child in block["value"]:
                if child["type"] != "paragraph":
                    new_children.append(child)
                    continue

                conversion = convert_paragraph_html(child["value"])
                if not conversion.changed:
                    new_children.append(child)
                    continue

                changed = True
                warnings.extend(conversion.warnings)
                for converted in conversion.blocks:
                    new_children.append(self._raw_block(converted))

            after_types.extend(grandchild["type"] for grandchild in new_children)
            new_top.append({"type": "detail", "value": new_children, "id": block.get("id")})

        return new_top, after_types, warnings, changed

    @staticmethod
    def _raw_block(converted: ConvertedBlock) -> dict:
        return {"type": converted.type, "value": converted.value, "id": uuid.uuid4().hex}

    # -- reporting ------------------------------------------------------
    def _report(self, result: EpisodeResult) -> None:
        self.stdout.write(f"Episode {result.slug} (pk={result.pk})")
        if result.publish_conflict:
            if result.before_types:
                self.stdout.write(f"  before: {', '.join(result.before_types) or '(empty)'}")
                self.stdout.write(f"  after:  {', '.join(result.after_types) or '(empty)'}")
                for warning in result.warnings:
                    self.stdout.write(f"  warning: {warning}")
                self.stdout.write(f"  -> changed (draft revision {result.revision_pk})")
            self.stdout.write(
                f"  -> conflict: not published, the draft (revision {result.revision_pk}) also changes "
                f"{', '.join(result.publish_conflict)}"
            )
            return

        if result.edit_conflict:
            self.stdout.write(
                "  -> conflict: not converted, the episode changed while the command was running; "
                "nothing was written"
            )
            return

        if result.status == "skipped":
            self.stdout.write(f"  -> skipped: {result.reason}")
            return

        if not result.before_types and result.reason:
            # e.g. publishing an existing converted draft.
            self.stdout.write(f"  -> {result.reason} (revision {result.revision_pk})")
            return

        self.stdout.write(f"  before: {', '.join(result.before_types) or '(empty)'}")
        self.stdout.write(f"  after:  {', '.join(result.after_types) or '(empty)'}")
        for warning in result.warnings:
            self.stdout.write(f"  warning: {warning}")
        if result.revision_pk is not None:
            self.stdout.write(f"  -> changed (revision {result.revision_pk})")
        else:
            self.stdout.write("  -> would change (dry run)")

    def _report_summary(self, results: list[EpisodeResult], *, apply: bool, publish: bool) -> None:
        changed = sum(1 for result in results if result.status == "changed")
        skipped = sum(1 for result in results if result.status == "skipped")
        with_warnings = sum(1 for result in results if result.warnings)
        conflicts = sum(1 for result in results if result.publish_conflict)
        edit_conflicts = sum(1 for result in results if result.edit_conflict)

        self.stdout.write("")
        summary = f"Summary: {changed} changed, {skipped} skipped, {with_warnings} with warnings"
        if conflicts:
            summary += f", {conflicts} not published (conflict)"
        if edit_conflicts:
            summary += f", {edit_conflicts} changed during the run (conflict)"
        self.stdout.write(summary)
        if not apply:
            self.stdout.write("Dry run: no changes written. Re-run with --apply to create revisions.")
        elif publish and conflicts:
            self.stdout.write("Applied revisions; published only the episodes without a conflict.")
        elif publish:
            self.stdout.write("Applied and published revisions.")
        else:
            self.stdout.write("Applied: created draft revisions (not published).")
