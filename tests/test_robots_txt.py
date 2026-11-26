from urllib.robotparser import RobotFileParser

import pytest
from django.test import RequestFactory

from python_podcast.core.views import robots_txt


@pytest.fixture
def robots():
    response = robots_txt(RequestFactory().get("/robots.txt"))
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    parser = RobotFileParser()
    parser.parse(response.content.decode().splitlines())
    return parser


@pytest.mark.parametrize(
    "path",
    [
        "/show/?tag_facets=python",
        "/show/?date_facets=&tag_facets=typescript",
        "/show/?page=2&category_facets=interview",
        "/admin/",
        "/cms/pages/",
    ],
)
def test_robots_txt_disallows_index_filters_and_admin(robots, path):
    assert not robots.can_fetch("PetalBot", f"https://python-podcast.de{path}")


@pytest.mark.parametrize(
    "path", ["/", "/show/", "/show/?page=2", "/show/python-315/", "/show/feed/podcast/m4a/rss.xml"]
)
def test_robots_txt_keeps_indexes_pagination_episodes_and_feeds_crawlable(robots, path):
    assert robots.can_fetch("PetalBot", f"https://python-podcast.de{path}")
