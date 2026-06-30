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
* ``--publish`` publishes the created revision (implies ``--apply``).
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
   publish the drafts from the Wagtail admin).
5. Repeat in batches. Because the command is idempotent, already-converted
   episodes are skipped automatically.

Implementation
--------------

* Command: ``python_podcast/pp/management/commands/convert_show_notes.py``
* Pure parser/converter (no DB access):
  ``python_podcast/pp/show_notes/converter.py``
* Tests: ``python_podcast/pp/tests/test_show_note_converter.py`` (parser) and
  ``python_podcast/pp/tests/test_convert_show_notes_command.py`` (command).
