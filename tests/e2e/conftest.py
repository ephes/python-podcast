import os
from socketserver import ThreadingMixIn
from threading import Thread
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIServer, make_server

import pytest

# Playwright's sync API runs an event loop on the test thread; allow the Django
# ORM to be used from the fixtures/test in that context (the live-server data is
# created synchronously). Set before Django touches the ORM.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Allow audio playback to start without a separate gesture-policy hurdle in
    # headless Chromium (the test still clicks Play).
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get("args", []),
            "--autoplay-policy=no-user-gesture-required",
            # Use a null audio sink: the media playback clock then advances even
            # when the host's real audio output device is unavailable/wedged
            # (otherwise currentTime can stall at ~0 with paused === false).
            "--disable-audio-output",
        ],
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}


@pytest.fixture
def local_media_network(page):
    """Media fixtures use local assets only; suppress external analytics."""

    def route_local(route):
        if urlsplit(route.request.url).hostname in {"localhost", "127.0.0.1", "::1"}:
            route.continue_()
        else:
            route.fulfill(status=204)

    page.route("**/*", route_local)


@pytest.fixture
def local_media_storage(settings, tmp_path):
    from whitenoise import WhiteNoise

    def missing(environ, start_response):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Missing synthetic media"]

    # Django's live-server file handler doesn't support byte ranges. Use the
    # existing WhiteNoise dependency so Chromium can seek real local M4A/MP3.
    media = WhiteNoise(missing, root=tmp_path, prefix="media/", autorefresh=True)

    class ThreadedMediaServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server("127.0.0.1", 0, media, server_class=ThreadedMediaServer) as server:
        settings.MEDIA_ROOT = str(tmp_path)
        settings.MEDIA_URL = f"http://127.0.0.1:{server.server_port}/media/"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive(), "synthetic media server did not stop"
