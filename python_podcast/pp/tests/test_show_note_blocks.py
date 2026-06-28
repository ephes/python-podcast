from __future__ import annotations

from cast.post_body_blocks import configured_content_blocks
from django import forms

from python_podcast.pp.show_notes.blocks import (
    ShowNoteHeadingBlock,
    ShowNoteLinkListBlock,
    ShowNoteSponsorBlock,
    heading_block,
    link_list_block,
    sponsor_block,
)
from python_podcast.pp.show_notes.icons import glyph_for_kind, resolve_icon_kind


def _display(block, value):
    return block.get_context(block.to_python(value))["display_kind"]


def test_factories_return_stable_block_names():
    assert sponsor_block()[0] == "show_note_sponsor"
    assert link_list_block()[0] == "show_note_link_list"
    assert heading_block()[0] == "show_note_heading"


def test_configured_blocks_are_detail_only():
    assert [name for name, _block in configured_content_blocks("detail")] == [
        "show_note_sponsor",
        "show_note_link_list",
        "show_note_heading",
    ]
    assert configured_content_blocks("overview") == []


def test_auto_icon_resolves_from_heading_when_icon_absent():
    block = ShowNoteLinkListBlock()
    value = {"heading": "Books", "kind": "auto", "intro": "", "items": [], "icon": ""}
    assert _display(block, value) == "books"


def test_explicit_kind_wins_when_icon_absent():
    block = ShowNoteHeadingBlock()
    value = {"heading": "Links", "kind": "projects", "icon": ""}
    assert _display(block, value) == "projects"


def test_icon_field_is_hidden_in_admin_form():
    block = ShowNoteHeadingBlock()
    assert isinstance(block.child_blocks["icon"].field.widget, forms.HiddenInput)


def test_clean_materializes_icon():
    block = ShowNoteSponsorBlock()
    value = block.clean(
        block.to_python(
            {
                "heading": "Sponsor",
                "kind": "auto",
                "icon": "",
                "sponsor_name": "ACME",
                "sponsor_url": "https://example.com",
                "copy": "",
                "coupon_code": "",
            }
        )
    )
    assert value["icon"] == "sponsor"


def test_rendered_icon_is_hidden_for_feed():
    block = ShowNoteHeadingBlock()
    value = block.to_python({"heading": "Links", "kind": "auto", "icon": "links"})

    html = block.render(value, context={"render_for_feed": False})
    feed_html = block.render(value, context={"render_for_feed": True})

    assert "show-note-icon--links" in html
    assert "show-note-icon" not in feed_html
    assert "Links" in feed_html


def test_link_list_renders_inline_note_and_extra_links():
    block = ShowNoteLinkListBlock()
    value = block.to_python(
        {
            "heading": "Picks",
            "show_heading": True,
            "show_items": True,
            "kind": "links",
            "icon": "links",
            "intro": "<p>Intro text.</p>",
            "items": [
                {
                    "prefix": "Tooling: ",
                    "title": "uv",
                    "url": "https://docs.astral.sh/uv/",
                    "extra_links": [{"title": "just", "url": "https://github.com/casey/just"}],
                    "note": "Starts at the justfile part.",
                    "description": "<p>Longer detail.</p>",
                }
            ],
        }
    )

    html = block.render(value, context={"render_for_feed": False})

    assert "show-note-icon--links" in html
    assert "Tooling: " in html
    assert '<a href="https://docs.astral.sh/uv/">uv</a>' in html
    assert ' / <a href="https://github.com/casey/just">just</a>' in html
    assert '<span class="show-note-item-note">Starts at the justfile part.</span>' in html
    assert "Longer detail." in html


def test_link_list_can_hide_heading_and_items():
    block = ShowNoteLinkListBlock()
    value = block.to_python(
        {
            "heading": "Hidden",
            "show_heading": False,
            "show_items": False,
            "kind": "links",
            "icon": "links",
            "intro": "",
            "items": [{"title": "Hidden item", "url": "https://example.com"}],
        }
    )

    html = block.render(value, context={"render_for_feed": False})

    assert "<h3>" not in html
    assert "Hidden item" not in html


def test_link_list_icon_is_hidden_for_feed():
    block = ShowNoteLinkListBlock()
    value = block.to_python(
        {
            "heading": "Links",
            "show_heading": True,
            "show_items": True,
            "kind": "auto",
            "icon": "links",
            "intro": "",
            "items": [{"title": "Python", "url": "https://www.python.org/"}],
        }
    )

    html = block.render(value, context={"render_for_feed": True})

    assert "show-note-icon" not in html
    assert "Links" in html
    assert "Python" in html


def test_sponsor_renders_copy_and_hides_icon_for_feed():
    block = ShowNoteSponsorBlock()
    value = block.to_python(
        {
            "heading": "Sponsor",
            "kind": "auto",
            "icon": "sponsor",
            "sponsor_name": "ACME",
            "sponsor_url": "https://example.com",
            "copy": '<p>Thanks to <a href="https://example.com">ACME</a>.</p>',
            "coupon_code": "PYTHON",
        }
    )

    html = block.render(value, context={"render_for_feed": False})
    feed_html = block.render(value, context={"render_for_feed": True})

    assert "show-note-icon--sponsor" in html
    assert "Thanks to" in html
    assert "Coupon code:" in html
    assert "PYTHON" in html
    assert "show-note-icon" not in feed_html
    assert "Sponsor" in feed_html


def test_sponsor_renders_link_fallback_without_copy():
    block = ShowNoteSponsorBlock()
    value = block.to_python(
        {
            "heading": "Sponsor",
            "kind": "auto",
            "icon": "sponsor",
            "sponsor_name": "ACME",
            "sponsor_url": "https://example.com",
            "copy": "",
            "coupon_code": "",
        }
    )

    html = block.render(value, context={"render_for_feed": False})

    assert '<a href="https://example.com">ACME</a>' in html
    assert "Coupon code:" not in html


def test_icon_helpers():
    assert resolve_icon_kind("🔗 Links") == "links"
    assert resolve_icon_kind("50% Rabatt") == "sale"
    assert glyph_for_kind("unknown") == glyph_for_kind("default")
