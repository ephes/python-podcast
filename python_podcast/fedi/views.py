import http.client
import logging
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit

import certifi
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect

logger = logging.getLogger(__name__)

FEDI_BASE_URL = "https://fedi.python-podcast.de"

# Timeouts in seconds for the upstream .well-known request: connect (including
# the TLS handshake), each socket read, and a hard overall deadline. When the
# deadline passes the upstream socket is shut down, which aborts any blocked
# read (headers, chunk framing or body), so a slowly dripping upstream cannot
# hold a worker longer than this.
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10
UPSTREAM_DEADLINE = 15
# .well-known documents are small; refuse anything larger than this.
MAX_UPSTREAM_BYTES = 1024 * 1024
# Besides Content-Type (and Location on redirects) only these upstream response
# headers are passed back to the client. Everything else, notably Set-Cookie,
# is dropped.
PASSED_RESPONSE_HEADERS = ("Cache-Control", "Access-Control-Allow-Origin", "Content-Encoding")

_ssl_context = None


class UpstreamTimeout(Exception):
    pass


class UpstreamError(Exception):
    pass


def _get_ssl_context():
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context(cafile=certifi.where())
    return _ssl_context


def _read_limited(upstream) -> bytes:
    chunks = []
    total = 0
    while True:
        # http.client's read1 does not decode anything and returns as soon as some
        # data is available (it handles chunked framing itself).
        chunk = upstream.read1(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPSTREAM_BYTES:
            raise UpstreamError("upstream response too large")
        chunks.append(chunk)
    if upstream.length:
        # read1 signals a premature EOF only by returning b"" with bytes outstanding.
        raise UpstreamError("upstream response truncated")
    return b"".join(chunks)


def _resolve(host, port, remaining):
    """
    Resolve ``host`` in a helper thread so that a stalled resolver cannot hold
    the request past the deadline (``getaddrinfo`` itself cannot be interrupted).
    """
    result = {}

    def resolve():
        try:
            result["addresses"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            result["error"] = exc

    resolver = threading.Thread(target=resolve, daemon=True)
    resolver.start()
    resolver.join(max(remaining, 0))
    if resolver.is_alive():
        raise UpstreamTimeout
    if "error" in result:
        raise UpstreamError(f"cannot resolve {host}: {result['error']}")
    return result["addresses"]


def _connect(conn, parts, deadline, deadline_hit, active):
    """
    Open the socket for ``conn`` ourselves, bounding DNS, every TCP connect
    attempt and the TLS handshake by the overall deadline.
    """

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0 or deadline_hit.is_set():
            raise UpstreamTimeout
        return left

    port = parts.port or (443 if parts.scheme == "https" else 80)
    last_error = None
    for family, socktype, proto, _, address in _resolve(parts.hostname, port, remaining()):
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(min(CONNECT_TIMEOUT, remaining()))
            sock.connect(address)
        except OSError as exc:
            sock.close()
            last_error = exc
            continue
        except UpstreamTimeout:
            sock.close()
            raise
        active["sock"] = sock
        if parts.scheme == "https":
            sock = _get_ssl_context().wrap_socket(sock, server_hostname=parts.hostname, do_handshake_on_connect=False)
            # Register the TLS socket before the handshake so the deadline timer
            # can abort it, and bound the handshake by the remaining time.
            active["sock"] = sock
            sock.settimeout(min(CONNECT_TIMEOUT, remaining()))
            sock.do_handshake()
        sock.settimeout(min(READ_TIMEOUT, remaining()))
        conn.sock = sock
        return
    if isinstance(last_error, TimeoutError):
        raise UpstreamTimeout from last_error
    raise UpstreamError(f"cannot connect to {parts.hostname}: {last_error}")


def _fetch(url, accept):
    """
    GET ``url`` and return ``(status, headers, body)``.

    Redirects are not followed and the body is not decoded (``identity`` is
    requested; any Content-Encoding is passed on unchanged). Raises
    ``UpstreamTimeout`` or ``UpstreamError``.
    """
    parts = urlsplit(url)
    # The socket is set up by _connect; http.client only speaks HTTP over it.
    conn = http.client.HTTPConnection(parts.hostname, parts.port)
    target = parts.path + (f"?{parts.query}" if parts.query else "")

    deadline_hit = threading.Event()
    # http.client detaches the socket from ``conn`` for responses that end on
    # close (HTTP/1.0, Connection: close, no Content-Length), so keep our own
    # reference for the deadline to abort.
    active = {}

    def abort():
        deadline_hit.set()
        sock = active.get("sock") or conn.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    deadline = time.monotonic() + UPSTREAM_DEADLINE
    timer = threading.Timer(UPSTREAM_DEADLINE, abort)
    timer.daemon = True
    timer.start()
    try:
        _connect(conn, parts, deadline, deadline_hit, active)
        conn.request(
            "GET",
            target,
            headers={"Accept": accept, "Accept-Encoding": "identity", "User-Agent": "fedi-wellknown-proxy"},
        )
        upstream = conn.getresponse()
        body = _read_limited(upstream)
        if deadline_hit.is_set():
            # The shutdown may surface as a clean EOF; never return a truncated body.
            raise UpstreamTimeout
        return upstream.status, upstream.headers, body
    except UpstreamTimeout:
        raise
    except UpstreamError:
        if deadline_hit.is_set():
            raise UpstreamTimeout from None
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if deadline_hit.is_set() or isinstance(exc, TimeoutError):
            raise UpstreamTimeout from exc
        raise UpstreamError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        timer.cancel()
        conn.close()
        if active.get("sock") is not None:
            active["sock"].close()


def _proxy_wellknown(request, path, *, forward_query=True, default_accept="*/*"):
    """
    Fetch a fediverse .well-known document from the fedi host and return it.

    Only GET and HEAD are allowed. No client headers are forwarded except
    ``Accept``, so cookies, Authorization and other credentials never reach the
    upstream. Only a small allow-list of upstream response headers is returned,
    so upstream cookies are never set on this site's domain.
    """
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET", "HEAD"])

    url = FEDI_BASE_URL + path
    if forward_query and request.GET:
        url += "?" + request.GET.urlencode()
    accept = request.headers.get("Accept") or default_accept

    try:
        status, headers, content = _fetch(url, accept)
    except UpstreamTimeout:
        logger.warning("Timeout fetching %s", path)
        return HttpResponse("Upstream timeout", status=504, content_type="text/plain")
    except UpstreamError as exc:
        logger.warning("Failed to fetch %s: %s", path, exc)
        return HttpResponse("Bad gateway", status=502, content_type="text/plain")

    try:
        return _build_response(request, url, status, headers, content)
    except ValueError as exc:
        # Invalid upstream status or header values (BadHeaderError is a ValueError),
        # or a malformed redirect location.
        logger.warning("Invalid upstream response for %s: %s", path, exc)
        return HttpResponse("Bad gateway", status=502, content_type="text/plain")


def _build_response(request, url, status, headers, content):
    response = HttpResponse(
        b"" if request.method == "HEAD" else content,
        status=status,
        content_type=headers.get("Content-Type") or "application/octet-stream",
    )
    for name in PASSED_RESPONSE_HEADERS:
        value = headers.get(name)
        if value is not None:
            response[name] = value
    location = headers.get("Location")
    if 300 <= status < 400 and location:
        # Redirects are not followed; pass them on, absolute against the fedi host.
        response["Location"] = urljoin(url, location)
    return response


def wellknown_webfinger(request):
    return _proxy_wellknown(request, "/.well-known/webfinger", default_accept="application/jrd+json")


def wellknown_hostmeta(request):
    return _proxy_wellknown(request, "/.well-known/host-meta", default_accept="application/xrd+xml")


def wellknown_nodeinfo(request):
    return _proxy_wellknown(request, "/.well-known/nodeinfo", forward_query=False, default_accept="application/json")


def username_redirect_jochen(request):
    return HttpResponseRedirect("https://fedi.python-podcast.de/@jochen")


def username_redirect_show(request):
    return HttpResponseRedirect("https://fedi.python-podcast.de/@show")
