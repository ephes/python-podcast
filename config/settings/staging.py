"""Staging settings.

Identical to production except that staging
(``python-podcast.staging.django-cast.com``) previews the new dependency-free
custom audio player, while production keeps the Podlove Web Player. This lets us
run external Lighthouse / real-browser checks against the custom player on a real
site before it replaces Podlove in production.
"""

from .production import *  # noqa: F401,F403

# Preview the custom audio player on staging only (production stays "podlove").
CAST_AUDIO_PLAYER = "custom"

# Staging proof: keep one custom player alive across enhanced (htmx) navigation.
# Production never sets this, so it stays disabled there.
PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True
