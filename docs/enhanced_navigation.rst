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

Payload identity
----------------

Every play card publishes its player payload as a ``json_script`` and points
to it by id (``data-cast-play`` and ``data-cast-episode-payload``); the script
looks the payload up with ``getElementById``. The payload depends on the post
(cover poster, transcript link), so the id names the audio and the post:
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

Card artwork
------------

Play cards request a small 128 px WebP rendition of the episode or blog cover.
If its original file is unavailable (``FileNotFoundError`` or Wagtail's
``SourceImageIOError``), the card uses the player poster already present in the
payload, which may be a cached rendition. This keeps the card renderable when
only the smaller rendition cannot be generated. Other errors still propagate;
this fallback does not repair or delete media files.

Tests
-----

``tests/e2e/test_enhanced_navigation.py`` runs the source file and the
committed minified build in a real browser against a small fixture server. The
repository has no separate JavaScript test runner; these tests use the
Playwright harness of the other browser tests, need no database content and run
in CI in the ``dock-transitions`` job. The exact isolated local command is::

    uv run --locked pytest -p no:django -p no:sugar -o addopts='' -m e2e tests/e2e/test_dock_transitions.py tests/e2e/test_enhanced_navigation.py

After changing ``persistent-player.js`` run
``just minify-static``.

``tests/e2e/test_dock_transitions.py`` exercises queued updates in both orders,
close during a pending switch, and activation without a transition, for both
source and minified assets. These isolated tests need no PostgreSQL or Vite:
``uv run pytest -p no:django -o addopts='' -m e2e tests/e2e/test_dock_transitions.py``.

Unreleased
----------

* Return keyboard focus to the current episode action or current content when
  closing the player, including after enhanced navigation and with reduced motion.
* Recover plain playback when View Transition startup throws or rejects, while
  preserving current-generation ownership and preventing duplicate activation.
