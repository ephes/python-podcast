from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from python_podcast.fedi import views


def test_declared_oversize_body_is_rejected_before_reading():
    upstream = Mock(length=views.MAX_UPSTREAM_BYTES + 1)
    upstream.read1.return_value = b"x" * upstream.length

    with pytest.raises(views.UpstreamError, match="^response-too-large$"):
        views._read_limited(upstream)

    upstream.read1.assert_not_called()


def test_unknown_length_body_is_limited_incrementally(monkeypatch):
    monkeypatch.setattr(views, "MAX_UPSTREAM_BYTES", 4)
    upstream = Mock(length=None)
    upstream.read1.side_effect = [b"ab", b"cd", b"e", b""]

    with pytest.raises(views.UpstreamError, match="^response-too-large$"):
        views._read_limited(upstream)

    assert upstream.read1.call_count == 3


@pytest.mark.parametrize(
    "error",
    [None, views.UpstreamError("response-truncated"), OSError("synthetic read failure")],
    ids=["completed-body", "upstream-error", "transport-error"],
)
def test_elapsed_deadline_returns_504_even_when_timer_has_not_fired(rf, monkeypatch, error):
    now = 0
    chunks = iter([b"document", b""])

    def read1(_size):
        nonlocal now
        now = views.UPSTREAM_DEADLINE + 1
        if error is not None:
            raise error
        return next(chunks)

    upstream = SimpleNamespace(length=None, read1=read1, status=200, headers={})
    connection = Mock()
    connection.getresponse.return_value = upstream
    timer = Mock()  # start() leaves the deadline callback pending
    monkeypatch.setattr(views.http.client, "HTTPConnection", Mock(return_value=connection))
    monkeypatch.setattr(views, "_connect", Mock())
    monkeypatch.setattr(views, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(views.threading, "Timer", Mock(return_value=timer))

    response = views.wellknown_nodeinfo(rf.get("/.well-known/nodeinfo"))

    assert response.status_code == 504
    assert response.content == b"Upstream timeout"
    timer.start.assert_called_once_with()
    timer.cancel.assert_called_once_with()
