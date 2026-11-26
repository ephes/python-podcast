from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "HEAD"])
@cache_control(max_age=60 * 60 * 24, public=True)  # one day
def robots_txt(request: HttpRequest) -> HttpResponse:
    content = "\n".join(
        [
            "User-agent: *",
            "Disallow: /admin/",
            "Disallow: /cms/",
            # Every combination of the django-cast blog index filters is its
            # own URL, and crawlers walk them all. Match each filter parameter
            # at a query parameter boundary (first or later parameter), so
            # look-alikes such as utm_tag_facets stay crawlable.
            "Disallow: /*?date_facets=",
            "Disallow: /*?*&date_facets=",
            "Disallow: /*?tag_facets=",
            "Disallow: /*?*&tag_facets=",
            "Disallow: /*?category_facets=",
            "Disallow: /*?*&category_facets=",
        ]
    )
    return HttpResponse(f"{content}\n", content_type="text/plain; charset=utf-8")
