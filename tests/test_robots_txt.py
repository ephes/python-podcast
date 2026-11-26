import re

import pytest
from django.test import RequestFactory

from python_podcast.core.views import robots_txt


def disallows(path: str) -> bool:
    """Match like RFC 9309 crawlers do (``*`` is a wildcard, rules are prefixes).

    ``urllib.robotparser`` treats ``*`` literally before Python 3.14, so the
    rules are matched here. robots.txt has one group and only Disallow rules.
    """
    response = robots_txt(RequestFactory().get("/robots.txt"))
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    group, *rules = response.content.decode().splitlines()
    assert group == "User-agent: *"
    assert all(rule.startswith("Disallow: /") and "$" not in rule for rule in rules)
    patterns = [rule.removeprefix("Disallow: ") for rule in rules]
    return any(re.match(".*".join(map(re.escape, pattern.split("*"))), path) for pattern in patterns)


@pytest.mark.parametrize(
    "path",
    [
        "/show/?tag_facets=python",
        "/show/?date_facets=&tag_facets=typescript",
        "/show/?page=2&category_facets=interview",
        "/show/?date_facets=2024-05",
        "/admin/",
        "/cms/pages/",
    ],
)
def test_robots_txt_disallows_index_filters_and_admin(path):
    assert disallows(path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/show/",
        "/show/?page=2",
        "/show/?page=2&utm_tag_facets=python",
        "/show/?xdate_facets=2024-05",
        "/show/python-315/",
        "/show/feed/podcast/m4a/rss.xml",
    ],
)
def test_robots_txt_keeps_indexes_pagination_episodes_and_feeds_crawlable(path):
    assert not disallows(path)
