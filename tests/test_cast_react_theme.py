"""The React theme (cast-react) is installed and offered in django-cast's theme chooser."""

from pathlib import Path

import cast_react
from cast.models.theme import get_template_base_dir_choices
from django.conf import settings
from django.template.loader import get_template


def test_react_theme_is_offered():
    assert "cast_react.apps.CastReactConfig" in settings.INSTALLED_APPS
    assert ("react", "React") in get_template_base_dir_choices()


def test_react_theme_templates_and_bundle_are_available():
    get_template("cast/react/base.html")
    get_template("cast/react/post_body.html")
    manifest = Path(cast_react.__file__).parent / "static" / "cast_react" / "manifest.json"
    assert manifest.is_file()
