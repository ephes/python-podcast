"""Discovery is independent of the selected cast theme; content stays private."""

from unittest.mock import Mock

import pytest
from cast.models import Blog, Episode, Post
from django.contrib.auth.models import Group
from django.template.response import TemplateResponse
from django.test import RequestFactory
from indieweb.models import Webmention
from wagtail.coreutils import get_supported_content_language_variant
from wagtail.models import Collection, Locale, Page, PageViewRestriction, Site

from python_podcast.core.webmention_discovery import WebmentionDiscoveryMiddleware
from python_podcast.users.tests.factories import UserFactory


@pytest.mark.parametrize("page_type", [Blog, Post, Episode])
@pytest.mark.parametrize("excluded", [None, "draft", "restricted", "preview", "error"])
def test_discovery_only_for_live_public_cast_pages(page_type, excluded):
    page = page_type(title="Synthetic private post 746", live=excluded != "draft", content_type_id=1, locale_id=1)
    page.get_view_restrictions = Mock()
    page.get_view_restrictions.return_value.exists.return_value = excluded == "restricted"
    request = RequestFactory().get("/show/content/")
    request.is_preview = excluded == "preview"
    response = TemplateResponse(request, "unused.html", {"page": page}, status=404 if excluded == "error" else 200)
    response["Link"] = '<https://example.org/feed/>; rel="alternate"'
    middleware = WebmentionDiscoveryMiddleware(lambda r: response)
    middleware.process_template_response(request, response)
    assert ('rel="webmention"' in response["Link"]) == (excluded is None)
    assert 'rel="alternate"' in response["Link"]


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"page": Page(title="Other", content_type_id=1, locale_id=1)},
        {"is_preview": True, "page": Post(live=True, content_type_id=1, locale_id=1)},
    ],
)
def test_discovery_omitted_from_non_content_and_preview_responses(context):
    request = RequestFactory().get("/accounts/login/")
    response = TemplateResponse(request, "unused.html", context)
    WebmentionDiscoveryMiddleware(lambda r: response).process_template_response(request, response)
    assert "Link" not in response


@pytest.mark.django_db
@pytest.mark.parametrize("restriction_type", ["login", "groups"])
def test_public_cast_response_advertises_endpoint_without_rendering_mentions(
    client, settings, monkeypatch, restriction_type
):
    from django_vite.core.asset_loader import DjangoViteAssetLoader

    # Asset compilation is covered separately; render the real content templates.
    monkeypatch.setattr(DjangoViteAssetLoader, "generate_vite_asset", lambda *a, **kw: "")
    monkeypatch.setattr(DjangoViteAssetLoader, "generate_vite_ws_client", lambda *a, **kw: "")
    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    if not Collection.objects.exists():
        Collection.add_root(name="Root")
    root = Page.get_first_root_node() or Page.add_root(title="Root")
    owner = UserFactory()
    blog = root.add_child(instance=Blog(title="Synthetic Webmention show 746", slug="webmention-show", owner=owner))
    post = blog.add_child(
        instance=Post(title="Synthetic private post 746", slug="content", comments_enabled=False, owner=owner)
    )
    Site.objects.all().delete()
    Site.objects.create(hostname="testserver", port=80, root_page=root, is_default_site=True)
    settings.CAST_AUDIO_PLAYER = "podlove"
    marker = "UNREVIEWED-WEBMENTION-CONTENT"
    for status in ("pending", "verified", "spam", "failed"):
        Webmention.objects.create(
            source_url=f"https://remote.example/{status}",
            target_url=f"http://testserver{post.url}",
            status=status,
            content=marker,
            author_name=marker,
        )
    for url in (blog.url, post.url):
        response = client.get(url)
        assert response.status_code == 200
        assert '<http://testserver/indieweb/webmention/>; rel="webmention"' in response["Link"]
        assert marker.encode() not in response.content
    restriction = PageViewRestriction.objects.create(page=blog, restriction_type=restriction_type)
    reader = UserFactory()
    if restriction_type == "groups":
        group = Group.objects.create(name="Private show readers")
        restriction.groups.add(group)
        reader.groups.add(group)
    assert not post.view_restrictions.exists(), "the restriction belongs to the ancestor"
    anonymous = client.get(post.url)
    assert anonymous.status_code != 200
    assert "Link" not in anonymous
    login = client.get("/accounts/login/")
    assert login.status_code == 200
    assert "Link" not in login
    client.force_login(reader)
    for url in (blog.url, post.url):
        response = client.get(url)
        assert response.status_code == 200
        assert (
            b"Synthetic private post 746" if url == post.url else b"Synthetic Webmention show 746"
        ) in response.content
        assert 'rel="webmention"' not in response.get("Link", "")
        assert marker.encode() not in response.content
