from __future__ import annotations

import re
from typing import NamedTuple


class IconDef(NamedTuple):
    kind: str
    label: str
    glyph: str | None


ICON_REGISTRY: list[IconDef] = [
    IconDef("auto", "Auto icon (from heading)", None),
    IconDef("links", "Links", "🔗"),
    IconDef("projects", "Projects", "🧰"),
    IconDef("books", "Books", "📚"),
    IconDef("youtube", "YouTube", "▶"),
    IconDef("groups", "Groups", "👥"),
    IconDef("support", "Support the show", "💜"),
    IconDef("sponsors", "Sponsors", "🏷"),
    IconDef("sponsor", "Sponsor", "🏷"),
    IconDef("sale", "Sale / offer", "%"),
    IconDef("default", "Default / other", "📌"),
]

_GLYPH_BY_KIND = {definition.kind: definition.glyph for definition in ICON_REGISTRY if definition.glyph}
_RESOLVE_LABEL_TO_KIND = {
    "books": "books",
    "groups": "groups",
    "links": "links",
    "projects": "projects",
    "sponsor": "sponsor",
    "sponsors": "sponsors",
    "support the show": "support",
    "youtube": "youtube",
}
_SALE_KEYWORDS = ("sale", "rabatt", "offer", "angebot")


def kind_choices() -> list[tuple[str, str]]:
    return [(definition.kind, definition.label) for definition in ICON_REGISTRY]


def glyph_for_kind(kind: str) -> str:
    return _GLYPH_BY_KIND.get(kind, _GLYPH_BY_KIND["default"])


def resolve_icon_kind(heading: str) -> str:
    label = _section_label_key(heading)
    if label in _RESOLVE_LABEL_TO_KIND:
        return _RESOLVE_LABEL_TO_KIND[label]

    folded = (heading or "").casefold()
    if "%" in folded or any(re.search(rf"\b{re.escape(keyword)}\b", folded) for keyword in _SALE_KEYWORDS):
        return "sale"
    return "default"


def materialize_icon(value: dict[str, object]) -> str:
    kind = str(value.get("kind") or "auto")
    if kind != "auto":
        return kind
    return resolve_icon_kind(str(value.get("heading") or ""))


def display_icon(value: dict[str, object]) -> str:
    return str(value.get("icon") or materialize_icon(value))


def _section_label_key(value: str) -> str:
    text = re.sub(r"^[^\w]+", "", value or "", flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.rstrip(":")
