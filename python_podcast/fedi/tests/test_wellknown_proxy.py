"""
Tests for the fediverse .well-known proxy, run against a real local HTTP server
standing in for the fedi host.
"""

import datetime
import http.server
import ipaddress
import ssl
import threading
import time
from urllib.parse import urlsplit

import pytest

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


def test_oversized_upstream_returns_502(client, upstream):
    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(h, body=b"x" * (views.MAX_UPSTREAM_BYTES + 1))

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502


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


def test_truncated_body_returns_502(client, upstream):
    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "100")
        handler.end_headers()
        handler.wfile.write(b"{}")
        handler.close_connection = True

    upstream.routes["/.well-known/nodeinfo"] = truncated

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 502


def test_content_encoding_passed_through_undecoded(client, upstream):
    upstream.routes["/.well-known/nodeinfo"] = lambda h: send_document(
        h, body=b"\x1f\x8bnot-really-gzip", headers={"Content-Encoding": "gzip"}
    )

    response = client.get("/.well-known/nodeinfo")

    assert response.status_code == 200
    assert response.content == b"\x1f\x8bnot-really-gzip"
    assert response["Content-Encoding"] == "gzip"
    assert upstream.requests[0]["headers"]["Accept-Encoding"] == "identity"


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
