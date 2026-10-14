"""
Received Webmentions are queued on the ``cast_transcripts`` worker and the
endpoint is rate limited.
"""

from functools import partial

import httpx
import pytest
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.urls import reverse
from django_tasks_db.models import DBTaskResult
from indieweb.models import Webmention
from indieweb.processors import process_queued_webmention

from python_podcast.core import webmention_tasks

SOURCE = "https://remote.example/post-mentioning-us"
TARGET = "https://python-podcast.example/jochen/"
IMMEDIATE_TASKS = {
    "default": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"},
    "cast_transcripts": {"BACKEND": "django_tasks.backends.immediate.ImmediateBackend"},
}


@pytest.fixture(autouse=True)
def fresh_rate_limit_counters():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def site_domain(db, settings):
    settings.TASKS = {
        **settings.TASKS,
        "cast_transcripts": {"BACKEND": "django_tasks_db.DatabaseBackend"},
    }
    Site.objects.update_or_create(pk=settings.SITE_ID, defaults={"domain": "python-podcast.example"})
    Site.objects.clear_cache()
    yield
    Site.objects.clear_cache()


@pytest.fixture
def no_remote_fetch(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the Webmention request must not fetch a remote page")

    monkeypatch.setattr(httpx.Client, "send", refuse)


def post_webmention(client):
    return client.post(reverse("indieweb:webmention"), data={"source": SOURCE, "target": TARGET})


def test_settings_queue_webmentions_and_limit_the_endpoint():
    assert settings.INDIEWEB_WEBMENTION_ENQUEUE == "python_podcast.core.webmention_tasks.enqueue_webmention"
    assert settings.INDIEWEB_RATE_LIMITS == {
        "webmention": {"limit": 60, "window": 300},
        "webmention_status": {"limit": 120, "window": 300},
    }
    assert webmention_tasks.process_webmention.backend == "cast_transcripts"


@pytest.mark.django_db
def test_post_queues_the_webmention_without_fetching_the_source(client, no_remote_fetch):
    response = post_webmention(client)

    assert response.status_code == 202
    webmention = Webmention.objects.get(source_url=SOURCE)
    assert webmention.status == "pending"
    assert response["Location"].endswith(f"/indieweb/webmention/{webmention.status_token}/")
    queued = DBTaskResult.objects.get()
    assert queued.task_path == "python_podcast.core.webmention_tasks.process_webmention"
    assert queued.backend_name == "cast_transcripts"
    assert queued.queue_name == "default"
    assert queued.args_kwargs["args"] == [webmention.pk]


@pytest.mark.django_db
def test_running_the_queued_task_processes_the_webmention(client, monkeypatch):
    def remote_site(request):
        assert str(request.url) == SOURCE
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f'<html><body><a href="{TARGET}">a mention</a></body></html>',
        )

    monkeypatch.setattr(
        webmention_tasks,
        "process_queued_webmention",
        partial(process_queued_webmention, client=httpx.Client(transport=httpx.MockTransport(remote_site))),
    )
    assert post_webmention(client).status_code == 202
    assert Webmention.objects.get(source_url=SOURCE).status == "pending"

    # What the worker does with the stored row: import the task by its path
    # and call it with the stored arguments.
    queued = DBTaskResult.objects.get().task_result
    queued.task.call(*queued.args, **queued.kwargs)

    assert Webmention.objects.get(source_url=SOURCE).status == "verified"


@pytest.mark.django_db
def test_requests_over_the_limit_are_rejected(client, no_remote_fetch, settings):
    settings.INDIEWEB_RATE_LIMITS = {"webmention": {"limit": 2, "window": 300}}

    assert [post_webmention(client).status_code for _ in range(3)] == [202, 202, 429]
    rejected = post_webmention(client)
    assert rejected.status_code == 429
    assert 0 < int(rejected["Retry-After"]) <= 300
    assert DBTaskResult.objects.count() == 2


@pytest.mark.django_db
def test_immediate_backend_processes_the_webmention_in_the_request(client, monkeypatch, settings):
    settings.TASKS = IMMEDIATE_TASKS
    processed = []
    monkeypatch.setattr(webmention_tasks, "process_queued_webmention", processed.append)

    response = post_webmention(client)

    assert response.status_code == 202
    assert processed == [Webmention.objects.get(source_url=SOURCE).pk]
    assert not DBTaskResult.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "auth/",
        "auth/metadata/",
        "token/",
        "token/introspect/",
        "tokens/",
        "tokens/1/revoke/",
        "micropub/",
        "media/",
        "websub/example/",
    ],
)
def test_unused_indieweb_endpoints_stay_unrouted(client, path):
    assert client.get(f"/indieweb/{path}").status_code == 404
    assert client.post(f"/indieweb/{path}").status_code == 404


@pytest.mark.django_db
def test_status_url_exposes_only_verification_state(client, no_remote_fetch):
    response = post_webmention(client)
    status = client.get(response["Location"])
    assert status.status_code == 200
    assert status.json() == {"status": "pending"}
    assert status["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_owner_can_inspect_mentions_in_admin(admin_client, client, no_remote_fetch):
    assert post_webmention(client).status_code == 202
    mention = Webmention.objects.get()
    listing = admin_client.get(reverse("admin:indieweb_webmention_changelist"))
    assert listing.status_code == 200
    assert SOURCE.encode() in listing.content
    detail = admin_client.get(reverse("admin:indieweb_webmention_change", args=[mention.pk]))
    assert detail.status_code == 200
    assert TARGET.encode() in detail.content
    assert client.get(reverse("admin:indieweb_webmention_changelist")).status_code == 302


@pytest.mark.django_db
def test_indieweb_migrations_are_applied(request):
    """CI runs this module with --migrations as well as normal model sync."""
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.recorder import MigrationRecorder

    if request.config.getoption("nomigrations"):
        pytest.skip("run with --migrations to check the dependency's migration history")
    loader = MigrationLoader(connection)
    migrations = {key for key in loader.disk_migrations if key[0] == "indieweb"}
    assert ("indieweb", "0008_webmention") in migrations
    assert migrations <= set(MigrationRecorder(connection).applied_migrations())
    assert Webmention._meta.db_table in connection.introspection.table_names()


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "head"])
def test_status_requests_over_the_limit_are_rejected(client, no_remote_fetch, monkeypatch, method):
    # Keep all requests in the same fixed window, even on a slow CI runner.
    monkeypatch.setattr("indieweb.rate_limit.time.time", lambda: 1_800_000_000)
    submitted = post_webmention(client)
    assert submitted.status_code == 202
    status_url = submitted["Location"]
    request_status = getattr(client, method)

    for _ in range(120):
        assert request_status(status_url).status_code == 200

    rejected = request_status(status_url)
    assert rejected.status_code == 429
    assert int(rejected["Retry-After"]) == 300
    assert DBTaskResult.objects.count() == 1
