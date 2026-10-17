import logging

UPSTREAM_FAILURE_STATUSES = (502, 504)


class SkipFediUpstreamFailures(logging.Filter):
    """
    Drop ``django.request`` records for the 502/504 the .well-known proxy
    returns when the fedi host is slow or unreachable.

    Such failures are expected during federation bursts and recover on their
    own; the proxy already logs a warning for each. Only records that carry no
    exception, have one of those statuses and belong to a request the proxy
    marked are dropped, so a 500 raised in a view or a middleware still
    reaches the admins.
    """

    def filter(self, record):
        request = getattr(record, "request", None)
        return not (
            getattr(request, "fedi_upstream_failure", False)
            and getattr(record, "status_code", None) in UPSTREAM_FAILURE_STATUSES
            and not record.exc_info
        )
