from django.urls import path

from . import views

app_name = "fedi"
urlpatterns = [
    # Fediverse
    path(".well-known/webfinger", views.wellknown_webfinger),
    path(".well-known/host-meta", views.wellknown_hostmeta),
    path(".well-known/nodeinfo", views.wellknown_nodeinfo),
    path("@jochen", views.username_redirect_jochen),
    path("@show", views.username_redirect_show),
]
