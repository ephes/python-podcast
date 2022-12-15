from django.apps import AppConfig


class FediConfig(AppConfig):
    name = "python_podcast.fedi"
    verbose_name = "Fediverse redirects etc."

    def ready(self):
        """Override this to put in:
        Users system checks
        Users signal registration
        """
        pass
