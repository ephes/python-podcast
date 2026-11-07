"""Synthetic regressions for the Tornado 6.6 security update."""

import pytest
from tornado.httputil import HTTPHeaders, HTTPInputError
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application, RedirectHandler


@pytest.mark.parametrize("continuation", [" folded", "\tfolded"])
def test_obsolete_header_folding_is_rejected(continuation):
    # GHSA-pcg2-g6cj-q92c: folded headers formerly caused quadratic parsing.
    with pytest.raises(HTTPInputError):
        HTTPHeaders.parse(f"X-Test: value\r\n{continuation}\r\n")


class TestRedirectHostBoundary(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r"/(.*)/target", RedirectHandler, {"url": "/{0}/destination"})])

    def test_capture_cannot_change_redirect_host(self):
        # GHSA-pw9p-v7r6-gx4p: a leading slash made the target protocol-relative.
        response = self.fetch("//attacker.invalid/target", follow_redirects=False)
        assert response.code == 400
        assert "Location" not in response.headers
