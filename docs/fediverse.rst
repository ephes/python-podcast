Fediverse discovery
===================

The ``python_podcast.fedi`` app lets the site's domain act as the fediverse identity
domain while the actual server runs at ``https://fedi.python-podcast.de``.

``/@jochen`` and ``/@show``
   Redirect to the profile on the fedi host.

``/.well-known/webfinger``, ``/.well-known/host-meta``, ``/.well-known/nodeinfo``
   Fetched from the same path on the fedi host and returned to the client
   (``python_podcast.fedi.views._proxy_wellknown``). The proxy is deliberately
   narrow:

   * Only ``GET`` and ``HEAD`` are allowed; other methods get ``405``.
     Upstream is always fetched with ``GET``.
   * The only client header sent upstream is ``Accept``. Cookies (session,
     CSRF), ``Authorization`` and every other request header stay on this
     site.
   * The query string is forwarded once (webfinger and host-meta only;
     nodeinfo takes no query).
   * Only the upstream status, ``Content-Type``, ``Cache-Control``,
     ``Access-Control-Allow-Origin`` and ``Content-Encoding`` are returned.
     Upstream ``Set-Cookie`` and all other headers are dropped.
   * The body is not decoded: ``Accept-Encoding: identity`` is requested and
     any ``Content-Encoding`` the upstream still uses is passed on as is.
   * Upstream redirects are not followed; a ``3xx`` is returned to the client
     with its ``Location`` made absolute against the fedi host.
   * Timeouts: 3 s per TCP connect attempt, 10 s per socket read and a hard
     15 s overall deadline that also bounds DNS resolution (done in a helper
     thread), every connect attempt and the TLS handshake; when it passes, the
     upstream socket is shut down. A timeout returns ``504``; any other
     connection or protocol error, a truncated body, a body larger than
     1 MiB, or an invalid upstream status, header or redirect location returns
     ``502``.
   * The request is made with the standard library (``http.client``) and
     verified against the ``certifi`` CA bundle.

After deploying changes to this app, check that WebFinger still resolves, for
example ``curl 'https://python-podcast.de/.well-known/webfinger?resource=acct:show@python-podcast.de'``.
