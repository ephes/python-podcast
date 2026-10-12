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
a ``#fragment``, ``download`` or foreign ``target``, is not driven by htmx and
is not inside a form, and its path is not one of the excluded routes: admin,
CMS, account/login/logout, media, static, API, comments, feeds and
download/media file suffixes.

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

Back and forward
----------------

Back/forward to an entry created by enhanced navigation fetches that entry's
URL again. If it now redirects to another allowed page, the URL of the
**current** history entry is replaced with the final one (same state, no new
entry, forward entries kept), so the address bar and relative links such as
``?page=2`` match the page shown. A redirect to an excluded route or another
origin falls back to a full navigation, as above.

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

Tests
-----

``tests/e2e/test_enhanced_navigation.py`` runs the source file and the
committed minified build in a real browser against a small fixture server. The
repository has no separate JavaScript test runner; these tests use the
Playwright harness of the other browser tests, need no database content and run
with ``just test-e2e``. After changing ``persistent-player.js`` run
``just minify-static``.
