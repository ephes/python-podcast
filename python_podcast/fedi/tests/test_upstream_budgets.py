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
