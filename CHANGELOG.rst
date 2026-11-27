Changelog
=========

Unreleased
----------

* Move the React theme to cast-react ``v0.0.8`` (from ``v0.0.7``). Readers
  see a labelled "Subscribe" link in the header (written blogs: "Feeds"),
  podcast app links on the post list and episode pages, and follow links in the
  footer; the feed page becomes a subscribe page with app buttons, a copyable
  MP3 feed address, the other formats and the blog feeds. Rollback in
  ``docs/deploy.rst`` (2026-11-27 cast-react v0.0.8).

* Move the Vue.js theme to cast-vue ``7684476`` (from ``062fa8e``; Git
  commit, not on PyPI). Visitors can now subscribe from every Vue.js page: a
  "Subscribe" link in the header, Apple Podcasts, Overcast, Pocket Casts,
  Spotify, YouTube and RSS links on the archive and below the episode player,
  and follow links in the footer. ``/show/feed/`` becomes a subscribe page with
  app buttons, a copyable feed URL for the recommended format and the other
  formats. Rollback in ``docs/deploy.rst`` (2026-11-27 cast-vue 7684476).

* Move the React theme to cast-react ``v0.0.7`` (from ``v0.0.6``). Dropdown
  arrows sit inside the field with room to the edge in light and dark mode,
  and the footer theme switcher lines up with the header and stacks on
  phones. Rollback in ``docs/deploy.rst`` (2026-11-27 cast-react v0.0.7).

* Move the Vue.js theme to cast-vue ``062fa8e`` (from ``cdc53e4``; Git
  commit, not on PyPI). The sort and site theme selects get an inset chevron
  and the theme's control style in light and dark, the footer theme switcher
  stacks on phones and shows the theme that renders the page, the theme
  chooser page becomes an aligned grid that marks the current theme, and the
  archive, tag search, date range, chips, pagination and header controls share
  one style. Rollback in ``docs/deploy.rst`` (2026-11-27 cast-vue 062fa8e).

* Move the React theme to cast-react ``v0.0.6`` (from ``v0.0.5``). Episode
  lists show each episode's overview with a "Read more" link to the full
  episode page, and list rows never show the detail part. Rollback in
  ``docs/deploy.rst`` (2026-11-27 cast-react v0.0.6).

* Move the Vue.js theme to cast-vue ``cdc53e4`` (from ``785a147``; Git
  commit, not on PyPI). The tag filter shows the most-used tags plus a tag
  search and an alphabetical index instead of one pill per tag; the archive
  lists years with counts and opens the months of a year; the custom date
  range is folded away; active filters appear as removable chips above the
  list. The feed page, transcripts, the theme chooser, error pages and the
  Impressum, Über uns and account pages get the theme's header, footer and
  styles instead of a bare fallback. Rollback in ``docs/deploy.rst``
  (2026-11-27 cast-vue cdc53e4).

* Move the React theme to cast-react ``v0.0.5`` (from ``v0.0.4``). The tag
  filter shows the ten most-used tags and opens the rest as a searchable A-Z
  index instead of one pill per tag; the custom date range folds below the
  month menu; list rows show a cover only once; the phone header keeps its
  links on one line. Rollback in ``docs/deploy.rst`` (2026-11-27 cast-react v0.0.5).

* Move the React theme to cast-react ``v0.0.4`` (from ``v0.0.3``). Tags and
  categories are ordered by post count, months are one select grouped by
  year, and the feed page, transcripts, the theme chooser and the Impressum,
  Über uns and account pages get the theme's header and styles instead of a
  bare fallback. Rollback in ``docs/deploy.rst`` (2026-11-27 cast-react v0.0.4).

* Move the Vue.js theme to the cast-vue redesign (Git commit ``785a147``, from
  ``b82a2e6``; not on PyPI). The new reading design has a light/dark switch
  and an episode list with search and filters in a side column. A lightweight
  audio player replaces Podlove within the Vue.js theme and supports chapters,
  transcripts and playback speed. Playback continues across page changes
  with controls in a bottom bar. Only readers who choose Vue.js in the theme
  chooser or visit a blog set to ``vue`` see the redesign. The package ships
  its built bundle (no Node.js build on the server). No migration. Rollback
  in ``docs/deploy.rst`` (2026-11-27 cast-vue redesign).

* Offer the React theme (cast-react ``v0.0.3``, from its Git tag; not on
  PyPI) in the theme chooser next to Vue.js, Bootstrap 5 and Python Podcast.
  It is installed as ``cast_react``, ships its built bundle (no Node.js build
  on the server) and is only used where a reader picks it or a blog sets it
  as its theme. Rollback in ``docs/deploy.rst`` (2026-11-27 React theme).

* Relock django-cast to develop ``766c225f`` (from ``d4f29f33``),
  cast-bootstrap5 to ``44aece3`` (from ``8a11f2b``) and django-indieweb to
  develop ``47a983a`` (from ``3faf52a``). Uncached podcast feeds no longer ask
  the media storage for every enclosure size: a size read from storage is now
  stored with its file name. Also included: the "Cache file sizes" admin
  action keeps concurrent editor changes, chapter saves no longer overwrite
  unrelated chapters on retry, replaced theme-switcher controls show the
  current colour mode, and Webmentions with an out-of-range date or a
  ``#author`` link to another page are stored correctly. No migration; see
  ``docs/deploy.rst`` (2026-11-27 relock).

* Keep show-note headings other than ``h3`` as HTML when converting legacy
  show notes, with the list that follows them. Both show-note blocks render
  ``h3``, so an ``h4`` subsection (or an ``h2`` above the sections) was
  flattened to the same level before. ``h3`` sections still convert, and
  stored show-note blocks keep rendering ``h3``.

* Keep visible spaces such as ``&nbsp;`` between a show-note heading and its
  list, between list items and at the edges of preserved show-note prose.
  The converter dropped them because it treated every Unicode space as
  collapsible HTML whitespace; ordinary indentation still converts.

* Keep crawlers that honour ``robots.txt`` out of the episode index filter URLs:
  ``robots.txt`` now disallows the ``date_facets``, ``tag_facets`` and
  ``category_facets`` query parameters, as first (``/*?tag_facets=``) or later
  (``/*?*&tag_facets=``) parameter. Filter URLs were about a quarter of all
  requests, and about 45% of those came from such crawlers. Unfiltered index
  pages, their pagination, episodes, feeds and other query parameters (such as
  ``utm_tag_facets``) stay crawlable.

* Keep flat show-note items with line breaks between meaningful lines as
  HTML, preserving the line boundaries while eligible siblings still convert.

* Abort legacy backup downloads on short staging writes or a staged size
  mismatch before publishing or restoring the backup.

* Keep show-note groups with text or markup following their nested list as
  HTML, preserving the order of the links and the trailing content.

* Preserve show-note items with blank link titles as HTML, including items
  with a blank title on an extra link or a nested sub-link.

* Convert legacy sibling detail sections while preserving existing structured
  show notes. A subsequent publish can reuse the converted draft. ``--force``
  still needs a body whose details are all legacy, so a sibling converted from
  an already mixed body cannot be regenerated with it.

* Reapply forced show-note conversions only to detail sections changed by the
  converter, preserving current draft edits in other sections.

* Preserve attributed inline wrappers around show-note list separators,
  including attributes on nested elements.

* Keep blank HTML comments and other non-text nodes directly inside outer or
  nested show-note lists.

* Reject core media JUnit reports that change during reading or whose byte
  count differs from the reported file size.

* Report missing JUnit evidence for the seven required core media cases when
  pytest exits successfully without writing the report.

* Match forced show-note conversions to current detail blocks by ID, keeping
  newly added and reordered sections in place. Report missing or ambiguous
  historical matches before writing a revision.

* Keep HTML comments and escaped literal text intact in preserved show-note
  paragraphs during conversion.

* Keep attributed line breaks in show-note prose and list items, including
  fragment targets between a heading and a list.

* Preserve show-note lists with HTML attributes as prose, including nested
  list wrappers with fragment targets.

* Preserve show-note list items with anchor attributes beyond ``href`` as
  prose, keeping fragment targets and download filenames in list order.

* Try the next resolved Fediverse address when opening a socket fails,
  within the existing upstream deadline.

* Relock django-cast to develop ``d4f29f33`` (0.2.70 development state; from
  ``e0c632ad``), cast-bootstrap5 to ``8a11f2b`` (gallery opening fixes; from
  ``b7f16729``) and django-indieweb to develop ``3faf52a`` (0.7.1 plus the
  unreleased 0.7.2 changes; from ``7ab7a8ef``). Readers see, among others, a
  single stable podcast RSS build date. django-indieweb adds migrations
  ``indieweb.0032`` and ``indieweb.0033``; upgrade checks and the rollback
  step for them are in ``docs/deploy.rst`` (2026-11-25).

* Remove the failed-login throttle on the Django admin and Wagtail admin
  logins (``python_podcast.users.login_throttle``) together with its
  ``api_token_auth_throttle`` cache, ``ADMIN_LOGIN_THROTTLE_LOCK_PATH``, the
  ``DJANGO_ADMIN_LOGIN_CLIENT_RATE``/``DJANGO_ADMIN_LOGIN_USERNAME_RATE``
  settings and the ``filelock`` dependency. Admin accounts rely on long,
  randomly generated passwords; failed admin logins no longer get ``429``.
  allauth's own rate limits, ``ALLAUTH_TRUSTED_PROXY_COUNT`` and the limited
  Wagtail password reset stay. The ``api-token-auth-throttle/`` directory and
  ``admin-login-throttle.lock`` under ``DJANGO_CACHE_LOCATION`` are no longer
  used and can be deleted. ``docs/admin_login_throttle.rst`` is now
  ``docs/login_rate_limits.rst``.

* ``commands.py switch-to-*`` and ``just minify-static`` keep their
  checkout-local lock files but take them with ``fcntl.flock`` from the
  standard library instead of ``filelock``.

* Limit the core media gate's JUnit input to a regular file of at most 1 MiB
  and reject XML document type declarations.

* Require a single passing JUnit suite with matching summary counters for the
  seven core media cases, and reject suite-level failure indicators.

* Preserve Fediverse discovery gateway responses and failure markers when
  warning dispatch raises. HEAD responses remain bodyless.

* Validate every generated asset recovery record before rollback. Preserve
  the outputs and pending journal if a recovery record is missing or invalid.

* Skip generated asset publication after recovery when all output bytes
  already match the generated set.

* Copy generated asset recovery backups in bounded chunks and check their
  sizes before publication. Refuse publication if source metadata or output
  paths change during backup staging.

* Show retry controls when the current dock audio fails to load, and ignore
  errors from retired audio elements. Retry rebuilds the failed episode from
  the dock's own payload copy, also after navigating away from its page.

* Wait for the dock's own exit animation or its fallback before dismissing the
  player and restoring focus.

* Report an edit conflict under the requested slug if an explicitly selected
  show-note conversion target is renamed before it is loaded.

* Use the episode's write database for show-note conversion locks, publication
  verification, and commit receipts in routed deployments. Report rolled-back
  conversions as failures.

* Require autocommit for show-note conversion with ``--apply`` or ``--publish``
  so revision receipts follow each episode's commit. Dry runs still work inside
  a transaction.

* Validate explicit show-note conversion slugs using only episode IDs and slugs,
  then load the selected episode bodies in batches.

* Return ``502`` for conflicting upstream ``Content-Type`` fields on Fediverse
  discovery responses.

* Preserve all upstream ``Content-Encoding`` fields in wire order on Fediverse
  discovery responses.

* Resolve profile edits by account ID and redirect to the profile URL for the
  username loaded from that account. Return 404 if the account is missing.

* Limit profile saves to the display name, preserving concurrent changes to
  other account fields. Return 404 if the account is removed before the save.

* Return ``502`` for Fediverse discovery redirects with multiple upstream
  ``Location`` fields.

* Preserve all upstream ``Cache-Control`` directives on Fediverse discovery
  responses, including directives sent in separate header fields.

* Paginate the staff account directory in username order, with 50 accounts
  per page and Previous and Next links.

* Keep the localized duplicate-username message scoped to the admin account
  creation form and use Django's case-insensitive duplicate check.

* Stop Webmention Link discovery at the first matching advertisement and
  preserve existing headers over 8,192 characters without scanning them.

* Let custom template responses with nonmapping contexts render with their
  supplied headers.

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
