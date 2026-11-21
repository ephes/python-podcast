"""Advertise receiving Webmentions on public cast content pages only."""

import re
from email.message import Message
from urllib.parse import urljoin

from cast.models import Blog, Post
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

# Commas within the target or quoted parameters belong to that link value.
LINK_VALUE = re.compile(r'(?:^|,)[ \t]*<([^>]*)>((?:[^",]|"(?:[^"\\]|\\.)*")*)')


def _has_webmention_link(header: str, endpoint: str, request_uri: str) -> bool:
    for target, parameters in LINK_VALUE.findall(header):
        link = Message()
        link["Link"] = f"link{parameters}"
        relation = link.get_param("rel", header="Link", failobj="")
        if not isinstance(relation, str) or "webmention" not in relation.lower().split():
            continue
        anchor = link.get_param("anchor", header="Link", failobj="")
        if not isinstance(anchor, str):
            continue
        try:
            if urljoin(request_uri, target) == endpoint and urljoin(request_uri, anchor) == request_uri:
                return True
        except ValueError:
            continue
    return False


class WebmentionDiscoveryMiddleware(MiddlewareMixin):
    def process_template_response(self, request, response):
        context = response.context_data or {}
        page = context.get("page")
        if (
            response.status_code == 200
            and isinstance(page, (Blog, Post))
            and page.live
            and not getattr(request, "is_preview", False)
            and not context.get("is_preview", False)
            and not page.get_view_restrictions().exists()
        ):
            endpoint = request.build_absolute_uri(reverse("indieweb:webmention"))
            link = f'<{endpoint}>; rel="webmention"'
            existing = response.get("Link", "")
            if not _has_webmention_link(existing, endpoint, request.build_absolute_uri()):
                response["Link"] = f"{existing}, {link}" if existing else link
        return response
