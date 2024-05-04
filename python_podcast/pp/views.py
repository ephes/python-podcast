from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

# from django.templatetags.static import static


def podlove_player_config(request: HttpRequest) -> JsonResponse:
    """Return the Podlove Player Config for the Python Podcast Theme."""
    # hubot_sans = static("fonts/pp/Hubot-Sans.woff2")
    # mona_sans = static("fonts/pp/Mona-Sans.woff2")
    config = {
        "activeTab": None,
        "subscribe-button": None,
        "share": {
            "channels": ["facebook", "twitter", "whats-app", "linkedin", "pinterest", "xing", "mail", "link"],
            # "outlet": "https://ukw.fm/wp-content/plugins/podlove-web-player/web-player/share.html",
            "sharePlaytime": True,
        },
        "related-episodes": {"source": "disabled", "value": None},
        "version": 5,
        "theme": {
            "tokens": {
                "brand": "#E64415",
                "brandDark": "#235973",
                "brandDarkest": "#1A3A4A",
                "brandLightest": "#fff",
                "shadeDark": "#807E7C",
                "shadeBase": "#807E7C",
                "contrast": "#000",
                "alt": "#fff",
            },
            "fonts": {
                "ci": {
                    "name": "ci",
                    "family": [
                        "Hubot-Sans",
                        "sans-serif",
                    ],
                    # "src": [f"{hubot_sans}"],
                    "src": [],
                    # "weight": 800,
                },
                "regular": {
                    "name": "regular",
                    "family": [
                        "Mona-Sans",
                        "sans-serif",
                    ],
                    # "src": [f"{mona_sans}"],
                    "src": [],
                    # "weight": 300,
                },
                "bold": {
                    "name": "bold",
                    "family": [
                        "Mona-Sans",
                        "sans-serif",
                    ],
                    # "src": [f"{mona_sans}"],
                    "src": [],
                    # "weight": 700,
                },
            },
        },
    }
    return JsonResponse(config)


def podlove_player_template(request: HttpRequest) -> HttpResponse:
    """Return the Podlove Player Template for the Python Podcast Theme."""
    return render(request, "cast/pp/player_template.html", {})
