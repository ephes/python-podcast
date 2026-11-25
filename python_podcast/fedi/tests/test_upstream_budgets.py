import errno
import logging
import socket
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


@pytest.mark.parametrize("deadline_expires", [False, True], ids=["fallback", "deadline-expired"])
def test_socket_construction_failure_uses_remaining_address_budget(rf, monkeypatch, deadline_expires):
    now = 0
    ipv6 = ("2001:db8::1", 443, 0, 0)
    ipv4 = ("192.0.2.1", 443)
    addresses = [
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ipv6),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ipv4),
    ]
    connected_socket = Mock()
    attempted_families = []

    def open_socket(family, _socktype, _proto):
        nonlocal now
        attempted_families.append(family)
        if family == socket.AF_INET6:
            now = views.UPSTREAM_DEADLINE if deadline_expires else views.UPSTREAM_DEADLINE - 1
            raise OSError(errno.EAFNOSUPPORT, "synthetic unsupported address family")
        return connected_socket

    tls_context = Mock()
    tls_context.wrap_socket.return_value = connected_socket
    upstream = Mock(length=None, status=200, headers={})
    upstream.read1.side_effect = [b"document", b""]
    connection = Mock()
    connection.getresponse.return_value = upstream
    monkeypatch.setattr(views, "_resolve", Mock(return_value=addresses))
    monkeypatch.setattr(views.socket, "socket", open_socket)
    monkeypatch.setattr(views.http.client, "HTTPConnection", Mock(return_value=connection))
    monkeypatch.setattr(views, "_get_ssl_context", lambda: tls_context)
    monkeypatch.setattr(views, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(views.threading, "Timer", Mock())

    response = views.wellknown_nodeinfo(rf.get("/.well-known/nodeinfo"))

    if deadline_expires:
        assert response.status_code == 504
        assert attempted_families == [socket.AF_INET6]
        connection.request.assert_not_called()
    else:
        assert response.status_code == 200
        assert response.content == b"document"
        assert attempted_families == [socket.AF_INET6, socket.AF_INET]
        connected_socket.connect.assert_called_once_with(ipv4)
        assert connected_socket.settimeout.call_args_list[0].args == (1,)


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


@pytest.mark.parametrize(
    "method, error, status, body",
    [
        ("head", socket.timeout("synthetic upstream timeout"), 504, b""),
        ("get", socket.timeout("synthetic upstream timeout"), 504, b"Upstream timeout"),
        ("get", OSError("synthetic transport failure"), 502, b"Bad gateway"),
        ("get", None, 502, b"Bad gateway"),
    ],
    ids=["head-timeout", "get-timeout", "transport", "invalid-response"],
)
def test_gateway_reply_survives_warning_handler_failure(client, monkeypatch, settings, method, error, status, body):
    # The endpoint has no database queries, so a request transaction is unnecessary.
    monkeypatch.setitem(settings.DATABASES["default"], "ATOMIC_REQUESTS", False)
    if error is None:
        monkeypatch.setattr(views, "_fetch", Mock(return_value=(99, {}, b"document")))
    else:
        connection = Mock()
        connection.request.side_effect = error
        monkeypatch.setattr(views.http.client, "HTTPConnection", Mock(return_value=connection))
        monkeypatch.setattr(views, "_connect", Mock())

    records = []

    class BrokenWarningHandler(logging.Handler):
        def emit(self, record):
            records.append(record)
            raise RuntimeError("synthetic warning sink failure")

    handler = BrokenWarningHandler()
    views.logger.addHandler(handler)
    try:
        client.raise_request_exception = False
        response = getattr(client, method)("/.well-known/nodeinfo")
    finally:
        views.logger.removeHandler(handler)

    assert len(records) == 1
    assert response.status_code == status
    assert response.content == body
    assert response.wsgi_request.fedi_upstream_failure is True
