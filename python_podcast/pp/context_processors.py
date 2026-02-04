from __future__ import annotations

from cast.follow_links import get_follow_links


def default_follow_links(request) -> dict[str, dict[str, str]]:
    return {"default_follow_links": get_follow_links(None)}
