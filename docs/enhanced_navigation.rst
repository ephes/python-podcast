Persistent player: enhanced navigation
======================================

With the persistent audio player enabled,
``python_podcast/static/js/persistent-player.js`` turns clicks on internal
public links into an *enhanced navigation*: it fetches the page, swaps only the
theme's swap target (``#paging-area`` or ``#main-content``) and leaves the
player region alone, so audio keeps playing. Everything else stays a normal
full document load. This page records where that boundary is.

Which links are enhanced
------------------------

A link is enhanced only when it is a plain same-origin ``http(s)`` link without
``download`` or foreign ``target``, is not driven by htmx and
is not inside a form, and its path is not one of the excluded routes: admin,
CMS, account/login/logout, media, static, API, comments, feeds and
download/media file suffixes.

Cross-page fragments
--------------------

Cross-page links retain their requested fragment in history. After a swap,
the matching decoded id (or legacy named anchor) is scrolled into view and
focused; missing targets use the heading/top fallback. Same-page fragment
links stay browser native. A request with a fragment that redirects uses a
full document navigation to the original URL: Fetch hides redirect fragments,
so the browser must apply Location's fragment override or inheritance rules.
This fallback restarts playback like other full document loads. Direct enhanced
fragment navigation and back/forward swaps preserve the audio element.

The final URL is checked again
------------------------------

The fetch follows redirects, so the page that answers is not necessarily the
one that was clicked. Before the response body is read, the **final** URL is
checked against the same rules:

* A redirect to an allowed public page is swapped in as usual and the address
  bar shows the final URL.
* A redirect to an excluded route (for example a public link that now leads to
  ``/accounts/login/`` or the admin) or to another origin is never parsed or
  imported. The browser does a full navigation to that final URL instead. This
  also holds when the other origin allows cross-origin reads.

Deadline and superseded navigations
-----------------------------------

One enhanced navigation (request and body together) has 15 seconds. After that
the request is aborted and the browser does a normal full load of the
destination, so a stalled response cannot leave a clicked link dead. A theme
can change the deadline with ``data-cast-nav-timeout-ms`` on the
``#cast-persistent-player`` region.

HTML is admitted before parsing with a 2 MiB byte ceiling. Declared oversized
responses are cancelled immediately; streamed bytes (after decompression) are
counted before retaining each chunk, including when Content-Length is absent or
incorrect. Oversize bodies and browsers without readable response streams use
the same single native-navigation fallback.

A plain native same-document fragment click also retires a pending enhanced
navigation, so its late response or deadline cannot replace the chosen page.
Modified clicks and links owned by htmx, forms, downloads or another target keep
their normal behavior without cancelling the pending navigation.

Starting another navigation aborts the request of the previous one. An aborted,
superseded navigation never triggers the full-load fallback; only the current
navigation can hand over to the browser. Browsers without ``AbortController``
keep the deadline and the fallback but cannot cancel the download.

Other navigation owners
-----------------------

An htmx request or swap targeting the content region (including an ancestor or
child) invalidates and aborts pending enhanced navigation. htmx history restores
and non-cast popstate entries also invalidate it. Late responses and old
deadlines cannot overwrite that owner's DOM or address bar. Unrelated htmx
targets, already-cancelled events and explicit non-swaps (``shouldSwap=false``)
do not cancel enhanced navigation; our synchronous swaps do not emit
htmx swap events, so they do not cancel themselves. Audio is left intact.

Required asset compatibility
-----------------------------

Both documents must advertise the same nonempty ``cast-navigation-assets`` meta
value. The pp and bootstrap5 base templates declare separate asset sets. A page
that needs extra CSS or modules must override ``navigation_assets`` with a new
value; pages sharing those requirements use the same value. The pp base
template loads the comments stylesheet on every page (asset set ``pp-v2``), so
comment-enabled posts share the marker and navigating to or from them keeps the
persistent player. The pp theme loads no comment JavaScript (``ajaxcomments.js``
is only used by other themes), so no comment script is lost when a post's content
is swapped in. Bump the value when
changing required assets. Missing or different markers cause a native load
before any partial swap or history update. Enhanced navigation does not import
head assets. Full loads restart playback.

Adopting destination content
----------------------------

History is moved to the fetched final URL before connecting incoming nodes.
Relative media URLs and synchronous custom-element callbacks therefore use the
destination base. A history or swap error hands over to a full document load.
When htmx is present, a synchronous public ``htmx.swap(old, "", {swapStyle:
"delete"})`` retires the old content before connecting and processing the
replacement: htmx runs its element cleanup (``htmx:beforeCleanupElement``,
polling, listeners and extension hooks) and then detaches it. ``htmx.remove()``
alone only detaches, so it is used only as a fallback for builds without
``swap``.
The persistent dock stays outside this boundary.

Back and forward
----------------

Back/forward to an entry created by enhanced navigation fetches that entry's
URL again. If the entry's URL now redirects to another allowed page, the URL of the
**current** history entry is replaced with the final one (same state, no new
entry, forward entries kept), so the address bar and relative links such as
``?page=2`` match the page shown. A redirect to an excluded route or another
origin falls back to a full navigation, as above. A full-load fallback to the
exact active history URL forces a document reload, including when that URL
contains a fragment.

Playback actions and deferred transitions
-----------------------------------------

The latest explicit episode activation or close owns the dock. A queued View
Transition update from an older activation cannot rebuild or start its episode,
even if it runs after the newer update. Closing invalidates queued updates so
they cannot reopen the dock. Activating without a transition (including reduced
motion) also supersedes pending updates. Transition cleanup and close animation
completion retain their ownership guards.

Closing with focus inside the dock returns focus to its activation button, or
the matching current episode action if navigation replaced that button. When
that episode is absent, focus returns to the current content heading (or the
content region if it has no visible heading). A superseded close does not move
focus, and moving focus outside the dock during the close animation is respected.

View Transition startup is best effort: a synchronous startup exception or
rejected transition falls back to plain activation when the update has not run.
An update that already built the dock is not repeated. All transition promises
are handled, and cleanup or fallback from an older activation cannot change a
newer dock.

Dock construction recovery
--------------------------

A synchronous player/panel connection or initial controller-play failure closes
and empties the failed dock. Partially connected elements are disconnected,
manager listeners and reserved space are released, and all cards return to idle.
The next explicit play builds a fresh player, including when retrying the same
episode. Errors reported while the previous dock is torn down during an
in-place switch are not attributed to the new build. View Transition fallback
does not repeat a failed build. Connection
errors retain the browser's original report; the original error object is also
available as ``window.__castPersistentAudioDebug.lastDockError`` until the next
successful build. Asynchronous media playback failures retain the player's
existing handling.

Player readiness deadline
--------------------------

If the custom player has no audio yet, its activation owns a 15-second deadline
and a single ready listener. Themes/tests can set
``data-cast-player-ready-timeout-ms`` on the region. Readiness for the current
player retires the wait and starts a newly available controller. Ready events
without current audio do not extend the deadline. Switching or closing cancels
the pending wait immediately; stale callbacks cannot affect the current dock.
Expiry disconnects the failed player, clears active cards and shows a retryable
alert. ``Retry playback`` builds a fresh activation; ``Close`` dismisses it.

Payload identity
----------------

The first play card for each audio/post pair publishes its player payload as a
``json_script``. Every card for that pair points to the same script id
(``data-cast-play`` and ``data-cast-episode-payload``), which the player looks up
with ``getElementById``. A new page render publishes its own payload scripts.
The payload depends on the post's cover poster and transcript link, so the id
names the audio and the post:
``cast-player-data-<audio pk>-post-<post pk>``, with the matching
``cast-player-<audio pk>-post-<post pk>`` in ``data-cast-player-id``.

* Two posts that reuse one audio on an overview get two different ids, so each
  card loads its own payload and only the started card mirrors the playback
  state.
* One post has the same id on its detail page and on every list card. That is
  how a list card shows the playing state after enhanced navigation.
* Without a saved post the audio-only id ``cast-player-data-<audio pk>`` is
  used.

The ids are built in ``cast_player_payload``
(``python_podcast/pp/templatetags/pp_persistent_player.py``); templates must
take all three attributes from that payload and not build ids themselves.

Overview query budgets
----------------------

``cast_player_payload`` resolves the displayed ``posts`` IDs together and
reuses the result across audio-block includes on the current request. Cached
projections use their source database when available, otherwise the owning
page or queryset supplies the alias. The base pages, concrete posts, covers
and existing renditions are read on that alias. Without an explicit owner,
the Wagtail specific-page queryset uses normal Django routing. Found and
missing IDs are memoized separately by database authority.
The batch omits cards the repository marks as having no audio. Cards without
eligibility metadata remain candidates, and the card requesting a payload is
always included.
If a cached card's Wagtail page has been deleted, the request remembers the
missing ID along with the pages it found. Both themes omit that card's play
action and leave its ordinary episode link and the other cards in place.
Detail pages keep their already concrete page. Payload identity and transcript
context still belong to each post, including when posts share an audio.

Card artwork
------------

Play cards prefer an episode's explicit cover before looking up any fallback
blog data. For cached overview cards, cover images and existing renditions for
both sizes are prefetched together. The current context's blog cover supplies
fallback artwork, with its renditions reused across cards. The player payload
retains its 512 px poster; compact cards request a separate 128 px WebP rendition.
If its original file is unavailable (``FileNotFoundError`` or Wagtail's
``SourceImageIOError``), the card uses the player poster already present in the
payload, which may be a cached rendition. This keeps the card renderable when
only the smaller rendition cannot be generated. Other errors still propagate;
this fallback does not repair or delete media files.

Tests
-----

``tests/test_player_card_queries.py`` renders the actual audio-block templates
and payload builder with synthetic ORM pages, covers and existing renditions.
It freezes a five-query cold-cache budget for one and twenty cards with shared
or distinct covers (content type, base pages, concrete episodes, images,
renditions). The shared blog fallback also uses five queries when the
context already has the concrete blog. The routed overview regression renders
same-ID episodes with distinct covers on two databases and checks that a
missing card on one database still renders on the other. Mixed overviews in
both themes publish the same payloads within the five-query budget even when
they also display an article with its own cover. Audio metadata is preloaded
to isolate this page/cover budget from upstream audio chapter queries. New
rendition generation may require additional reads and writes.
The same tests cover stale cached pages and repeated audio blocks in both
themes, including a fresh script on each render and distinct post transcripts.

``tests/e2e/test_enhanced_navigation.py`` runs the source file and the
committed minified build in a real browser against a small fixture server. The
repository has no separate JavaScript test runner; these tests use the
Playwright harness of the other browser tests, need no database content and run
in CI in the ``dock-transitions`` job. The exact isolated local command is::

    uv run --locked pytest -p no:django -p no:sugar -o addopts='' -m e2e tests/e2e/test_dock_transitions.py tests/e2e/test_enhanced_navigation.py

``tests/test_navigation_runtime.py`` additionally runs a small Node transport
oracle when Node is installed. It checks streaming rejection and generation
retirement, including ignored modified/other-owner clicks, without a DOM/browser.
The real-browser navigation, focus and custom-element tests remain required.

After changing ``persistent-player.js`` or ``persistent-player.css``, run
``just minify-static``. A checkout-local ``.minify-static.lock`` covers source
reads, publication and recovery. A second invocation exits immediately with an
error. Retry after the first finishes and leave the lock file in place.
The minifier stages all three generated assets and byte-exact recovery copies
alongside their destinations. Before replacing any output, it syncs the
staged files, their directories and the pending publication recorded in
``.minify-static-transaction``. This ordering relies on local POSIX filesystems
and storage that honor file and directory ``fsync``. On macOS each sync uses
``F_FULLFSYNC`` to flush the drive cache and falls back to ``fsync`` where the
filesystem does not support it. If staging or replacement
fails or is interrupted by Ctrl-C, the command attempts recovery before
propagating the original exception. After a forced kill or a cleanup error, rerun
``just minify-static``. Under the lock it restores the whole previous generation
for a pending publication before reading the sources, including deleting outputs
that were previously absent. Publication and rollback both sync the resulting
files and their parent directories before removing the pending marker. Recovery
files remain available until the marker removal itself has been synced. If the
marker is gone on restart, the minifier keeps the current generation and syncs
the journal before clearing the remaining recovery files.

Before recovery or staging, the command checks all output paths. It lists
every symlink, hard-linked file or other non-regular output and exits with the
existing assets untouched. Check the listed paths and retry with ordinary
files or absent outputs.

If recovery reports an error, keep the journal and the reported copies in place.
Resolve the underlying filesystem error and retry. After a system or power
failure, verify the generated assets. Run
``uv run --locked pytest tests/test_performance_assets.py`` before committing or
deploying.

``tests/e2e/test_dock_transitions.py`` exercises queued updates in both orders,
close during a pending switch, and activation without a transition, for both
source and minified assets. These isolated tests need no PostgreSQL or Vite:
``uv run pytest -p no:django -o addopts='' -m e2e tests/e2e/test_dock_transitions.py``.

Core media gate
~~~~~~~~~~~~~~~

Run ``just test-core-media`` before pushing playback changes. The command uses
Chromium, ``config.settings.e2e`` and real migrations with an overall 300-second
deadline. Install the locked dependencies and Chromium, provide a disposable
PostgreSQL ``DATABASE_URL`` and dummy AWS settings (see README), and have
ffmpeg/ffprobe on PATH. It explicitly selects the custom-player test and the
persistent playback and delayed transcript tests across both server-rendered
themes; explicit node IDs override marker filtering, and the JUnit report must
contain exactly the seven required passing identities with no duplicates or skips.
The identity includes the JUnit classname, browser, theme and response ordering.
For intentional test selection or parameter changes, update ``TESTS`` and
``EXPECTED_CASES`` in ``scripts/check_core_media.py`` and the independently written
``EXPECTED`` fixture in ``tests/test_core_media_gate.py``. Check the collected
node IDs and a real gate report rather than loosening the identity check.
Run the synthetic report/process-boundary tests with
``uv run --locked pytest tests/test_core_media_gate.py``; these tests simulate
POSIX and unsupported platforms without requiring a browser or database.
Synthetic subprocess regressions additionally exercise descendant cleanup on
supported systems and verify refusal elsewhere.
On supported POSIX systems (Linux/macOS), pytest starts a new session. Timeout
or interruption sends TERM to that process group, waits at most two seconds,
then sends KILL to any remaining members even if pytest already exited and
reaps pytest with a further two-second bound. Unsupported systems refuse before
launch. Children which deliberately detach into another session are not covered.
Temporary reports are removed on success, failure and interruption. Synthesized MP3/M4A
clips, transcript artifacts and temporary local storage exercise real media
routing, advancing clocks, seeking, cue/chapter highlights and playback across
navigation. A local WhiteNoise fixture serves media byte ranges (the Django
live-server file handler cannot support real Chromium seeking). External
analytics requests are suppressed. No staging or production
site is involved, and no additional Actions job is used.

Transcript requests are counted by the exact active episode URL. A browser
response gate lets the real HTTP request finish, then holds the response before
the player can consume it. The test requires exactly one initial fetch, keeps
that count through reopening and navigation, and checks one fetch for the next
episode too. Separate cases release old/current episode responses in both
orders and require the current episode's cues after both settle. No fixed sleep
or permissive baseline count can hide redundant initial requests.

The gate in ``tests/e2e/transcript-gate.js`` marks a JSON read settled in
``finally``, on the next task after the consumer's continuation. Disconnecting
the old player cancels its transcript hydration and aborts the response body;
the resulting ``AbortError`` is a valid terminal outcome for the retired
episode. Waiting only for successful JSON reads would deadlock the test when
releasing that response. The current episode must still render its expected
cues after both releases, so a failed current request cannot pass the test.
Run ``uv run --locked pytest tests/test_transcript_gate.py`` for a Node-based,
browser-free regression using native Response streams with successful, aborted
and malformed JSON bodies. Node is required for this regression. It supplements
the seven-case real Chromium gate; it does not replace playback verification.

Unreleased
----------

* Correct delayed-transcript test settlement for cancelled response bodies,
  preserving both response orders and all cue/fetch-count assertions.
* Recover a coherent, closed and retryable dock after synchronous player, panel
  or initial play failures, retaining the original error.
* Limit enhanced HTML to 2 MiB before parsing and retire pending page navigation
  on newer native fragment clicks, preserving continuous audio.

* Verify exact core-media report identities, including every theme and response
  ordering; terminate the owned POSIX process group on timeout or interruption.
* Protect closed/open local and social signup and existing-account login with
  synthetic allauth route tests; registration behavior is unchanged.

* Add a bounded local Chromium gate for actual custom/persistent media playback
  using only generated audio and local transcript storage.
* Require one transcript fetch per active episode through navigation/reopening,
  including explicitly delayed responses in either episode order.

* Batch concrete page resolution for persistent-player overview cards while
  preserving per-post payload and transcript identities.
* Batch existing cover renditions and skip blog/ancestor reads for explicit
  episode covers; retain compact-card missing-original fallback.

* Return keyboard focus to the current episode action or current content when
  closing the player, including after enhanced navigation and with reduced motion.
* Recover plain playback when View Transition startup throws or rejects, while
  preserving current-generation ownership and preventing duplicate activation.
