"""
Tests for the fediverse .well-known proxy, run against a real local HTTP server
standing in for the fedi host.
"""

import datetime
import http.client
import http.server
import ipaddress
import socket
import ssl
import threading
import time
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.core import mail

from python_podcast.fedi import views

pytestmark = pytest.mark.django_db


class Upstream(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), UpstreamHandler)
        self.requests = []
        # path -> callable(handler); default: a small JSON document
        self.routes = {}

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class UpstreamHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.server.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers)})
        route = self.server.routes.get(urlsplit(self.path).path, send_document)
        route(self)

    do_POST = do_PUT = do_DELETE = do_GET

    def log_message(self, *args):
        pass


def send_document(handler, body=b'{"links": []}', status=200, headers=None):
    headers = {"Content-Type": "application/json", **(headers or {})}
    handler.send_response(status)
    for name, value in headers.items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@pytest.fixture
def upstream(monkeypatch):
    server = Upstream()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(views, "FEDI_BASE_URL", server.base_url)
    monkeypatch.setattr(views, "CONNECT_TIMEOUT", 1)
    monkeypatch.setattr(views, "READ_TIMEOUT", 0.5)
    monkeypatch.setattr(views, "UPSTREAM_DEADLINE", 1)
    yield server
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize(
    "path, query, upstream_path, content_type",
    [
        (
            "/.well-known/webfinger",
            "?resource=acct:jochen@python-podcast.de",
            "/.well-known/webfinger?resource=acct%3Ajochen%40python-podcast.de",
            "application/jrd+json",
        ),
        ("/.well-known/host-meta", "", "/.well-known/host-meta", "application/xrd+xml"),
        ("/.well-known/nodeinfo", "?ignored=1", "/.well-known/nodeinfo", "application/json"),
    ],
)
def test_happy_path_per_endpoint(client, upstream, path, query, upstream_path, content_type):
    upstream.routes[path] = lambda h: send_document(
        h,
        body=b"document",
        headers={"Content-Type": content_type, "Cache-Control": "max-age=60", "Access-Control-Allow-Origin": "*"},
    )

    response = client.get(path + query)

    assert response.status_code == 200
    assert response.content == b"document"
    assert response["Content-Type"] == content_type
    assert response["Cache-Control"] == "max-age=60"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert len(upstream.requests) == 1
    assert upstream.requests[0]["method"] == "GET"
    assert upstream.requests[0]["path"] == upstream_path
    assert upstream.requests[0]["headers"]["Accept"] == content_type


def test_no_credentials_forwarded(client, upstream):
    client.cookies["sessionid"] = "secret-session"
    client.cookies["csrftoken"] = "secret-csrf"

    client.get(
        "/.well-known/webfinger?resource=acct:jochen@python-podcast.de",
        HTTP_AUTHORIZATION="Bearer secret-token",
        HTTP_X_CUSTOM="value",
        HTTP_ACCEPT="application/jrd+json",
    )

    sent = {name.lower(): value for name, value in upstream.requests[0]["headers"].items()}
    assert "cookie" not in sent
    assert "authorization" not in sent
    assert "x-custom" not in sent
    assert sent["accept"] == "application/jrd+json"
    assert "secret" not in repr(sent)


def test_query_string_sent_once(client, upstream):
    client.get("/.well-known/webfinger?resource=acct:jochen@python-podcast.de&rel=a&rel=b")

    assert upstream.requests[0]["path"] == (
        "/.well-known/webfinger?resource=acct%3Ajochen%40python-podcast.de&rel=a&rel=b"
    )


def test_set_cookie_and_other_headers_not_copied(client, upstream):
    upstream.routes["/.well-known/webfinger"] = lambda h: send_document(
        h, headers={"Set-Cookie": "upstream_session=evil; Path=/", "X-Upstream": "leak"}
    )

    response = client.get("/.well-known/webfinger?resource=acct:jochen@python-podcast.de")

    assert response.status_code == 200
    assert "upstream_session" not in response.cookies
    assert not response.has_header("Set-Cookie")
    assert not response.has_header("X-Upstream")


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_unsafe_methods_rejected(client, upstream, method):
    response = getattr(client, method)("/.well-known/webfinger?resource=acct:jochen@python-podcast.de")

    assert response.status_code == 405
    assert upstream.requests == []


def test_head_returns_no_body(client, upstream):
    response = client.head("/.well-known/nodeinfo")

    assert response.status_code == 200
    assert response.content == b""


def test_upstream_error_status_passed_through(client, upstream):
    upstream.routes["/.well-known/webfinger"] = lambda h: send_document(h, body=b"not found", status=404)

    response = client.get("/.well-known/webfinger?resource=acct:nobody@python-podcast.de")

    assert response.status_code == 404


def test_redirect_is_passed_on_not_followed(client, upstream):
    def redirect_with_large_body(handler):
        handler.send_response(302)
        handler.send_header("Location", "/.well-known/nodeinfo/2.0")
        handler.send_header("Set-Cookie", "a=b")
        handler.end_headers()  # no Content-Length: body runs until close
        handler.wfile.write(b"x" * (views.MAX_UPSTREAM_BYTES + 100))
        handler.close_connection = True

    upstream.routes["/.well-known/nodeinfo"] = redirect_with_large_body

    response = client.get("/.well-known/nodeinfo")

    # The oversized redirect body is subject to the size limit like any other.
    assert response.status_code == 502
    assert len(upstream.requests) == 1

    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(
        h, status=302, headers={"Location": "/.well-known/nodeinfo/2.0", "Set-Cookie": "a=b"}
    )

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 302
    assert response["Location"] == upstream.base_url + "/.well-known/nodeinfo/2.0"
    assert not response.has_header("Set-Cookie")
    assert len(upstream.requests) == 2  # not followed


@pytest.mark.parametrize("location_fields", [[], ["/other"], ["/next"]], ids=["single", "conflicting", "repeated"])
def test_proxy_requires_a_single_location_for_redirects(rf, monkeypatch, location_fields):
    headers = http.client.HTTPMessage()
    headers["Location"] = "/next"
    for location in location_fields:
        headers["location"] = location
    origin = "https://fedi.example.invalid"
    monkeypatch.setattr(views, "FEDI_BASE_URL", origin)
    monkeypatch.setattr(views, "_fetch", lambda *args: (302, headers, b""))

    response = views.wellknown_nodeinfo(rf.get("/.well-known/nodeinfo"))

    if location_fields:
        assert response.status_code == 502
        assert response.content == b"Bad gateway"
        assert "Location" not in response
    else:
        assert response.status_code == 302
        assert response["Location"] == origin + "/next"


def test_oversized_upstream_returns_502(client, upstream, caplog):
    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(h, body=b"x" * (views.MAX_UPSTREAM_BYTES + 1))

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502
    assert "response-too-large" in caplog.text


def test_connection_refused_returns_502(client, upstream):
    upstream.shutdown()
    upstream.server_close()

    response = client.get("/.well-known/host-meta")

    assert response.status_code == 502


def test_stalled_body_returns_504(client, upstream):
    def stall(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "100")
        handler.end_headers()
        handler.wfile.flush()
        time.sleep(2)

    upstream.routes["/.well-known/webfinger"] = stall

    response = client.get("/.well-known/webfinger?resource=acct:jochen@python-podcast.de")

    assert response.status_code == 504


@pytest.mark.parametrize("phase", ["headers", "chunked", "body", "until-close", "connection-close", "http10"])
def test_dripping_upstream_hits_overall_deadline(client, upstream, phase):
    """Each byte arrives within the read timeout, but the whole response never finishes."""
    stop = threading.Event()

    def drip(handler):
        handler.wfile.write(b"HTTP/1.0 200 OK\r\n" if phase == "http10" else b"HTTP/1.1 200 OK\r\n")
        if phase == "headers":
            handler.wfile.write(b"X-Slow: ")
        elif phase == "chunked":
            handler.wfile.write(b"Transfer-Encoding: chunked\r\n\r\n1")
        elif phase == "body":
            handler.wfile.write(b"Content-Length: 1000\r\n\r\n")
        elif phase == "connection-close":
            handler.wfile.write(b"Connection: close\r\nContent-Length: 1000\r\n\r\n")
        else:  # until-close / http10: no Content-Length, body ends on close
            handler.wfile.write(b"\r\n")
        handler.wfile.flush()
        while not stop.is_set():
            try:
                handler.wfile.write(b"0" if phase == "chunked" else b"a")
                handler.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)

    upstream.routes["/.well-known/nodeinfo"] = drip

    started = time.monotonic()
    response = client.get("/.well-known/nodeinfo")
    elapsed = time.monotonic() - started
    stop.set()

    assert response.status_code == 504
    assert elapsed < views.UPSTREAM_DEADLINE + 0.5


def test_truncated_body_returns_502(client, upstream, caplog):
    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "100")
        handler.end_headers()
        handler.wfile.write(b"{}")
        handler.close_connection = True

    upstream.routes["/.well-known/nodeinfo"] = truncated

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502
    assert "response-truncated" in caplog.text


def test_content_encoding_passed_through_undecoded(client, upstream):
    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(
        h, body=b"\x1f\x8bnot-really-gzip", headers={"Content-Encoding": "gzip"}
    )

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 200
    assert response.content == b"\x1f\x8bnot-really-gzip"
    assert response["Content-Encoding"] == "gzip"
    assert upstream.requests[0]["headers"]["Accept-Encoding"] == "identity"


def test_repeated_content_encodings_preserved_in_wire_order(rf, monkeypatch):
    body = b"\x1f\x8bencoded-document"
    headers = http.client.HTTPMessage()
    headers["Content-Encoding"] = "gzip, br"
    headers["content-encoding"] = "gzip"
    headers["Set-Cookie"] = "upstream=synthetic"
    monkeypatch.setattr(views, "_fetch", lambda *args: (200, headers, body))

    response = views.wellknown_nodeinfo(rf.get("/.well-known/nodeinfo"))

    assert response.status_code == 200
    assert response.content == body
    assert response["Content-Encoding"] == "gzip, br, gzip"
    assert not response.cookies
    assert "Set-Cookie" not in response


def test_stalled_dns_resolution_hits_deadline(client, upstream, monkeypatch):
    real_getaddrinfo = views.socket.getaddrinfo

    def slow_getaddrinfo(*args, **kwargs):
        time.sleep(3)
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(views.socket, "getaddrinfo", slow_getaddrinfo)

    started = time.monotonic()
    response = client.get("/.well-known/nodeinfo")
    elapsed = time.monotonic() - started

    assert response.status_code == 504
    assert elapsed < views.UPSTREAM_DEADLINE + 0.5


def test_unresolvable_host_returns_502(client, upstream, monkeypatch):
    def fail(*args, **kwargs):
        raise views.socket.gaierror("Name or service not known")

    monkeypatch.setattr(views.socket, "getaddrinfo", fail)

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502


@pytest.mark.parametrize(
    "raw_headers",
    [
        b"Content-Type: application/json\r\n folded\r\nContent-Length: 2\r\n",
        b"Location: http://[::1\r\nContent-Length: 2\r\n",
    ],
    ids=["folded-content-type", "malformed-location"],
)
def test_invalid_upstream_headers_return_502(client, upstream, raw_headers):
    def invalid(handler):
        handler.wfile.write(b"HTTP/1.1 302 Found\r\n" + raw_headers + b"\r\n{}")
        handler.close_connection = True

    upstream.routes["/.well-known/nodeinfo"] = invalid

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502


def _write_self_signed_cert(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file = directory / "cert.pem"
    key_file = directory / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


class TLSUpstream(Upstream):
    handshake_delay = 0

    def __init__(self, cert_file, key_file):
        super().__init__()
        self.tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls_context.load_cert_chain(cert_file, key_file)

    @property
    def base_url(self):
        return f"https://127.0.0.1:{self.server_address[1]}"

    def finish_request(self, request, client_address):
        time.sleep(self.handshake_delay)
        try:
            tls_request = self.tls_context.wrap_socket(request, server_side=True)
        except OSError:
            return
        try:
            self.RequestHandlerClass(tls_request, client_address, self)
        finally:
            tls_request.close()


@pytest.fixture
def tls_upstream(monkeypatch, tmp_path):
    cert_file, key_file = _write_self_signed_cert(tmp_path)
    server = TLSUpstream(cert_file, key_file)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(views, "FEDI_BASE_URL", server.base_url)
    monkeypatch.setattr(views, "_ssl_context", ssl.create_default_context(cafile=str(cert_file)))
    monkeypatch.setattr(views, "CONNECT_TIMEOUT", 1)
    monkeypatch.setattr(views, "READ_TIMEOUT", 0.5)
    monkeypatch.setattr(views, "UPSTREAM_DEADLINE", 1)
    yield server
    server.shutdown()
    server.server_close()


def test_https_upstream_happy_path(client, tls_upstream):
    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 200
    assert response.content == b'{"links": []}'


def test_https_upstream_with_untrusted_cert_returns_502(client, tls_upstream, monkeypatch):
    monkeypatch.setattr(views, "_ssl_context", ssl.create_default_context())

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502


def test_slow_tls_handshake_then_dripping_body_hits_deadline(client, tls_upstream, monkeypatch):
    """A handshake finishing just before the deadline must not let the body read run on."""
    monkeypatch.setattr(views, "CONNECT_TIMEOUT", 5)
    monkeypatch.setattr(views, "READ_TIMEOUT", 5)
    tls_upstream.handshake_delay = 0.8
    stop = threading.Event()

    def drip(handler):
        handler.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        handler.wfile.flush()
        while not stop.is_set():
            try:
                handler.wfile.write(b"a")
                handler.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)

    tls_upstream.routes["/.well-known/nodeinfo"] = drip

    started = time.monotonic()
    response = client.get("/.well-known/nodeinfo")
    elapsed = time.monotonic() - started
    stop.set()

    assert response.status_code == 504
    assert elapsed < views.UPSTREAM_DEADLINE + 0.5


def test_stalled_tls_handshake_hits_deadline(client, tls_upstream, monkeypatch):
    monkeypatch.setattr(views, "CONNECT_TIMEOUT", 5)
    tls_upstream.handshake_delay = 3

    started = time.monotonic()
    response = client.get("/.well-known/nodeinfo")
    elapsed = time.monotonic() - started

    assert response.status_code == 504
    assert elapsed < views.UPSTREAM_DEADLINE + 0.5


def stall_headers(handler):
    time.sleep(2)


def test_upstream_failures_do_not_mail_admins(client, upstream, caplog):
    upstream.routes["/.well-known/webfinger"] = stall_headers

    timeout = client.get("/.well-known/webfinger?resource=acct:show@python-podcast.de")
    upstream.shutdown()
    upstream.server_close()
    refused = client.get("/.well-known/host-meta")

    assert (timeout.status_code, refused.status_code) == (504, 502)
    assert mail.outbox == []
    # The proxy's own warnings stay the record of the failures.
    assert "Timeout fetching /.well-known/webfinger" in caplog.text
    assert "Failed to fetch /.well-known/host-meta" in caplog.text


def test_invalid_upstream_response_does_not_mail_admins(client, upstream):
    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(h, status=302, headers={"Location": "http://["})

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502
    assert mail.outbox == []


def test_error_in_fedi_view_still_mails_admins(client, upstream, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug in the proxy view")

    monkeypatch.setattr(views, "_build_response", broken)
    client.raise_request_exception = False

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 500
    assert len(mail.outbox) == 1


class RaiseAfterGatewayErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 504:
            raise RuntimeError("middleware failed after a proxy 504")
        return response


def test_middleware_error_after_upstream_failure_still_mails_admins(client, upstream, settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, f"{__name__}.RaiseAfterGatewayErrorMiddleware"]
    upstream.routes["/.well-known/webfinger"] = stall_headers
    client.raise_request_exception = False

    response = client.get("/.well-known/webfinger?resource=acct:show@python-podcast.de")

    assert response.status_code == 500
    assert len(mail.outbox) == 1


def test_resolver_capacity_survives_timeout_and_recovers(client, monkeypatch):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(views, "_resolver_slots", slots, raising=False)
    monkeypatch.setattr(views, "UPSTREAM_DEADLINE", 0.02)
    release = threading.Event()
    completed = threading.Event()
    calls = []

    def stalled(*args, **kwargs):
        calls.append(args)
        try:
            assert release.wait(5)
            raise socket.gaierror("synthetic DNS failure")
        finally:
            if len(calls) == 2:
                completed.set()

    monkeypatch.setattr(views.socket, "getaddrinfo", stalled)
    try:
        assert client.get("/.well-known/nodeinfo").status_code == 504
        assert client.get("/.well-known/nodeinfo").status_code == 504
        for _ in range(8):
            assert client.get("/.well-known/nodeinfo").status_code == 502
        assert len(calls) == 2
    finally:
        release.set()
    assert completed.wait(5)
    # Acquiring both slots waits for the helpers' finally blocks, without sleeps.
    assert slots.acquire(timeout=5)
    assert slots.acquire(timeout=5)
    slots.release()
    slots.release()
    assert client.get("/.well-known/nodeinfo").status_code == 502
    assert len(calls) == 3


def test_resolver_start_failure_returns_capacity(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(views, "_resolver_slots", slots, raising=False)
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("no threads")))
        with pytest.raises(views.UpstreamError):
            views._resolve("synthetic.invalid", 443, 1)
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.parametrize("method", ["get", "head", "post"])
@pytest.mark.parametrize("outcome", [200, 302, 404, "timeout", "connection", "invalid-header"])
def test_proxy_always_varies_on_accept(rf, monkeypatch, method, outcome):
    def fetch(*args):
        if outcome == "timeout":
            raise views.UpstreamTimeout
        if outcome == "connection":
            raise views.UpstreamError("synthetic connection failure")
        if outcome == "invalid-header":
            return 200, {"Content-Type": "invalid\r\nheader"}, b"document"
        return outcome, {"Content-Type": "application/json", "Location": "/next"}, b"document"

    monkeypatch.setattr(views, "_fetch", fetch)
    response = views.wellknown_webfinger(getattr(rf, method)("/.well-known/webfinger"))

    expected = {"timeout": 504, "connection": 502, "invalid-header": 502}.get(outcome, outcome)
    assert response.status_code == (405 if method == "post" else expected)
    assert response["Vary"] == "Accept"
    if method == "head":
        assert response.content == b""


@pytest.mark.parametrize("upstream_vary, expected", [("aCcEpT, Cookie, Origin", "accept"), ("*", "*")])
def test_only_supported_upstream_vary_is_preserved(client, upstream, upstream_vary, expected):
    def document(handler):
        # Repeated Vary fields must also preserve the wildcard.
        handler.send_response(200)
        handler.send_header("Vary", "Accept-Encoding")
        handler.send_header("Vary", upstream_vary)
        handler.send_header("Content-Length", "2")
        handler.end_headers()
        handler.wfile.write(b"{}")

    upstream.routes["/.well-known/nodeinfo"] = document
    response = client.get("/.well-known/nodeinfo")

    assert response["Vary"].lower() == expected


def test_shared_cache_keeps_accept_representations_separate(rf, monkeypatch):
    from django.core.cache import cache
    from django.middleware.cache import CacheMiddleware

    calls = []

    def fetch(url, accept):
        calls.append(accept)
        return 200, {"Content-Type": accept}, accept.encode()

    monkeypatch.setattr(views, "_fetch", fetch)
    cached = CacheMiddleware(views.wellknown_webfinger, cache_timeout=60, key_prefix="fedi-accept-regression")
    cache.clear()
    try:
        for accept in ["application/jrd+json", "application/json"] * 2:
            response = cached(rf.get("/.well-known/webfinger?resource=synthetic", HTTP_ACCEPT=accept))
            assert response.content == accept.encode()
            assert response["Content-Type"] == accept
        assert calls == ["application/jrd+json", "application/json"]
    finally:
        cache.clear()


@pytest.mark.parametrize("directive", ["no-store", "private"])
def test_repeated_cache_control_fields_prevent_shared_cache_storage(rf, monkeypatch, directive):
    from django.core.cache import cache
    from django.middleware.cache import CacheMiddleware

    headers = http.client.HTTPMessage()
    headers["Cache-Control"] = "max-age=60"
    headers["cache-control"] = directive
    fetch = Mock(return_value=(200, headers, b"document"))
    monkeypatch.setattr(views, "_fetch", fetch)
    cached = CacheMiddleware(views.wellknown_nodeinfo, cache_timeout=60, key_prefix="fedi-cache-control-regression")
    cache.clear()
    try:
        responses = [cached(rf.get("/.well-known/nodeinfo")) for _ in range(2)]

        assert fetch.call_count == 2
        assert [response.status_code for response in responses] == [200, 200]
        assert [response["Cache-Control"] for response in responses] == [f"max-age=60, {directive}"] * 2
    finally:
        cache.clear()


def test_invalid_repeated_cache_control_field_returns_502(rf, monkeypatch):
    headers = http.client.HTTPMessage()
    headers["Cache-Control"] = "max-age=60"
    headers["Cache-Control"] = "no-store\r\n invalid"
    monkeypatch.setattr(views, "_fetch", lambda *args: (200, headers, b"document"))

    response = views.wellknown_nodeinfo(rf.get("/.well-known/nodeinfo"))

    assert response.status_code == 502
    assert response.content == b"Bad gateway"


@pytest.mark.parametrize(
    "phase, category, status",
    [
        ("dns", "dns", 502),
        ("connect", "connect", 502),
        ("tls", "tls", 502),
        ("request", "request", 502),
        ("protocol", "protocol", 502),
        ("transport", "transport", 502),
        ("timeout", "timeout", 504),
        ("capacity", "resolver-capacity", 502),
        ("resolver-start", "resolver-start", 502),
        ("invalid-header", "invalid-response", 502),
        ("invalid-location", "invalid-response", 502),
        ("invalid-status", "invalid-response", 502),
        ("unknown", "upstream-failure", 502),
    ],
)
def test_upstream_diagnostics_never_log_remote_text(rf, monkeypatch, caplog, phase, category, status):
    from types import SimpleNamespace

    secret = "synthetic-query-token\r\nINJECTED-LOG"

    def fail(error):
        def raise_error(*args, **kwargs):
            raise error

        return raise_error

    conn = SimpleNamespace(sock=None, request=lambda *a, **kw: None, close=lambda: None)
    monkeypatch.setattr(views.http.client, "HTTPConnection", lambda *a: conn)
    if phase == "dns":
        monkeypatch.setattr(views.socket, "getaddrinfo", fail(socket.gaierror(secret)))
    elif phase == "connect":
        monkeypatch.setattr(
            views, "_resolve", lambda *a: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 1))]
        )
        sock = SimpleNamespace(settimeout=lambda *a: None, connect=fail(OSError(secret)), close=lambda: None)
        monkeypatch.setattr(views.socket, "socket", lambda *a: sock)
    elif phase == "capacity":
        monkeypatch.setattr(views, "_resolver_slots", threading.BoundedSemaphore(0))
    elif phase == "resolver-start":
        # Don't replace Timer.start: only the DNS helper fails to start.
        real_start = threading.Thread.start

        def start(thread):
            if isinstance(thread, threading.Timer):
                return real_start(thread)
            raise RuntimeError(secret)

        monkeypatch.setattr(threading.Thread, "start", start)
    elif phase == "unknown":
        monkeypatch.setattr(views, "_fetch", fail(views.UpstreamError(secret)))
    elif phase.startswith("invalid-"):
        headers = {"Content-Type": secret} if phase == "invalid-header" else {"Location": "http://[" + secret}
        upstream_status = 99 if phase == "invalid-status" else 302
        monkeypatch.setattr(views, "_fetch", lambda *a: (upstream_status, headers, b"document"))
    else:
        monkeypatch.setattr(views, "_connect", lambda *a: None)
        error = {
            "tls": ssl.SSLError(secret),
            "request": ValueError(secret),
            "protocol": views.http.client.BadStatusLine(secret),
            "transport": OSError(secret),
            "timeout": TimeoutError(secret),
        }[phase]
        if phase == "protocol":
            conn.getresponse = fail(error)
        else:
            conn.request = fail(error)

    response = views.wellknown_webfinger(rf.get("/.well-known/webfinger?resource=synthetic-query-token"))

    assert response.status_code == status
    assert response.content == (b"Upstream timeout" if status == 504 else b"Bad gateway")
    records = [record for record in caplog.records if record.name == views.__name__]
    assert len(records) == 1
    assert "/.well-known/webfinger" in records[0].getMessage()
    assert "synthetic-query-token" not in caplog.text
    assert "INJECTED-LOG" not in caplog.text
    assert records[0].exc_info is None
    assert category in records[0].getMessage()
