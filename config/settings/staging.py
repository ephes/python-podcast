"""Staging settings.

Identical to production except that staging
(``python-podcast.staging.django-cast.com``) also previews anonymous comment
self-editing/deletion.
"""

from .production import *  # noqa: F401,F403

# Production also uses the custom player; keep this explicit for readability.
CAST_AUDIO_PLAYER = "custom"

# Keep this explicit so staging mirrors production player behavior.
PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True

# Preview anonymous comment self-editing/deletion on staging before production.
# Commenters can edit or delete their own comment for the lifetime of the browser
# session that created it. Requires a server-side session backend (Django's
# default ``db`` backend is in use), which the cast.E006/E008 checks enforce.
CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
