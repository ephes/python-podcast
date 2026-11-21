Changelog
=========

Unreleased
----------

* Stop Webmention Link discovery at the first matching advertisement and
  preserve existing headers over 8,192 characters without scanning them.

* Reject Fediverse discovery responses whose known body length exceeds 1 MiB
  before reading the body.

* Return ``504`` when the Fediverse upstream deadline has elapsed, including
  when the socket shutdown timer has yet to run.

* Resolve relative Webmention discovery targets against the request URI before
  checking for an existing link to the endpoint.

* Preserve Webmention links anchored to another resource and still advertise
  the endpoint for the current page.

* Skip cached play cards whose content type disappears during a routed
  lookup, keeping the other cards playable.

* Use the current blog's fallback cover for cached play cards after an
  episode moves between blogs.

* Sync staged assets, recovery copies and the pending minifier journal before
  replacing any generated asset. On macOS the syncs use ``F_FULLFSYNC``.

* Sync the published or restored generation before retiring the minifier
  journal, and preserve recovery copies until that retirement is durable.

* Reject ambiguous show-note conversion slugs before processing the selection
  and report the matching episode IDs.

* Confirm the submitted show-note revision is live or scheduled before
  reporting publication, and flag unconfirmed attempts with their revision IDs.

* Resolve persistent play cards and their covers on the database that supplied
  the card or owns the overview. Keep found and missing card IDs scoped to that
  database on each request.

* Skip poster prefetches for cached overview cards marked as having no audio.

* Keep an existing Webmention discovery link for the same endpoint and
  preserve the order of the response's other Link values.

* Convert the show-note archive in bounded primary-key batches. Close each
  selection cursor before writing revisions and defer newly appended episodes
  to the next run.

* Count newly created and published show-note revisions separately, including
  in batches with failures or conflicts.

* Report the committed revision ID when show-note conversion encounters a
  failed post-commit callback, and flag the follow-up for separate recovery.

* Keep headings with HTML attributes (on the heading or on a ``<b>``,
  ``<strong>`` or ``<br>`` inside it) and their following lists in prose during
  show-note conversion, preserving fragment targets and metadata.

* Preserve literal heading text during show-note conversion by recognizing
  only HTML ``<br>`` elements as line breaks.

* Keep cached episode listings renderable after a page is deleted. Remember
  missing pages for the request and omit their persistent play actions.

* Publish one persistent player payload per audio and post in a page render.
  Repeated blocks keep their play controls and share that payload.

* Limit forced show-note conversion to the newest 100 revision bodies per
  episode when the live body lacks legacy detail. Report a failure if older
  revisions remain and the search found no legacy detail.

* Refuse an explicit show-note conversion selection if any requested episode
  slug is unknown, before processing or writing revisions.

* Upgrade Wagtail 8.0.1 to 8.1 (range ``>=8.1,<8.2``) and relock django-cast
  to develop ``e0c632ad`` (release 0.2.68 plus the 0.2.69 version bump; from
  ``c290ec1a``), the revision the homepage runs, with the Wagtail 8 hook order
  and media chooser fixes. draftjs-exporter moves to 7.3.1 with Wagtail.
  Neither package adds migrations in this range.

* Allow one minified asset generator per checkout from source reads through
  recovery. A competing run exits immediately and can be retried.

* Recover interrupted minified asset publication from a checkout-local journal.
  The next run restores the previous generation before reading sources, even
  after a forced kill, and can retry recovery if a restore failed.

* Refuse symlinked, hard-linked and other non-regular minified asset outputs,
  listing all affected paths before recovery or staging.

* Count allauth rate limits per client behind Traefik: production and staging
  set ``ALLAUTH_TRUSTED_PROXY_COUNT`` from ``DJANGO_NUM_PROXIES`` (default 1).
  Before, every request counted against Traefik's ``127.0.0.1``, so one client
  could lock all editors out of ``/accounts/login/`` and the password reset.

* Limit the Wagtail admin password reset (``/cms/password_reset/``) with
  allauth's ``reset_password`` rate and key, shared with
  ``/accounts/password/reset/``; it previously sent unlimited reset emails.

* Lock the development-only Tornado (Jupyter) at 6.6.1 for GHSA-5cjw-f85j-cv6r.

* Admit exactly one bounded, successful legacy backup announcement. Bound SSH,
  command, SFTP and close phases; stage private downloads, verify stable size and
  complete bounded gzip/SQL content, and publish without overwriting old backups.
  Transfer or cleanup uncertainty stops before any local restore.

* Make the legacy production-transfer helper inert on import, validate local
  identities and pass downloaded paths as literal process arguments. Remove its
  independent Docker/SQL restore and automatic role creation; delegate to the
  maintained staging/cutover restore with explicit existing-database confirmation.
  The new ``check-local-restore`` command runs those restore preconditions before
  the helper contacts production.

* Log Fediverse upstream failures with fixed categories and discovery paths;
  omit raw exception, query, status, header and redirect text while preserving
  generic 502/504 responses and timeout/capacity/protocol distinctions.

* Vary every Fediverse discovery proxy response on ``Accept`` to separate
  cached representations; preserve supported upstream variation and wildcard
  no-reuse semantics, and keep gateway ``HEAD`` responses bodyless.

* Settle the delayed-transcript browser-test gate after rejected JSON reads too:
  switching episodes correctly aborts the retired player's response body. Keep
  both response orders, exact fetch counts and current-episode cue assertions;
  add a browser-free regression for successful, aborted and invalid JSON bodies.
* Load the comments stylesheet on every pp page (navigation asset set
  ``pp-v2``) instead of giving comment-enabled posts their own ``pp-v1+comments``
  set: that marker forced a full page load when navigating from such a post,
  which stopped the persistent player in the pp theme.
* Stage and recover the generated asset set on handled publication failures.
* Bound asynchronous player readiness and retire stale waits on switch/close;
  expose an explicit playback retry after expiry.
* Select forced shownote sources deterministically with revision/digest receipts
  (SHA-256 over UTF-8 JSON); per-episode reports keep block counts and order;
  emit committed progress immediately and continue independent episode failures
  with a nonzero summary.
* Require matching navigation asset markers before partial swaps, and iterate
  shownote archives without retaining every full episode body.
* Establish the destination URL before connecting navigation content and retire
  old htmx node work before processing the replacement through a cleanup-running
  ``htmx.swap`` delete; comment-enabled pp posts advertise their own navigation
  asset marker.

* Bound enhanced-navigation HTML to 2 MiB before parsing; cancel oversized
  streams and use one native-navigation fallback.
* Retire pending enhanced navigation on a newer native same-page fragment click.
* Serialize development/Git source switches through validation, atomic source
  publication and environment sync, retaining failed-sync recovery.
* Clear partially constructed docks after synchronous player/panel connection
  or initial play failures; retain the original error and allow explicit retry.
  Errors raised while tearing down the previous dock do not fail the new one.
