"""Shared helpers for the browser-level e2e tests."""

from __future__ import annotations


def ensure_site():
    """Return a default Wagtail Site, recreating the tree if a transactional
    flush (live_server) wiped the migration-created site/locale."""
    from django.conf import settings
    from wagtail.models import Locale, Page, Site

    # The transactional flush between tests also removes the migration-created
    # default Locale, which Page creation requires; restore it first.
    Locale.objects.get_or_create(language_code=getattr(settings, "LANGUAGE_CODE", "en").split("-")[0])

    site = Site.objects.first()
    if site is not None and site.root_page_id is not None:
        return site
    root = Page.get_first_root_node()
    if root is None:
        root = Page.add_root(title="Root", slug="root")
    home = root.add_child(instance=Page(title="Home", slug="home"))
    return Site.objects.create(hostname="localhost", port=80, root_page=home, is_default_site=True)
