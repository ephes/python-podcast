from django.apps import AppConfig


class PythonPodcastConfig(AppConfig):
    name = "python_podcast.pp"
    verbose_name = "Python Podcast Theme"

    def ready(self):
        """Override this to put in:
        Users system checks
        Users signal registration
        """
        pass
