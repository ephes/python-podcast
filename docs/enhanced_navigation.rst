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

Tests
-----

``tests/e2e/test_enhanced_navigation.py`` runs the source file and the
committed minified build in a real browser against a small fixture server. The
repository has no separate JavaScript test runner; these tests use the
Playwright harness of the other browser tests, need no database content and run
with ``just test-e2e``. After changing ``persistent-player.js`` run
``just minify-static``.
