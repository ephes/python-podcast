"""
Received Webmentions are queued on the ``cast_transcripts`` worker and the
endpoint is rate limited.
"""

import signal
from collections import Counter
from functools import partial

import httpx
import pytest
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django_tasks.base import TaskResultStatus
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


@pytest.fixture
def run_worker():
    def run(*, backend="cast_transcripts", queue="default"):
        # The public command installs process handlers; leave pytest's intact.
        handlers = {
            sig: signal.getsignal(sig) for sig in signal.Signals if sig.name in {"SIGINT", "SIGTERM", "SIGQUIT"}
        }
        try:
            call_command(
                "db_worker",
                backend_name=backend,
                queue_name=queue,
                batch=True,
                max_tasks=10,
                interval=0,
                startup_delay=False,
                reload=False,
                worker_id="webmention-test",
                verbosity=0,
            )
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)

    return run


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", ["source", "task"])
def test_worker_claims_and_finishes_independent_mentions(client, monkeypatch, settings, run_worker, failure):
    settings.TASKS = {**settings.TASKS, "default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}
    bad_source = "https://remote.example/failing-source"
    calls = Counter()

    def assert_claimed(mention_id):
        queued = DBTaskResult.objects.get(args_kwargs__args=[mention_id])
        assert queued.status == TaskResultStatus.RUNNING
        assert queued.worker_ids == ["webmention-test"]
        assert queued.started_at is not None
        assert queued.finished_at is None

    def remote_site(request):
        source = str(request.url)
        assert source in {SOURCE, bad_source}
        calls[source] += 1
        assert_claimed(Webmention.objects.get(source_url=source).pk)
        if source == bad_source:
            raise httpx.ConnectError("synthetic unavailable source", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f'<html><body><a href="{TARGET}">a mention</a></body></html>',
        )

    with httpx.Client(transport=httpx.MockTransport(remote_site)) as transport:
        process = partial(process_queued_webmention, client=transport)

        def process_with_failure(mention_id):
            mention = Webmention.objects.get(pk=mention_id)
            if failure == "task" and mention.source_url == bad_source:
                assert_claimed(mention_id)
                calls[bad_source] += 1
                raise RuntimeError("synthetic task failure")
            return process(mention_id)

        monkeypatch.setattr(webmention_tasks, "process_queued_webmention", process_with_failure)
        assert (
            client.post(reverse("indieweb:webmention"), data={"source": bad_source, "target": TARGET}).status_code
            == 202
        )
        bad = Webmention.objects.get(source_url=bad_source)
        DBTaskResult.objects.filter(args_kwargs__args=[bad.pk]).update(priority=10)
        assert post_webmention(client).status_code == 202
        assert set(Webmention.objects.values_list("status", flat=True)) == {"pending"}

        for backend, queue in (("cast_transcripts", "other"), ("default", "default")):
            run_worker(backend=backend, queue=queue)
            assert calls == {}
            assert set(DBTaskResult.objects.values_list("status", flat=True)) == {TaskResultStatus.READY}
            assert not DBTaskResult.objects.exclude(worker_ids=[]).exists()

        run_worker()
        good = Webmention.objects.get(source_url=SOURCE)
        bad.refresh_from_db()
        assert good.status == "verified"
        assert bad.status == ("failed" if failure == "source" else "pending")
        for mention, expected in (
            (good, TaskResultStatus.SUCCESSFUL),
            (bad, TaskResultStatus.FAILED if failure == "task" else TaskResultStatus.SUCCESSFUL),
        ):
            queued = DBTaskResult.objects.get(args_kwargs__args=[mention.pk])
            assert queued.status == expected
            assert queued.worker_ids == ["webmention-test"]
            assert queued.enqueued_at <= queued.started_at <= queued.finished_at
            assert queued.exception_class_path == (
                "builtins.RuntimeError" if expected == TaskResultStatus.FAILED else ""
            )
        assert calls == {bad_source: 1, SOURCE: 1}
        run_worker()
        assert calls == {bad_source: 1, SOURCE: 1}, "terminal tasks must not execute again"


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
