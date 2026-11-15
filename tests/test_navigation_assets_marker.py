"""Pages whose required assets differ must advertise different navigation markers."""

import re

import pytest
from cast.models import Blog, Post
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Collection, Locale, Page, Site

from python_podcast.users.tests.factories import UserFactory

MARKER = re.compile(rb'<meta name="cast-navigation-assets" content="([^"]+)">')


@pytest.mark.django_db
@pytest.mark.parametrize("comments_enabled", [True, False])
def test_pp_pages_share_marker_and_comment_stylesheet(client, settings, monkeypatch, comments_enabled):
    from django_vite.core.asset_loader import DjangoViteAssetLoader

    monkeypatch.setattr(DjangoViteAssetLoader, "generate_vite_asset", lambda *a, **kw: "")
    monkeypatch.setattr(DjangoViteAssetLoader, "generate_vite_ws_client", lambda *a, **kw: "")
    settings.CAST_COMMENTS_ENABLED = True
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    if not Collection.objects.exists():
        Collection.add_root(name="Root")
    root = Page.get_first_root_node() or Page.add_root(title="Root")
    owner = UserFactory()
    blog = root.add_child(
        instance=Blog(
            title="Synthetic marker show",
            slug="marker-show",
            owner=owner,
            template_base_dir="pp",
            comments_enabled=True,
        )
    )
    post = blog.add_child(
        instance=Post(title="Synthetic marker post", slug="post", comments_enabled=comments_enabled, owner=owner)
    )
    Site.objects.all().delete()
    Site.objects.create(hostname="testserver", port=80, root_page=root, is_default_site=True)

    list_page = client.get(blog.url)
    detail = client.get(post.url)
    assert list_page.status_code == detail.status_code == 200
    (list_marker,) = MARKER.findall(list_page.content)
    (post_marker,) = MARKER.findall(detail.content)
    # Every pp page loads the comments stylesheet, so comment-enabled posts keep
    # the shared marker: enhanced navigation (and the persistent player) survives
    # navigating to and from them, and swapped-in comments are still styled.
    for response in (list_page, detail):
        assert b"fluent_comments/css/ajaxcomments.css" in response.content
    assert post_marker == list_marker == b"pp-v2"
