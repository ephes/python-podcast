Shownote Conversion Runbook
===========================

This runbook covers converting legacy episode *detail* shownotes (free-form
rich-text HTML) into the structured show-note blocks added in commit
``53f2fab`` (``show_note_heading``, ``show_note_link_list``,
``show_note_sponsor``).

The conversion is performed by the ``convert_show_notes`` management command.
It is deliberately conservative and safe to run repeatedly on staging or
production *after a database backup*.

What the command does
---------------------

* Rewrites only the ``detail`` body section; the ``overview`` section is never
  touched.
* Converts only ``paragraph`` children whose HTML actually contains shownote
  structure. Every other child (``image``, ``audio``, ``gallery``, ...) is
  preserved verbatim and in place.
* Splits a paragraph by headings (``h1``–``h6``):

  - a standalone heading becomes ``show_note_heading``;
  - a heading immediately followed by a ``ul``/``ol`` becomes a
    ``show_note_link_list``;
  - contact/intro prose stays as a ``paragraph``.

* Per link item it extracts ``prefix`` (text before the first link),
  ``title``/``url`` (first link), ``extra_links`` (further inline links) and a
  short ``note`` (trailing explanatory text, with leading ``|`` / dash
  separators stripped).
* A list item shaped as a *topic label + a nested list of single-link
  sub-items* is flattened into one item: the label becomes the ``prefix``, the
  first sub-link the main link, the rest ``extra_links``, and a lone sub-item
  note the item ``note``. This covers the common ``Django 5.0 -> Release Notes /
  What's new`` shownote shape without nesting.
* Anything ambiguous — block-level content, list items without a single
  ``http(s)`` link, non-separator text *between* links, or a nested group that
  would lose structure (a sub-item with multiple links or its own prefix, more
  than one note, more than six sub-items, or nesting deeper than two levels) —
  is preserved as a ``paragraph`` (under its heading) with a warning, rather
  than risk a lossy conversion.
* The structured fields are **plain text**, so markup they cannot hold is never
  flattened away. The section or item stays original HTML, with a warning:

  - a heading is converted only when it consists of text, optionally wrapped in
    ``<b>``/``<strong>`` (a heading renders bold anyway). A heading that
    contains an image, SVG, embed, iframe, link, ``<code>``, ``<em>``, a comment
    or a line break between words is preserved verbatim, and the list that
    follows it stays prose with it;
  - a list item is converted only when its prefix, link titles and note are
    unformatted text. Inline formatting around real text (``<strong>``,
    ``<b>``, ``<em>``, ``<i>``, ``<code>``, ``<sub>``, ``<sup>``, ``<small>``,
    ``<u>``, ``<span>``), any element inside a link, and comments keep that item
    as prose; the other items of the same list still convert, in order. The same
    applies to the topic label and sub-items of a nested group. Formatting that
    wraps only whitespace or a separator (``<b> | </b>``) carries nothing and
    does not block the conversion.

* Is **idempotent**: details that already contain ``show_note_*`` blocks are
  skipped, and the command reads the latest draft revision so re-running never
  duplicates a conversion.

Safety model
------------

* The default is a **dry run**: nothing is written. The command prints, per
  episode, the before/after detail child block types, any warnings, and whether
  it *would* change.
* ``--apply`` creates a Wagtail **draft revision**. The live page is unchanged
  until the revision is published, so the conversion can be reviewed in Wagtail
  before going live.
* ``--publish`` publishes the created revision (implies ``--apply``). It only
  ever puts the conversion live; see `Publish conflicts`_.
* ``--slug <slug>`` limits the run to one episode; it may be given multiple
  times.
* ``--force`` re-converts from the original legacy body, ignoring the "already
  converted" guard. Use it to regenerate conversions after the converter has
  been improved. It finds the most recent *unconverted* body — the live body if
  it is still legacy, otherwise the newest revision in history whose detail has
  no ``show_note_*`` blocks — and only the ``detail`` section is replaced, so the
  current ``overview`` and other body sections are kept. If an episode has no
  unconverted version anywhere (its legacy body was overwritten and never saved
  as a revision), it is skipped with "no legacy body to re-convert"; restore that
  episode's legacy body from a backup before re-converting.

Publish conflicts
-----------------

A Wagtail revision holds the whole page, so publishing a draft publishes every
pending edit in it. ``--publish`` therefore compares the draft with the live
page and publishes only when they differ in nothing but the ``detail`` section
(the conversion itself, including corrections made to it during review).

If the draft also changes anything else — an ``overview`` edit, a new title, a
different cover image — the episode is a *conflict*:

* nothing is published for that episode and the live page stays as it is;
* the pending edit is kept. When the conversion had not been applied yet, it is
  saved as a new draft revision on top of the pending edit; an existing
  conversion draft is left untouched;
* the report names the fields that differ, for example
  ``-> conflict: not published, the draft (revision 42) also changes title``;
* other episodes of the same run are still processed, the summary counts the
  conflicts and the command exits with an error that lists the affected slugs.

This applies in either order: an unrelated edit saved after ``--apply``, or
``--publish`` run for an episode that already had a pending draft. To resolve a
conflict, review the draft in the Wagtail admin and publish it there once the
other edits are meant to go live too.

Edits made while the command runs
---------------------------------

A conversion is bound to the page state it was computed from. Right before the
command saves or publishes a revision it locks the page row and the rows of the
page's revisions, reads the episode again and compares it with that state: the
latest and the live revision, the publication flags and the content of the
draft and of the live page.

If the episode was edited, published, unpublished or deleted in the Wagtail
admin in between, even when only its ``detail`` section changed, or if somebody
is saving it at that very moment, the episode is an *edit conflict*:

* nothing is written: no revision is created and nothing is published. The
  editor's revision stays the latest one;
* the older conversion is neither merged into the newer content nor silently
  recomputed from it;
* the report says ``-> conflict: not converted, the episode changed while the
  command was running; nothing was written``;
* other episodes of the same run are still processed, the summary counts the
  episodes as ``changed during the run (conflict)`` and the command exits with
  an error that lists the affected slugs.

This holds for ``--apply``, ``--publish`` and ``--force``, and also when
``--publish`` only publishes an existing conversion draft. To resolve it, run
the command again for the listed slugs: it then starts from the current
content. A dry run takes no lock.

The command never waits for a lock. Wagtail locks the page row and its revision
rows in different orders depending on the action (overwriting a draft: revision,
then page; save and publish: page, then revisions), so a command that waited
for one while holding the other could deadlock with an editor, and PostgreSQL
would end the deadlock by aborting one of the two, possibly the editor's save.
The locks are therefore requested with ``NOWAIT``: when any of the rows is held
by somebody else, the episode is being saved right now and is reported as an
edit conflict. An editor save that starts while the command holds the locks
waits for the short moment in which the revision is written and then completes.

The locks cannot show a new revision that another database transaction has
inserted but not committed yet. Such a save completes afterwards and remains the
latest revision, so the edit is kept in that case as well.

An episode that is deleted while the batch runs, at any point, is also reported
as an edit conflict and does not stop the remaining episodes.

Usage
-----

Dry run for everything (writes nothing)::

    uv run python manage.py convert_show_notes

Dry run for selected episodes::

    uv run python manage.py convert_show_notes --slug pytest --slug ansible

Create draft revisions (review in Wagtail before publishing)::

    uv run python manage.py convert_show_notes --slug pytest --apply

Convert and publish in one step::

    uv run python manage.py convert_show_notes --slug pytest --publish

Regenerate an existing draft after improving the converter::

    uv run python manage.py convert_show_notes --slug pytest --apply --force

Recommended procedure
---------------------

1. Take a database backup.
2. Run a full dry run and read the report. Confirm the before/after block types
   and review the warnings — warned sections are preserved as prose, not lost.
3. Convert a few episodes with ``--apply`` and review the draft revisions in
   Wagtail.
4. Publish the reviewed episodes (re-run with ``--publish`` for those slugs, or
   publish the drafts from the Wagtail admin). Episodes reported as a conflict
   are not published by the command; handle them in the Wagtail admin.
5. Repeat in batches. Because the command is idempotent, already-converted
   episodes are skipped automatically. Re-run the slugs reported as changed
   during the run.

Implementation
--------------

* Command: ``python_podcast/pp/management/commands/convert_show_notes.py``
* Pure parser/converter (no DB access):
  ``python_podcast/pp/show_notes/converter.py``
* Tests: ``python_podcast/pp/tests/test_show_note_converter.py`` (parser) and
  ``python_podcast/pp/tests/test_convert_show_notes_command.py`` (command).
