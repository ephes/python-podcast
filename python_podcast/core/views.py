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
        ]
    )
    return HttpResponse(f"{content}\n", content_type="text/plain; charset=utf-8")
