from django.apps import AppConfig


class FediConfig(AppConfig):
    name = "python_podcast.fedi"
    verbose_name = "Fediverse redirects etc."

    def ready(self):
        import logging

        from .log_filters import SkipFediUpstreamFailures

        # A logger-level filter runs before any handler, so neither mail_admins
        # nor Sentry's logging integration sees the dropped records. Added here
        # instead of in LOGGING so it applies with every settings module.
        logging.getLogger("django.request").addFilter(SkipFediUpstreamFailures())
