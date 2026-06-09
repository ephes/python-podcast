from __future__ import annotations

from cast.follow_links import get_follow_links
from cast.models import TemplateBaseDirectory
from cast.models.theme import get_template_base_dir
from django.conf import settings


def default_follow_links(request) -> dict[str, dict[str, str]]:
    return {"default_follow_links": get_follow_links(None)}


def persistent_audio_player(request) -> dict:
    """Expose the persistent-audio-player staging flag + a session-aware base.

    ``persistent_audio_player`` drives the `pp` theme persistent-player region,
    the per-episode payload publisher, and the enhanced-navigation wiring.
    Defaults to False so production keeps the shipped page-local custom player.

    ``cast_session_base_template`` is the active (session/query-aware) theme base,
    so flat ``TemplateView`` pages (about/dsgvo/impressum) follow the selected
    theme. django-cast's ``cast_base_template`` resolves to the *site default*
    only, which would otherwise keep these pages on bootstrap5 (no
    ``#paging-area``) and break enhanced navigation to them under the `pp` proof.
    """
    try:
        site_default = TemplateBaseDirectory.for_request(request).name
        template_base_dir = get_template_base_dir(request, site_default)
    except Exception:  # noqa: BLE001 - never break rendering on theme lookup
        template_base_dir = "bootstrap5"
    return {
        "persistent_audio_player": bool(getattr(settings, "PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER", False)),
        "cast_session_base_template": f"cast/{template_base_dir}/base.html",
    }
