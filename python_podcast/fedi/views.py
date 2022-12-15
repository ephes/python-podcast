from django.http import HttpResponseRedirect
from proxy.views import proxy_view


def wellknown_webfinger(request):
    remote_url = "https://fedi.python-podcast.de/.well-known/webfinger?" + request.META["QUERY_STRING"]
    return proxy_view(request, remote_url)


def wellknown_hostmeta(request):
    remote_url = "https://fedi.python-podcast.de/.well-known/host-meta?" + request.META["QUERY_STRING"]
    return proxy_view(request, remote_url)


def wellknown_nodeinfo(request):
    remote_url = "https://fedi.python-podcast.de/.well-known/nodeinfo"
    return proxy_view(request, remote_url)


def username_redirect_jochen(request):
    return HttpResponseRedirect("https://fedi.python-podcast.de/@jochen")


def username_redirect_show(request):
    return HttpResponseRedirect("https://fedi.python-podcast.de/@show")
