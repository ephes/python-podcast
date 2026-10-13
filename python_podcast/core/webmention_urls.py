"""Only the receiving endpoint and its opaque status URL are public."""

from django.urls import path
from indieweb.views import WebmentionEndpoint, WebmentionStatusView

app_name = "indieweb"
urlpatterns = [
    path("webmention/", WebmentionEndpoint.as_view(), name="webmention"),
    path("webmention/<str:status_token>/", WebmentionStatusView.as_view(), name="webmention-status"),
]
