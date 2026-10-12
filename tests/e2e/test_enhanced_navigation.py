"""Browser tests for the enhanced-navigation JavaScript in persistent-player.js.

The repository has no JavaScript test runner; its JavaScript is exercised by the
Playwright e2e suite. These tests keep to that harness but need no Django, no
database and no Vite build: a throwaway stdlib HTTP server hands the real
``persistent-player.js`` (source and committed minified build) to a real browser
together with fixture pages that redirect, stall or change between requests.
A second server on another port plays the foreign origin.

Run with ``just test-e2e`` (they carry the ``e2e`` marker like the other browser
tests).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

STATIC_JS = Path(__file__).resolve().parents[2] / "python_podcast" / "static" / "js"
NAV_HEADER = "X-Cast-Enhanced-Nav"
# Deadline the fixture pages configure via data-cast-nav-timeout-ms.
NAV_TIMEOUT_MS = 600
# Longer than the deadline: "nothing happened" assertions wait this long.
SETTLE_MS = NAV_TIMEOUT_MS + 600


def _page_html(marker: str, script: str, *, links: dict[str, str] | None = None) -> bytes:
    anchors = "".join(f'<a id="{link_id}" href="{href}">{link_id}</a>' for link_id, href in (links or {}).items())
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{marker}</title></head>
<body>
<div id="cast-persistent-player" data-cast-nav-timeout-ms="{NAV_TIMEOUT_MS}">
  <audio id="fixture-audio" src="/audio.wav" loop></audio>
</div>
<div id="paging-area">
  <h1>{marker}</h1>
  <p id="marker">{marker}</p>
  {anchors}
  <a id="relative-page-2" href="?page=2">page 2</a>
</div>
<script src="/js/{script}"></script>
</body></html>""".encode()


def _silent_wav(seconds: int = 30, rate: int = 8000) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(rate)
        wav.writeframes(b"\x80" * rate * seconds)
    return buffer.getvalue()


class _Site:
    """State shared between a fixture server and the test."""

    def __init__(self, script: str):
        self.script = script
        self.requests: list[tuple[str, bool]] = []  # (path, sent the enhanced-nav header)
        self.redirects: dict[str, str] = {}
        self.release = threading.Event()  # set at teardown to free stalled handlers
        self.foreign_base = ""
        self.lock = threading.Lock()

    def seen(self, path: str, *, enhanced: bool) -> int:
        with self.lock:
            return self.requests.count((path, enhanced))


LINKS = {
    "to-b": "/page/b",
    "to-c": "/page/c",
    "to-old": "/old",
    "to-public-redirect": "/redirect/public",
    "to-login-redirect": "/redirect/login",
    "to-admin-redirect": "/redirect/admin",
    "to-foreign-redirect": "/redirect/foreign",
    "to-stall": "/stall",
    "to-stall-body": "/stall-body",
}


def _make_handler(site: _Site, *, foreign: bool):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep pytest output quiet
            pass

        def _send(self, body: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200, headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str):
            self._send(b"", status=302, headers={"Location": location})

        def _cors(self) -> dict[str, str]:
            return {
                # A redirected cross-origin request carries "Origin: null".
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": NAV_HEADER,
            }

        def do_OPTIONS(self):
            self._send(b"", status=204, headers=self._cors())

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            enhanced = self.headers.get(NAV_HEADER) == "1"
            with site.lock:
                site.requests.append((("foreign:" if foreign else "") + path, enhanced))
                redirect_to = site.redirects.get(path)

            if foreign:
                # CORS-readable and carrying the swap target: only the final-URL
                # check keeps it out of the document.
                self._send(_page_html("FOREIGN PAGE", site.script), headers=self._cors())
                return
            if redirect_to:
                self._redirect(redirect_to)
            elif path.startswith("/js/"):
                self._send((STATIC_JS / path.removeprefix("/js/")).read_bytes(), "text/javascript")
            elif path == "/audio.wav":
                self._send(_silent_wav(), "audio/wav")
            elif path.startswith("/page/") or path == "/old":
                self._send(_page_html(path.rsplit("/", 1)[-1].upper() + " PAGE", site.script, links=LINKS))
            elif path == "/redirect/public":
                self._redirect("/page/b")
            elif path == "/redirect/login":
                self._redirect("/accounts/login/")
            elif path == "/redirect/admin":
                self._redirect("/admin/")
            elif path == "/redirect/foreign":
                self._redirect(site.foreign_base + "/landing")
            elif path in ("/accounts/login/", "/admin/"):
                # Excluded routes that would be swappable if they were imported.
                self._send(_page_html("PRIVATE FORM", site.script))
            elif path in ("/stall", "/stall-body") and enhanced:
                if path == "/stall-body":
                    # Headers and the first bytes arrive, the rest never does.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    self.wfile.write(b"<!doctype html><html><body>")
                    self.wfile.flush()
                site.release.wait(30)
                self.close_connection = True
            elif path in ("/stall", "/stall-body"):
                # The full-load fallback (no enhanced-nav header) is answered.
                self._send(_page_html("STALL FALLBACK PAGE", site.script, links=LINKS))
            else:
                self._send(b"not found", "text/plain", status=404)

    return Handler


@contextmanager
def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


# The deployed asset is the minified build, so both files are exercised.
@pytest.fixture(params=["persistent-player.js", "persistent-player.min.js"])
def site(request):
    state = _Site(request.param)
    with _serve(_make_handler(state, foreign=False)) as base, _serve(_make_handler(state, foreign=True)) as foreign:
        state.base = base
        state.foreign_base = foreign
        try:
            yield state
        finally:
            state.release.set()


# Records, across full page loads, every document the navigation code parses or
# imports and every fetch it aborts. Installed before any page script runs.
INIT_SCRIPT = """
(() => {
  const parse = DOMParser.prototype.parseFromString;
  DOMParser.prototype.parseFromString = function (text, type) {
    window.__recordParsed(String(text));
    return parse.call(this, text, type);
  };
  const realFetch = window.fetch;
  window.__aborted = [];
  window.fetch = function (input, init) {
    if (init && init.signal) {
      init.signal.addEventListener("abort", () => window.__aborted.push(String(input)));
    }
    return realFetch.call(this, input, init);
  };
})();
"""


@pytest.fixture
def nav(page, site):
    """Open /page/a with playing audio and a token that a full load would clear."""
    parsed: list[str] = []
    page.expose_function("__recordParsed", lambda text: parsed.append(text))
    page.add_init_script(INIT_SCRIPT)
    page.goto(site.base + "/page/a")
    page.wait_for_function("() => !!window.__castPersistentAudioDebug")
    page.evaluate("""async () => {
            window.__TOKEN = 'same-document';
            window.__audio = document.getElementById('fixture-audio');
            await window.__audio.play();
        }""")
    page.parsed = parsed
    return page


def _marker(page) -> str:
    return page.locator("#marker").inner_text()


def _same_document(page) -> bool:
    return page.evaluate("() => window.__TOKEN === 'same-document'")


def _audio_untouched(page) -> bool:
    return page.evaluate("""() => {
            const audio = document.getElementById('fixture-audio');
            return audio === window.__audio && !audio.paused && audio.src.endsWith('/audio.wav');
        }""")


def _path(page) -> str:
    return page.evaluate("() => location.pathname")


# ---- final-origin guard -------------------------------------------------------


def test_allowed_public_redirect_swaps_once_and_keeps_audio(nav, site):
    nav.locator("#to-public-redirect").click()
    nav.wait_for_function("() => location.pathname === '/page/b'")

    assert _marker(nav) == "B PAGE"
    assert _same_document(nav), "an allowed redirect must stay an enhanced navigation"
    assert _audio_untouched(nav)
    assert len(nav.parsed) == 1
    assert site.seen("/redirect/public", enhanced=True) == 1
    assert site.seen("/page/b", enhanced=False) == 0, "no full load expected"


@pytest.mark.parametrize(
    ("link", "final_path"),
    [("#to-login-redirect", "/accounts/login/"), ("#to-admin-redirect", "/admin/")],
)
def test_redirect_to_excluded_route_is_not_imported(nav, site, link, final_path):
    nav.locator(link).click()
    # The excluded destination is reached by a full document load ...
    nav.wait_for_function("() => window.__TOKEN === undefined && !!window.__castPersistentAudioDebug")

    assert _path(nav) == final_path
    assert site.seen(final_path, enhanced=False) == 1
    # ... and its markup was never parsed or swapped in as public content.
    assert nav.parsed == []


def test_redirect_to_cors_readable_foreign_origin_is_not_imported(nav, site):
    nav.locator("#to-foreign-redirect").click()
    nav.wait_for_url(site.foreign_base + "/landing")

    assert site.seen("foreign:/landing", enhanced=True) == 1, "fixture must be CORS-readable"
    assert site.seen("foreign:/landing", enhanced=False) == 1, "expected one full navigation"
    assert nav.parsed == [], "foreign markup must never be parsed or imported"


# ---- request deadline ----------------------------------------------------------


@pytest.mark.parametrize("link", ["#to-stall", "#to-stall-body"])
def test_stalled_response_falls_back_to_one_full_load(nav, site, link):
    path = nav.locator(link).get_attribute("href")
    nav.locator(link).click()
    # Bounded: the full-load fallback arrives although the fetch never finishes.
    nav.wait_for_function(
        "() => window.__TOKEN === undefined && !!window.__castPersistentAudioDebug",
        timeout=NAV_TIMEOUT_MS + 5000,
    )

    assert _marker(nav) == "STALL FALLBACK PAGE"
    assert _path(nav) == path
    nav.wait_for_timeout(SETTLE_MS)
    assert site.seen(path, enhanced=True) == 1
    assert site.seen(path, enhanced=False) == 1, "exactly one fallback navigation"
    assert nav.parsed == []


@pytest.mark.parametrize("link", ["#to-stall", "#to-stall-body"])
def test_superseded_navigation_is_aborted_without_fallback(nav, site, link):
    path = nav.locator(link).get_attribute("href")
    nav.locator(link).click()
    # Wait until the stalled request really is in flight, then navigate again.
    for _ in range(50):
        if site.seen(path, enhanced=True):
            break
        nav.wait_for_timeout(20)
    nav.locator("#to-b").click()
    nav.wait_for_function("() => location.pathname === '/page/b'")

    # Past the first navigation's deadline: its abort must not navigate away.
    nav.wait_for_timeout(SETTLE_MS)
    assert _marker(nav) == "B PAGE"
    assert _path(nav) == "/page/b"
    assert _same_document(nav), "the superseded navigation must not trigger a full load"
    assert _audio_untouched(nav)
    assert site.seen(path, enhanced=False) == 0
    assert nav.evaluate("() => window.__aborted") == [site.base + path]


# ---- popstate final-URL reconciliation ----------------------------------------


def test_popstate_to_redirecting_entry_replaces_its_url(nav, site):
    nav.locator("#to-old").click()
    nav.wait_for_function("() => location.pathname === '/old'")
    nav.locator("#to-c").click()
    nav.wait_for_function("() => location.pathname === '/page/c'")
    history_length = nav.evaluate("() => history.length")

    # The old route has moved since the history entry was created.
    with site.lock:
        site.redirects["/old"] = "/page/new"
    nav.evaluate("() => history.back()")
    nav.wait_for_function("() => document.getElementById('marker').textContent === 'NEW PAGE'")

    # The displayed page and the address agree, on the SAME history entry.
    nav.wait_for_function("() => location.pathname === '/page/new'")
    assert nav.evaluate("() => history.length") == history_length
    assert nav.evaluate("() => history.state") == {"castNav": True}
    assert nav.evaluate("() => document.getElementById('relative-page-2').href") == site.base + "/page/new?page=2"
    assert _same_document(nav)
    assert _audio_untouched(nav)

    # Forward depth is preserved: no entry was pushed on top of the corrected one.
    nav.evaluate("() => history.forward()")
    nav.wait_for_function("() => location.pathname === '/page/c'")
    nav.wait_for_function("() => document.getElementById('marker').textContent === 'C PAGE'")
    assert nav.evaluate("() => history.length") == history_length
    assert _same_document(nav)


def test_popstate_without_redirect_leaves_history_alone(nav, site):
    nav.locator("#to-b").click()
    nav.wait_for_function("() => location.pathname === '/page/b'")
    history_length = nav.evaluate("() => history.length")
    nav.evaluate("""() => {
            window.__replaced = 0;
            const replace = history.replaceState;
            history.replaceState = function () { window.__replaced += 1; return replace.apply(this, arguments); };
        }""")

    nav.evaluate("() => history.back()")
    nav.wait_for_function("() => document.getElementById('marker').textContent === 'A PAGE'")

    assert _path(nav) == "/page/a"
    assert nav.evaluate("() => window.__replaced") == 0
    assert nav.evaluate("() => history.length") == history_length
    assert _audio_untouched(nav)


def test_popstate_to_entry_now_redirecting_to_excluded_route_uses_full_load(nav, site):
    nav.locator("#to-old").click()
    nav.wait_for_function("() => location.pathname === '/old'")
    nav.locator("#to-c").click()
    nav.wait_for_function("() => location.pathname === '/page/c'")

    with site.lock:
        site.redirects["/old"] = "/accounts/login/"
    parsed_before = len(nav.parsed)
    nav.evaluate("() => history.back()")
    nav.wait_for_function("() => window.__TOKEN === undefined && !!window.__castPersistentAudioDebug")

    assert _path(nav) == "/accounts/login/"
    assert len(nav.parsed) == parsed_before, "the login page must not be imported"
