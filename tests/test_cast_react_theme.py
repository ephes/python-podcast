"""The React theme (cast-react) is installed and offered in django-cast's theme chooser."""

from pathlib import Path

import cast_react
import pytest
from cast.models.theme import get_template_base_dir_choices
from django.conf import settings
from django.template.loader import get_template
from django.urls import reverse


def test_react_theme_is_offered():
    assert "cast_react.apps.CastReactConfig" in settings.INSTALLED_APPS
    assert ("react", "React") in get_template_base_dir_choices()


def test_react_theme_templates_and_bundle_are_available():
    get_template("cast/react/base.html")
    get_template("cast/react/post_body.html")
    manifest = Path(cast_react.__file__).parent / "static" / "cast_react" / "manifest.json"
    assert manifest.is_file()


@pytest.fixture
def react_blog(db):
    from cast import devdata
    from wagtail.coreutils import get_supported_content_language_variant
    from wagtail.models import Locale, Page, Site

    Locale.objects.get_or_create(language_code=get_supported_content_language_variant(settings.LANGUAGE_CODE))
    root = Page.get_first_root_node() or Page.add_root(instance=Page(title="Root", slug="root"))
    Site.objects.all().delete()
    site = Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
    blog = devdata.create_blog(owner=devdata.create_user(name="react-theme"), site=site)
    blog.template_base_dir = "react"
    blog.save()
    return blog


def test_blog_and_post_render_with_the_react_theme(client, react_blog):
    from cast import devdata

    post = devdata.create_post(blog=react_blog)
    index = client.get(react_blog.url)
    assert index.status_code == 200
    assert 'id="cast-react-configuration"' in index.content.decode()
    assert "cast_react/main-" in index.content.decode()
    detail = client.get(post.url)
    assert detail.status_code == 200
    assert 'data-route-name="PostDetail"' in detail.content.decode()


@pytest.mark.parametrize("path", ["/about/", "/impressum/", "/datenschutzerklaerung/", None])
def test_pages_without_a_blog_render_with_react_selected(client, react_blog, path):
    chooser = reverse("cast:select-theme")
    path = path or chooser
    assert client.post(chooser, {"template_base_dir": "react", "next": "/"}).status_code == 302
    response = client.get(path)
    assert response.status_code == 200
    content = response.content.decode()
    assert "cr-page-content" in content  # cast-react's server-rendered page layout
    assert "cast-react-configuration" not in content  # without the React app
