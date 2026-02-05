from cast.views import defaults as default_views_cast
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView
from rest_framework.authtoken import views as authtokenviews
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.documents import urls as wagtaildocs_urls

from python_podcast.core import views as core_views
from python_podcast.pp import views as pp_views

handler404 = default_views_cast.page_not_found
handler500 = default_views_cast.server_error
handler400 = default_views_cast.bad_request
handler403 = default_views_cast.permission_denied


# openapi endpoint broken for wagtail until this is fixed:
# https://github.com/wagtail/wagtail/issues/8583
PagesAPIViewSet.schema = None


urlpatterns = [
    path("robots.txt", core_views.robots_txt, name="robots_txt"),
    # path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("", RedirectView.as_view(url="/show/"), name="home"),
    path(
        "about/",
        TemplateView.as_view(template_name="pages/about.html"),
        name="about",
    ),
    path(
        "datenschutzerklaerung/",
        TemplateView.as_view(template_name="pages/dsgvo.html"),
        name="dsgvo",
    ),
    path(
        "impressum/",
        TemplateView.as_view(template_name="pages/impressum.html"),
        name="impressum",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path(
        "users/",
        include("python_podcast.users.urls", namespace="users"),
    ),
    path("accounts/", include("allauth.urls")),
    # Your stuff: custom urls includes go here
    # Threadedcomments
    path("show/comments/", include("cast.comments.urls")),
    # rest
    path("api/api-token-auth/", authtokenviews.obtain_auth_token),
    # path("docs/", include_docs_urls(title="API service", public=False)),
    # Cast
    path("", include("cast.urls", namespace="cast")),
    # Podlove Player Config for Python Podcast Theme
    path("podlove-player-config/", pp_views.podlove_player_config, name="podlove-player-config"),
    path("podlove-player-template/", pp_views.podlove_player_template, name="podlove-player-template"),
    # Fediverse redirects etc.
    path("", include("python_podcast.fedi.urls", namespace="fedi")),
    # Wagtail
    path(settings.WAGTAILADMIN_BASE_URL, include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),  # default is wagtail
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views_cast.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views_cast.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views_cast.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views_cast.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns
