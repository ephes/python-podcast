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
Both write modes require autocommit on the write database so each episode's
receipt follows its commit.

``--publish`` only ever puts the conversion live. If the draft differs from the
live page in anything but the ``detail`` section (an overview edit, a changed
title, ...), publishing it would put those unrelated edits live as well. Such an
episode is reported as a conflict: the draft is kept, nothing is published and
the command exits with an error.

A conversion is bound to the page state it was computed from. Before a revision
is saved or published the command locks the page row and the rows of the page's
revisions without waiting, reads the episode again and compares it with that
state (latest and live revision, publication flags, draft and live content). An
episode that was edited, published, unpublished or deleted in between, or that
is being saved in the Wagtail admin at that moment, is reported as a conflict:
nothing is written for it, the editor's revision stays the latest one and the
command exits with an error. Run the command again to convert it from its
current content.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from itertools import batched

from cast.models import Episode
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import OperationalError, models, router, transaction
from wagtail.models import Page, Revision

from python_podcast.pp.show_notes.converter import ConvertedBlock, convert_paragraph_html

# PostgreSQL's SQLSTATE for a row lock that NOWAIT could not get.
LOCK_NOT_AVAILABLE = "55P03"

SHOW_NOTE_TYPES = frozenset({"show_note_heading", "show_note_link_list", "show_note_sponsor"})
LEGACY_REVISION_SEARCH_LIMIT = 100
EPISODE_BATCH_SIZE = 20

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


class LegacyRevisionSearchLimitExceeded(Exception):
    """The history continues beyond the allowed legacy source search."""


@dataclass
class EpisodeResult:
    slug: str
    pk: int
    status: str  # "changed" | "skipped" | "failed" | "committed_with_followup_failure"
    reason: str = ""
    before_types: list[str] = field(default_factory=list)
    after_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    revision_pk: int | None = None
    draft_created: bool = False
    published: bool = False
    publication_scheduled: bool = False
    publication_unconfirmed: bool = False
    # Exception class of a callback that failed after the episode's transaction committed.
    followup_error: str = ""
    source_revision_pk: int | None = None
    source_sha256: str = ""
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
            help="Limit conversion to these slugs. May be repeated; every slug must match exactly one episode.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Re-convert from the original legacy body (the most recent "
                f"unconverted version, searching up to {LEGACY_REVISION_SEARCH_LIMIT} revisions if needed), "
                "ignoring the 'already converted' guard. Use to regenerate "
                "conversions after the converter has been improved."
            ),
        )

    def handle(self, *args, **options):
        publish = options["publish"]
        apply = options["apply"] or publish
        force = options["force"]
        slugs = options["slugs"]

        episodes = Episode.objects.order_by("pk")
        if apply:
            using = router.db_for_write(Episode)
            if not transaction.get_autocommit(using=using):
                raise CommandError("--apply and --publish require autocommit outside an active transaction.")
            episodes = episodes.using(using)
        batch: Iterator[Episode | EpisodeResult]
        if slugs:
            selected = list(episodes.filter(slug__in=slugs).values_list("pk", "slug"))
            ids_by_slug: dict[str, list[int]] = {slug: [] for slug in sorted(set(slugs))}
            for pk, slug in selected:
                ids_by_slug[slug].append(pk)

            selection_errors = []
            missing = [slug for slug, ids in ids_by_slug.items() if not ids]
            if missing:
                selection_errors.append(f"Unknown episode slug(s): {', '.join(missing)}")
            ambiguous = [
                f"{slug} (IDs: {', '.join(map(str, ids))})" for slug, ids in ids_by_slug.items() if len(ids) > 1
            ]
            if ambiguous:
                selection_errors.append(f"Ambiguous episode slug(s): {', '.join(ambiguous)}")
            if selection_errors:
                raise CommandError(". ".join(selection_errors))
            batch = self._selected_episodes(episodes, selected)
        else:
            batch = self._archive_episodes(episodes)

        results = []
        for item in batch:
            if isinstance(item, EpisodeResult):
                result = item
            else:
                try:
                    result = self._process_episode(item, apply=apply, publish=publish, force=force)
                except Exception as exc:
                    # Preserve earlier receipts and continue independent pages without exception text.
                    result = EpisodeResult(item.slug, item.pk, "failed", reason=type(exc).__name__)
            self._report(result)
            self.stdout.flush()
            # Only summary flags/identities survive this episode, not its body
            # or potentially numerous conversion warnings.
            results.append(
                replace(
                    result,
                    before_types=[],
                    after_types=[],
                    warnings=result.warnings[:1],
                    publish_conflict=result.publish_conflict[:1],
                )
            )

        self._report_summary(results, apply=apply)

        errors = []
        failed = [result.slug for result in results if result.status == "failed"]
        if failed:
            errors.append(
                f"{len(failed)} episode(s) failed: {', '.join(failed)}. "
                "Earlier reported revisions remain committed; independent episodes were continued. "
                "Inspect the failed episodes and retry; already converted drafts are skipped."
            )
        followup_failures = [result.slug for result in results if result.status == "committed_with_followup_failure"]
        if followup_failures:
            errors.append(
                f"{len(followup_failures)} episode(s) committed with failed follow-up: {', '.join(followup_failures)}. "
                "Inspect the post-commit callbacks and recover the follow-up separately."
            )
        conflicts = [result.slug for result in results if result.publish_conflict]
        if conflicts:
            errors.append(
                f"{len(conflicts)} episode(s) were not published because their draft contains unrelated "
                f"unpublished changes: {', '.join(conflicts)}. Nothing was published for them and their pending "
                "edits are kept; review and publish the drafts in the Wagtail admin."
            )
        unconfirmed = [result.slug for result in results if result.publication_unconfirmed]
        if unconfirmed:
            errors.append(
                f"For {len(unconfirmed)} episode(s), publication could not be confirmed: {', '.join(unconfirmed)}. "
                "Inspect the reported revisions in the Wagtail admin before retrying."
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

    def _selected_episodes(
        self, episodes: models.QuerySet[Episode], selected: list[tuple[int, str]]
    ) -> Iterator[Episode | EpisodeResult]:
        for identities in batched(selected, EPISODE_BATCH_SIZE):
            loaded = episodes.in_bulk([pk for pk, _ in identities])
            for pk, slug in identities:
                episode = loaded.pop(pk, None)
                yield episode if episode is not None and episode.slug == slug else self._edit_conflict(pk, slug)

    @staticmethod
    def _archive_episodes(episodes: models.QuerySet[Episode]) -> Iterator[Episode]:
        horizon = episodes.aggregate(horizon=models.Max("pk"))["horizon"]
        if horizon is None:
            return
        episodes = episodes.filter(pk__lte=horizon)
        page = episodes
        # Materialize each page so its selection cursor is closed before any writes.
        while batch := list(page[:EPISODE_BATCH_SIZE]):
            yield from batch
            last_pk = batch[-1].pk
            if last_pk == horizon:
                return
            page = episodes.filter(pk__gt=last_pk)

    # -- per-episode ----------------------------------------------------
    def _process_episode(self, episode: Episode, *, apply: bool, publish: bool, force: bool) -> EpisodeResult:
        """Convert one episode; an episode that disappears meanwhile is an edit conflict.

        ``episode`` was loaded during selection. It, or its current
        revision, can be deleted before or while it is processed, and then one of the
        reads below fails. That is the same situation as any other edit made
        during the run, so it is reported the same way and the batch goes on.
        """
        try:
            return self._convert_episode(episode, apply=apply, publish=publish, force=force)
        except ObjectDoesNotExist:
            current = Episode.objects.using(episode._state.db).filter(pk=episode.pk).first()
            if current is not None and current.latest_revision_id == episode.latest_revision_id:
                # Nothing about the episode changed, so this is not a concurrent edit.
                raise
            return self._edit_conflict(episode.pk, episode.slug)

    def _convert_episode(self, episode: Episode, *, apply: bool, publish: bool, force: bool) -> EpisodeResult:
        # The detail conversion source: normally the latest revision (the current
        # draft) so the command stays idempotent; with --force, the original
        # legacy body (most recent unconverted version) so a previously converted
        # episode can be regenerated by an improved converter.
        #
        # Everything below is computed from the episode as it is now. The snapshot
        # identifies that state; it is checked again, under the page lock, before
        # anything is written.
        snapshot = self._snapshot(episode) if apply else None
        source_revision_pk = None
        source_sha256 = ""
        if force:
            try:
                source = self._legacy_raw_top(episode)
            except LegacyRevisionSearchLimitExceeded:
                return EpisodeResult(
                    episode.slug,
                    episode.pk,
                    "failed",
                    reason=(
                        f"legacy revision search limit reached ({LEGACY_REVISION_SEARCH_LIMIT} revisions); "
                        "save the legacy body (for example from a backup or an older revision) as the live "
                        "body or a new revision before retrying"
                    ),
                )
            if source is None:
                return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no legacy body to re-convert")
            raw_top, source_revision_pk = source
            source_sha256 = hashlib.sha256(
                json.dumps(list(raw_top), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
        else:
            raw_top = episode.get_latest_revision_as_object().body.raw_data
        detail_blocks = [block for block in raw_top if block["type"] == "detail"]

        if not detail_blocks:
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no detail section")

        new_top, after_types, warnings, changed_positions = self._convert_top(raw_top)
        if not changed_positions and not force and any(self._has_structured_notes(block) for block in detail_blocks):
            # The latest draft is already converted. When publishing, push that
            # draft live -- but only if the live page still has a legacy detail
            # that the draft holds converted (same position and block ID), i.e.
            # the pending change really is our conversion and not an unrelated draft.
            if (
                snapshot is not None
                and publish
                and episode.has_unpublished_changes
                and self._has_pending_conversion(episode.body.raw_data, raw_top)
            ):
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
                result = EpisodeResult(
                    episode.slug,
                    episode.pk,
                    "changed",
                    revision_pk=revision.pk,
                )
                with self._write_conversion(episode, snapshot, result) as current:
                    if current is None:
                        return self._edit_conflict(episode.pk, episode.slug)
                    self._publish_revision(current.get_latest_revision(), current, result)
                    if result.published:
                        result.reason = "published existing converted draft"
                    elif result.publication_scheduled:
                        result.reason = "scheduled publication of existing converted draft"
                    else:
                        result.reason = "publication unconfirmed for existing converted draft"
                return result
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="already converted")

        if not changed_positions:
            return EpisodeResult(episode.slug, episode.pk, "skipped", reason="no convertible shownote HTML")

        # Full ordered lists for the per-episode review; handle() drops them
        # from the retained summary record right after reporting.
        before_types = [child["type"] for block in detail_blocks for child in block["value"]]

        result = EpisodeResult(
            episode.slug,
            episode.pk,
            "changed",
            before_types=before_types,
            after_types=after_types,
            warnings=warnings,
            source_revision_pk=source_revision_pk,
            source_sha256=source_sha256,
        )

        merged_top: list[dict] | None = new_top
        if force:
            target_raw = episode.get_latest_revision_as_object().body.raw_data
            merged_top = self._merge_detail(target_raw, new_top, changed_positions)
            if merged_top is None:
                result.status = "failed"
                result.reason = "historical detail conflict: source sections do not match unique current block IDs"
                return result

        if snapshot is not None:
            # Always edit the latest-revision object to keep other unpublished
            # draft changes (such as page fields). The new body is computed from
            # that draft, with only matched detail values replaced on --force.
            #
            # The conversion was computed from the snapshot. It is written only if
            # the episode, read again under its row lock, is still in that state:
            # a detail edit saved in the meantime is never replaced by the older
            # conversion, and nothing is merged into or recomputed from it here.
            with self._write_conversion(episode, snapshot, result) as current:
                if current is None:
                    return self._edit_conflict(episode.pk, episode.slug)
                target = current.get_latest_revision_as_object()
                # Checked before the conversion is merged in: whatever differs from the
                # live page now is somebody else's pending edit.
                unrelated = self._unrelated_draft_changes(current, target) if publish else []
                target.body = target.body.stream_block.to_python(merged_top)
                revision = target.save_revision()
                result.revision_pk = revision.pk
                result.draft_created = True
                if unrelated:
                    result.publish_conflict = unrelated
                elif publish:
                    self._publish_revision(revision, current, result)

        return result

    @staticmethod
    def _publish_revision(revision: Revision, episode: Episode, result: EpisodeResult) -> None:
        revision.publish()
        using = episode._state.db
        result.published = (
            Page.objects.using(using).filter(pk=episode.pk, live=True, live_revision_id=revision.pk).exists()
        )
        if not result.published:
            result.publication_scheduled = (
                Revision.objects.using(using).filter(pk=revision.pk, approved_go_live_at__isnull=False).exists()
            )
            result.publication_unconfirmed = not result.publication_scheduled

    @contextmanager
    def _write_conversion(self, episode: Episode, snapshot: EpisodeSnapshot, result: EpisodeResult):
        committed = False

        def record_commit():
            nonlocal committed
            committed = True

        try:
            with self._locked_unchanged(episode, snapshot) as current:
                if current is not None:
                    # Run before callbacks registered by saving or publishing the revision.
                    transaction.on_commit(record_commit, using=current._state.db)
                yield current
                if current is not None and transaction.get_rollback(using=current._state.db):
                    raise transaction.TransactionManagementError("The conversion transaction was marked for rollback.")
        except Exception as exc:
            if not committed:
                raise
            result.status = "committed_with_followup_failure"
            result.followup_error = type(exc).__name__

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
        """Yield the current episode while holding its row locks, or ``None`` on a conflict.

        Saving a draft or publishing in the editor updates the page row and rows
        of the page's revisions. Holding their locks until the block ends makes
        those wait, and reading the episode again under the locks sees every edit
        committed since ``snapshot`` was taken. ``None`` is yielded when the
        episode no longer exists, is not in the snapshot's state any more or is
        being saved by somebody else right now; the caller must then write
        nothing.
        """
        using = episode._state.db
        with transaction.atomic(using=using):
            if not self._lock_rows(episode):
                yield None
                return
            current = Episode.objects.using(using).filter(pk=episode.pk).first()
            if current is None or self._snapshot(current) != snapshot:
                yield None
                return
            yield current

    @staticmethod
    def _lock_rows(episode: Episode) -> bool:
        """Lock the episode's revisions and page row without waiting; ``False`` when busy.

        Wagtail takes these locks in no single order: overwriting a draft updates
        the revision and then the page, saving and publishing in one request
        updates the page and then every revision. Waiting for either while
        holding the other can therefore deadlock with an editor, and PostgreSQL
        would resolve that by aborting one side, possibly the editor's save. So
        nothing is waited for: all rows are requested with NOWAIT, and a row that
        somebody else holds means the episode is being saved right now, which is
        a conflict. Once every row is held, this transaction only touches these
        rows and rows it inserts itself, so it cannot block on an editor later.

        ``no_key`` asks for the lock an UPDATE takes, so only real changes to the
        rows count as busy, not a foreign key check that merely references them.
        """
        using = episode._state.db
        try:
            # A refused lock fails the statement; the savepoint keeps the
            # surrounding transaction usable.
            with transaction.atomic(using=using):
                list(
                    episode.revisions.using(using)
                    .select_for_update(nowait=True, no_key=True)
                    .order_by("pk")
                    .values_list("pk", flat=True)
                )
                list(
                    Page.objects.using(using)
                    .select_for_update(nowait=True, no_key=True)
                    .filter(pk=episode.pk)
                    .values_list("pk", flat=True)
                )
        except OperationalError as exc:
            if getattr(exc.__cause__, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            return False
        return True

    @staticmethod
    def _edit_conflict(pk: int, slug: str) -> EpisodeResult:
        return EpisodeResult(
            slug,
            pk,
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
    def _merge_detail(
        target_raw: list[dict], converted_top: list[dict], changed_positions: list[int]
    ) -> list[dict] | None:
        """Match changed historical details to the current body, or return None for a conflict."""
        source_details = [block for block in converted_top if block["type"] == "detail"]
        target_details = [block for block in target_raw if block["type"] == "detail"]
        if len(source_details) == len(target_details) == 1:
            (converted,) = source_details
            (target,) = target_details
            if not converted.get("id") or not target.get("id"):
                # Older bodies may lack a block ID. One section on each side
                # is the only case where a missing ID has an unambiguous match.
                return [{**block, "value": converted["value"]} if block is target else block for block in target_raw]

        source_counts = Counter(block.get("id") for block in source_details)
        target_counts = Counter(block.get("id") for block in target_details)
        changed_details = [converted_top[position] for position in changed_positions]
        converted_by_id = {block.get("id"): block["value"] for block in changed_details}
        if any(
            not block_id or source_counts[block_id] != 1 or target_counts[block_id] != 1
            for block_id in converted_by_id
        ):
            return None

        return [
            (
                {**block, "value": converted_by_id[block.get("id")]}
                if block["type"] == "detail" and block.get("id") in converted_by_id
                else block
            )
            for block in target_raw
        ]

    @staticmethod
    def _has_structured_notes(detail: dict) -> bool:
        return any(child["type"] in SHOW_NOTE_TYPES for child in detail["value"])

    def _has_pending_conversion(self, live_top: list[dict], draft_top: list[dict]) -> bool:
        if not any(block["type"] == "detail" and self._has_structured_notes(block) for block in live_top):
            return True

        # A mixed live body can have a pending conversion too. A section that
        # was already structured on the live page is not evidence of one.
        _, _, _, live_positions = self._convert_top(live_top)
        return any(
            position < len(draft_top)
            and draft_top[position]["type"] == "detail"
            and draft_top[position].get("id") == live_top[position].get("id")
            and self._has_structured_notes(draft_top[position])
            for position in live_positions
        )

    def _legacy_raw_top(self, episode: Episode) -> tuple[list[dict], int | None] | None:
        """Return the most recent body that has not yet been converted.

        Prefers the live body when it is still legacy, otherwise scans revisions
        newest-first for a body in which no detail has ``show_note_*`` blocks
        (a mixed body is not a source). Returns
        ``None`` when the history ends without a source and raises if the search
        limit is reached while older revisions remain.
        """
        live = episode.body.raw_data
        live_detail = [block for block in live if block["type"] == "detail"]
        if live_detail and not any(self._has_structured_notes(block) for block in live_detail):
            return live, episode.live_revision_id

        revisions = episode.revisions.using(episode._state.db).order_by("-created_at", "-pk").only("content")
        limit = LEGACY_REVISION_SEARCH_LIMIT
        inspected = 0
        for inspected, revision in enumerate(revisions[:limit].iterator(chunk_size=20), start=1):
            body = revision.content.get("body")
            if body is None:
                continue
            raw = json.loads(body) if isinstance(body, str) else body
            detail = [block for block in raw if block["type"] == "detail"]
            if detail and not any(self._has_structured_notes(block) for block in detail):
                return raw, revision.pk

        # Check for more history without loading another revision body.
        if inspected == limit and revisions[limit:].exists():
            raise LegacyRevisionSearchLimitExceeded
        return None

    def _convert_top(self, raw_top: list[dict]) -> tuple[list[dict], list[str], list[str], list[int]]:
        new_top: list[dict] = []
        after_types: list[str] = []
        warnings: list[str] = []
        changed_positions: list[int] = []

        for position, block in enumerate(raw_top):
            if block["type"] != "detail":
                new_top.append(block)
                continue
            if self._has_structured_notes(block):
                new_top.append(block)
                after_types.extend(child["type"] for child in block["value"])
                continue

            changed = False
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
            if changed:
                changed_positions.append(position)
                new_top.append({**block, "value": new_children})
            else:
                new_top.append(block)

        return new_top, after_types, warnings, changed_positions

    @staticmethod
    def _raw_block(converted: ConvertedBlock) -> dict:
        return {"type": converted.type, "value": converted.value, "id": uuid.uuid4().hex}

    # -- reporting ------------------------------------------------------
    def _report(self, result: EpisodeResult) -> None:
        self.stdout.write(f"Episode {result.slug} (pk={result.pk})")
        if result.source_sha256:
            source = f"revision {result.source_revision_pk}" if result.source_revision_pk else "live page"
            self.stdout.write(f"  source: {source}, sha256={result.source_sha256}")
        if result.status == "failed":
            self.stdout.write(f"  -> failed: {result.reason}; inspect and retry this episode")
            return
        self._report_outcome(result)
        if result.status == "committed_with_followup_failure":
            if result.published:
                state = "published"
            elif result.publication_scheduled:
                state = "publication scheduled"
            elif result.publication_unconfirmed:
                state = "publication unconfirmed"
            else:
                state = "draft, not published"
            self.stdout.write(
                f"  -> committed (revision {result.revision_pk}, {state}), "
                f"follow-up failed: {result.followup_error}; recover the follow-up separately"
            )

    def _report_outcome(self, result: EpisodeResult) -> None:
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
        if result.publication_scheduled:
            self.stdout.write(f"  -> changed (revision {result.revision_pk}, publication scheduled)")
        elif result.publication_unconfirmed:
            self.stdout.write(f"  -> changed (revision {result.revision_pk}, publication unconfirmed)")
        elif result.revision_pk is not None:
            self.stdout.write(f"  -> changed (revision {result.revision_pk})")
        else:
            self.stdout.write("  -> would change (dry run)")

    def _report_summary(self, results: list[EpisodeResult], *, apply: bool) -> None:
        followup_failures = sum(1 for result in results if result.status == "committed_with_followup_failure")
        changed = sum(1 for result in results if result.status == "changed") + followup_failures
        failed = sum(1 for result in results if result.status == "failed")
        skipped = sum(1 for result in results if result.status == "skipped")
        with_warnings = sum(1 for result in results if result.warnings)
        conflicts = sum(1 for result in results if result.publish_conflict)
        edit_conflicts = sum(1 for result in results if result.edit_conflict)
        scheduled = sum(result.publication_scheduled for result in results)
        unconfirmed = sum(result.publication_unconfirmed for result in results)

        self.stdout.write("")
        summary = f"Summary: {changed} changed, {skipped} skipped, {with_warnings} with warnings"
        if failed:
            summary += f", {failed} failed"
        if followup_failures:
            summary += f", {followup_failures} committed with failed follow-up"
        if conflicts:
            summary += f", {conflicts} not published (conflict)"
        if edit_conflicts:
            summary += f", {edit_conflicts} changed during the run (conflict)"
        if scheduled:
            summary += f", {scheduled} scheduled"
        if unconfirmed:
            summary += f", {unconfirmed} publication unconfirmed"
        self.stdout.write(summary)
        if not apply:
            self.stdout.write("Dry run: no changes written. Re-run with --apply to create revisions.")
        else:
            drafts_created = sum(result.draft_created for result in results)
            published = sum(result.published for result in results)
            self.stdout.write(f"Revisions: {drafts_created} created, {published} published.")
