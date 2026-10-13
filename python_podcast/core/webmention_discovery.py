"""Advertise receiving Webmentions on public cast content pages only."""

from cast.models import Blog, Post
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin


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
            existing = response.get("Link")
            response["Link"] = f"{existing}, {link}" if existing else link
        return response
