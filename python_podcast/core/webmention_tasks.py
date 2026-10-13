"""
Queued processing of received Webmentions.

django-indieweb stores a received Webmention and hands its id to
``INDIEWEB_WEBMENTION_ENQUEUE``. Fetching and parsing the source page then runs
in the ``cast_transcripts`` worker instead of in the web request.
"""

from django_tasks import task
from indieweb.processors import process_queued_webmention


@task(backend="cast_transcripts")
def process_webmention(webmention_id: int) -> None:
    process_queued_webmention(webmention_id)


def enqueue_webmention(webmention_id: int) -> None:
    process_webmention.enqueue(webmention_id)
