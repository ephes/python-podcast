from __future__ import annotations

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString

from python_podcast.pp.show_notes.icons import glyph_for_kind

register = template.Library()


@register.simple_tag
def pp_show_note_icon(kind: str) -> SafeString:
    return format_html(
        '<span class="show-note-icon show-note-icon--{}" aria-hidden="true">{}</span>',
        kind,
        glyph_for_kind(kind),
    )
