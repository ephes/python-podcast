from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from python_podcast.pp.show_notes.converter import convert_paragraph_html


def _types(conversion):
    return [block.type for block in conversion.blocks]


def test_standalone_heading_becomes_heading_block():
    conversion = convert_paragraph_html("<h3>Bücher</h3>")

    assert conversion.changed is True
    assert _types(conversion) == ["show_note_heading"]
    assert conversion.blocks[0].value["heading"] == "Bücher"
    assert conversion.blocks[0].value["kind"] == "auto"


def test_heading_followed_by_list_becomes_single_link_list():
    html = '<h3>News</h3><ul><li><a href="https://example.com/a">Article A</a></li></ul>'

    conversion = convert_paragraph_html(html)

    assert conversion.changed is True
    assert _types(conversion) == ["show_note_link_list"]
    value = conversion.blocks[0].value
    assert value["heading"] == "News"
    assert [item["title"] for item in value["items"]] == ["Article A"]
    assert value["items"][0]["url"] == "https://example.com/a"


def test_prefix_is_extracted_before_first_link():
    html = '<h3>X</h3><ul><li>Visualisierungen:&nbsp;<a href="https://example.com/v">Vega</a></li></ul>'

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["prefix"] == "Visualisierungen: "
    assert item["title"] == "Vega"
    assert item["note"] == ""
    assert item["extra_links"] == []


def test_extra_links_are_extracted_after_separator():
    html = (
        "<h3>X</h3><ul><li>"
        '<a href="https://example.com/a">A</a>&nbsp;|&nbsp;<a href="https://example.com/b">B</a>'
        "</li></ul>"
    )

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["title"] == "A"
    assert item["url"] == "https://example.com/a"
    assert item["extra_links"] == [{"title": "B", "url": "https://example.com/b"}]
    assert item["note"] == ""


def test_note_is_extracted_and_separator_stripped():
    html = '<h3>X</h3><ul><li><a href="https://example.com/a">A</a> | Furchtbarer Report</li></ul>'

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["title"] == "A"
    assert item["note"] == "Furchtbarer Report"
    assert item["description"] == ""


def test_note_after_dash_is_extracted():
    html = '<h3>X</h3><ul><li><a href="https://example.com/a">A</a>&nbsp;- first release candidate</li></ul>'

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["note"] == "first release candidate"


def test_intro_paragraph_is_preserved_between_headings():
    html = (
        "<h2>Shownotes</h2>"
        '<p>Unsere E-Mail: <a href="mailto:hallo@example.com">hallo@example.com</a></p>'
        '<h3>News</h3><ul><li><a href="https://example.com/a">A</a></li></ul>'
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph", "show_note_link_list"]
    assert "mailto:hallo@example.com" in conversion.blocks[1].value
    assert conversion.blocks[0].value["heading"] == "Shownotes"
    assert conversion.blocks[2].value["heading"] == "News"


def test_prose_without_shownote_structure_is_unchanged():
    html = "<p>Just some prose.</p><ul><li>plain bullet without a link</li></ul>"

    conversion = convert_paragraph_html(html)

    assert conversion.changed is False


def test_grouped_label_with_single_link_subitems_flattens():
    html = (
        "<h3>News</h3><ul>"
        "<li>Django 5.0<ul>"
        '<li><a href="https://example.com/rn">Release Notes</a></li>'
        '<li><a href="https://example.com/wn">What is new</a></li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_link_list"]
    item = conversion.blocks[0].value["items"][0]
    assert item["prefix"] == "Django 5.0: "
    assert item["title"] == "Release Notes"
    assert item["url"] == "https://example.com/rn"
    assert item["extra_links"] == [{"title": "What is new", "url": "https://example.com/wn"}]
    assert item["note"] == ""
    assert conversion.warnings == []


def test_grouped_subitem_note_becomes_item_note():
    html = (
        "<h3>News</h3><ul>"
        "<li>GIL Removal<ul>"
        '<li><a href="https://example.com/ep">Episode 2</a></li>'
        '<li><a href="https://example.com/pep">PEP 703</a> | Accepted PEP</li>'
        "</ul></li>"
        "</ul>"
    )

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["prefix"] == "GIL Removal: "
    assert item["title"] == "Episode 2"
    assert item["extra_links"] == [{"title": "PEP 703", "url": "https://example.com/pep"}]
    assert item["note"] == "Accepted PEP"


def test_grouped_note_on_final_subitem_flattens():
    # A note on the LAST sub-link sits correctly as a trailing item note.
    html = (
        "<h3>News</h3><ul>"
        "<li>GIL<ul>"
        '<li><a href="https://example.com/ep">Episode 2</a></li>'
        '<li><a href="https://example.com/pep">PEP 703</a> | Accepted PEP</li>'
        "</ul></li>"
        "</ul>"
    )

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert item["title"] == "Episode 2"
    assert item["extra_links"] == [{"title": "PEP 703", "url": "https://example.com/pep"}]
    assert item["note"] == "Accepted PEP"


def test_grouped_note_on_non_final_subitem_preserves_section():
    # A note on a non-final sub-link cannot be placed correctly in the flat item
    # (it would render after every link), so the group is preserved verbatim.
    html = (
        "<h3>News</h3><ul>"
        "<li>GIL<ul>"
        '<li><a href="https://example.com/paper">Biased Reference Counting</a> | Paper von 2018</li>'
        '<li><a href="https://example.com/keynote">Keynote</a></li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    rendered = " ".join(str(block.value) for block in conversion.blocks)
    assert "example.com/paper" in rendered
    assert "example.com/keynote" in rendered
    assert "Paper von 2018" in rendered
    assert conversion.warnings


def test_grouped_multilink_subitem_preserves_section():
    html = (
        "<h3>News</h3><ul>"
        "<li>Sprachen<ul>"
        '<li><a href="https://example.com/v">vlang</a> | <a href="https://example.com/z">zig</a></li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_grouped_multiple_notes_preserves_section():
    html = (
        "<h3>News</h3><ul>"
        "<li>Topic<ul>"
        '<li><a href="https://example.com/a">A</a> - note one</li>'
        '<li><a href="https://example.com/b">B</a> - note two</li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_grouped_large_group_preserves_section():
    subitems = "".join(f'<li><a href="https://example.com/{i}">Link {i}</a></li>' for i in range(7))
    html = f"<h3>News</h3><ul><li>Big Topic<ul>{subitems}</ul></li></ul>"

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_grouped_label_with_link_preserves_section():
    html = (
        "<h3>News</h3><ul>"
        '<li><a href="https://example.com/label">Label link</a> intro<ul>'
        '<li><a href="https://example.com/sub">Sub</a></li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_deeply_nested_list_preserves_section():
    html = (
        "<h3>News</h3><ul>"
        "<li>Top<ul><li>Mid<ul>"
        '<li><a href="https://example.com/deep">Deep</a></li>'
        "</ul></li></ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_mixed_flat_and_grouped_items_convert_together():
    html = (
        "<h3>News</h3><ul>"
        '<li><a href="https://example.com/flat">Flat</a></li>'
        '<li>Group<ul><li><a href="https://example.com/sub">Sub</a></li></ul></li>'
        "</ul>"
    )

    items = convert_paragraph_html(html).blocks[0].value["items"]

    assert [i["title"] for i in items] == ["Flat", "Sub"]
    assert items[0]["prefix"] == ""
    assert items[1]["prefix"] == "Group: "


def test_item_without_link_preserves_section_with_warning():
    html = "<h3>News</h3><ul><li>No link in this bullet</li></ul>"

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_non_web_link_preserves_section_with_warning():
    html = '<h3>Contact</h3><ul><li><a href="mailto:x@example.com">Mail us</a></li></ul>'

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_text_between_links_that_is_not_separator_preserves_section():
    html = (
        "<h3>X</h3><ul><li>"
        '<a href="https://example.com/a">A</a> and also see <a href="https://example.com/b">B</a>'
        "</li></ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.warnings


def test_list_with_stray_non_li_content_preserves_section():
    # A <ul> that holds direct text/block content besides <li> items must not be
    # converted, or that stray content would be silently dropped.
    html = (
        "<h3>News</h3><ul>"
        "stray text that is not in a list item"
        '<li><a href="https://example.com/a">A</a></li>'
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert "stray text" in conversion.blocks[1].value
    assert conversion.warnings


def test_list_with_some_ambiguous_items_converts_the_rest():
    html = (
        "<h3>Links</h3><ul>"
        '<li><a href="https://example.com/a">A</a></li>'
        "<li>Plugins<ul>"
        '<li><a href="https://example.com/p1">p1</a> | <a href="https://example.com/p2">p2</a></li>'
        "</ul></li>"
        '<li><a href="https://example.com/b">B</a></li>'
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == [
        "show_note_heading",
        "show_note_link_list",
        "paragraph",
        "show_note_link_list",
    ]
    assert conversion.blocks[0].value["heading"] == "Links"
    assert conversion.blocks[1].value["items"][0]["title"] == "A"
    assert conversion.blocks[1].value["show_heading"] is False
    assert "Plugins" in conversion.blocks[2].value
    assert "example.com/p1" in conversion.blocks[2].value
    assert conversion.blocks[3].value["items"][0]["title"] == "B"
    assert conversion.warnings


def test_list_with_consecutive_ambiguous_items_groups_them():
    html = (
        "<h3>Links</h3><ul>"
        '<li><a href="https://example.com/a">A</a></li>'
        "<li>no link one</li>"
        "<li>no link two</li>"
        '<li><a href="https://example.com/b">B</a></li>'
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == [
        "show_note_heading",
        "show_note_link_list",
        "paragraph",
        "show_note_link_list",
    ]
    # both no-link items land in a single preserved fragment
    assert "no link one" in conversion.blocks[2].value
    assert "no link two" in conversion.blocks[2].value


def test_heading_containing_a_link_is_preserved_verbatim():
    # A heading with an inline link cannot become a plain text show_note_heading
    # without dropping the link, so the whole heading is preserved verbatim.
    html = '<h3>Typing Quadrants aus <a href="https://example.com/book">Fluent Python</a></h3>'

    conversion = convert_paragraph_html(html)

    assert any("https://example.com/book" in str(block.value) for block in conversion.blocks)
    assert any(block.type == "paragraph" for block in conversion.blocks)
    assert conversion.warnings


def test_heading_with_link_before_list_keeps_link_and_preserves_list():
    html = (
        '<h3>Books from <a href="https://example.com/src">Source</a></h3>'
        '<ul><li><a href="https://example.com/a">A</a></li></ul>'
    )

    conversion = convert_paragraph_html(html)

    rendered = " ".join(str(block.value) for block in conversion.blocks)
    assert "https://example.com/src" in rendered
    assert "https://example.com/a" in rendered


def test_br_separated_prose_links_keep_their_separators():
    html = "<h2>Shownotes</h2>" '<a href="https://example.com/a">A</a><br/>' '<a href="https://example.com/b">B</a>'

    conversion = convert_paragraph_html(html)

    paragraph = next(block.value for block in conversion.blocks if block.type == "paragraph")
    assert "<br" in paragraph
    assert "https://example.com/a" in paragraph
    assert "https://example.com/b" in paragraph


def test_zero_width_space_is_stripped_from_prefix():
    html = "<h3>X</h3><ul><li>Network Automation​​: " '<a href="https://example.com/a">Liste</a></li></ul>'

    item = convert_paragraph_html(html).blocks[0].value["items"][0]

    assert "​" not in item["prefix"]
    assert item["prefix"] == "Network Automation: "


def test_group_with_long_descriptive_label_is_preserved():
    desc = (
        "Ansible ist ein Werkzeug zum Managen von Servern. Benannt nach einem "
        "Science-Fiction-Geraet, das FTL-Kommunikation ermoeglicht."
    )
    html = (
        "<h3>Tools</h3><ul>"
        f"<li>{desc}<ul>"
        '<li><a href="https://example.com/a">ansible</a></li>'
        '<li><a href="https://example.com/b">chef</a></li>'
        "</ul></li>"
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    rendered = " ".join(str(block.value) for block in conversion.blocks)
    assert "https://example.com/a" in rendered
    assert "https://example.com/b" in rendered
    assert conversion.warnings


def test_ordered_list_is_preserved_verbatim():
    # Ordered lists carry meaningful numbering, so they are preserved rather
    # than flattened into an unordered link list.
    html = (
        "<h3>Steps</h3><ol>"
        '<li><a href="https://example.com/a">A</a></li>'
        '<li><a href="https://example.com/b">B</a></li>'
        "</ol>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert "<ol>" in conversion.blocks[1].value
    assert "example.com/b" in conversion.blocks[1].value
    assert conversion.warnings


def test_embed_only_pending_content_is_preserved():
    # A Wagtail rich-text embed has no text/link/img but must not be dropped when
    # the surrounding paragraph is otherwise converted.
    html = (
        '<h3>News</h3><ul><li><a href="https://example.com/a">A</a></li></ul>'
        '<embed embedtype="media" url="https://youtube.com/watch?v=x"/>'
    )

    conversion = convert_paragraph_html(html)

    assert "show_note_link_list" in _types(conversion)
    assert any(block.type == "paragraph" and "embed" in block.value for block in conversion.blocks)


def test_empty_html_is_unchanged():
    conversion = convert_paragraph_html("")

    assert conversion.changed is False


# -- heading media / markup preservation ---------------------------------

LINK_LIST = '<ul><li><a href="https://example.com/a">A</a></li></ul>'


@pytest.mark.parametrize(
    "heading",
    [
        '<h2><img alt="" src="meaningful.png"/>Links</h2>',
        '<h2>Links <svg viewbox="0 0 1 1"><title>Icon</title><path d="M0 0"></path></svg></h2>',
        '<h2>Links <embed embedtype="image" format="left" id="7"/></h2>',
        '<h2><iframe src="https://example.com/player"></iframe>Video</h2>',
        "<h2>Tools: <code>uv</code></h2>",
        "<h2>Wirklich <em>wichtige</em> Links</h2>",
        "<h2>Links<!-- keep me --></h2>",
        "<h2>Erste Zeile<br/>Zweite Zeile</h2>",
    ],
)
def test_heading_with_unrepresentable_markup_is_preserved_verbatim(heading):
    # A show_note_heading stores plain text only. Converting such a heading
    # would silently drop the image/embed/markup, so heading and list stay HTML.
    conversion = convert_paragraph_html(heading + LINK_LIST)

    assert _types(conversion) == ["paragraph"]
    assert conversion.blocks[0].value == heading + LINK_LIST
    assert conversion.changed is False
    assert len(conversion.warnings) == 1
    assert "preserved verbatim" in conversion.warnings[0]


def test_heading_with_linked_image_is_preserved_verbatim():
    heading = '<h2><a href="https://example.com/sponsor"><img alt="Sponsor" src="logo.png"/></a> Sponsor</h2>'

    conversion = convert_paragraph_html(heading + LINK_LIST)

    assert _types(conversion) == ["paragraph"]
    assert conversion.blocks[0].value == heading + LINK_LIST
    assert conversion.warnings


def test_heading_media_preserved_without_following_list():
    heading = '<h3><img alt="" src="meaningful.png"/>Bücher</h3>'

    conversion = convert_paragraph_html(heading)

    assert _types(conversion) == ["paragraph"]
    assert conversion.blocks[0].value == heading
    assert conversion.changed is False


def test_unrepresentable_heading_does_not_block_other_sections():
    html = (
        "<h2>Shownotes</h2>"
        '<h3><img alt="" src="news.png"/>News</h3>'
        + LINK_LIST
        + '<h3>Bücher</h3><ul><li><a href="https://example.com/b">B</a></li></ul>'
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_heading", "paragraph", "show_note_link_list"]
    assert conversion.blocks[1].value == '<h3><img alt="" src="news.png"/>News</h3>' + LINK_LIST
    assert conversion.blocks[2].value["heading"] == "Bücher"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("<h3>News</h3>", "News"),
        ("<h3><b>News</b></h3>", "News"),
        ("<h3><strong>News</strong> und Links</h3>", "News und Links"),
        ("<h3>News<br/></h3>", "News"),
        ("<h3>\n  News aus\n  der Szene\n</h3>", "News aus der Szene"),
        ("<h3>News&nbsp;</h3>", "News"),
    ],
)
def test_plain_text_heading_still_converts(heading, expected):
    conversion = convert_paragraph_html(heading + LINK_LIST)

    assert _types(conversion) == ["show_note_link_list"]
    assert conversion.blocks[0].value["heading"] == expected
    assert conversion.warnings == []


def test_converted_plain_headings_are_idempotent_input():
    # Converting twice from the same legacy HTML yields the same blocks.
    html = "<h3><b>News</b></h3>" + LINK_LIST

    first = convert_paragraph_html(html)
    second = convert_paragraph_html(html)

    assert [(b.type, b.value) for b in first.blocks] == [(b.type, b.value) for b in second.blocks]


# -- inline semantics in prefix / note / link title -----------------------


@pytest.mark.parametrize(
    "item",
    [
        '<li><strong>Required:</strong> <a href="https://example.com/x">X</a></li>',
        '<li><a href="https://example.com/x">X</a> | <code>pip install x</code></li>',
        '<li><a href="https://example.com/x">X</a> - wirklich <em>sehr</em> gut</li>',
        '<li><i>Neu:</i> <a href="https://example.com/x">X</a> | <a href="https://example.com/y">Y</a></li>',
        '<li><a href="https://example.com/x"><code>uv</code> Dokumentation</a></li>',
        '<li><a href="https://example.com/x">X</a><!-- recorded later --></li>',
        '<li><a href="https://example.com/x">X</a> H<sub>2</sub>O</li>',
        '<li><a href="https://example.com/x">X<!-- keep me --></a></li>',
        '<li><a href="https://example.com/x">X</a><b> | <!-- keep me --></b></li>',
        '<li><a href="https://example.com/x">X</a><span><i><!-- keep me --></i></span></li>',
    ],
)
def test_item_with_formatted_prefix_or_note_is_preserved(item):
    # prefix/title/note are plain-text fields: flattening would drop the markup.
    conversion = convert_paragraph_html(f"<h3>Links</h3><ul>{item}</ul>")

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.blocks[1].value == f"<ul>{item}</ul>"
    assert len(conversion.warnings) == 1
    assert "Ambiguous list item preserved as prose" in conversion.warnings[0]


def test_formatted_item_in_mixed_list_keeps_markup_and_order():
    formatted = (
        '<li><strong>Required:</strong> <a href="https://example.com/x">X</a> | <code>pip install x</code></li>'
    )
    html = (
        "<h3>Links</h3><ul>"
        '<li><a href="https://example.com/a">A</a> | plain note</li>'
        + formatted
        + '<li>Prefix: <a href="https://example.com/b">B</a></li>'
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == [
        "show_note_heading",
        "show_note_link_list",
        "paragraph",
        "show_note_link_list",
    ]
    assert conversion.blocks[1].value["items"][0]["note"] == "plain note"
    assert conversion.blocks[2].value == f"<ul>{formatted}</ul>"
    assert conversion.blocks[3].value["items"][0]["prefix"] == "Prefix: "


def test_group_label_with_formatting_is_preserved():
    item = (
        "<li><code>django-cast</code>"
        '<ul><li><a href="https://example.com/a">A</a></li><li><a href="https://example.com/b">B</a></li></ul>'
        "</li>"
    )

    conversion = convert_paragraph_html(f"<h3>Links</h3><ul>{item}</ul>")

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.blocks[1].value == f"<ul>{item}</ul>"
    assert conversion.warnings


def test_group_subitem_with_formatted_note_is_preserved():
    item = "<li>Django" '<ul><li><a href="https://example.com/a">A</a> | <code>5.0</code></li></ul>' "</li>"

    conversion = convert_paragraph_html(f"<h3>Links</h3><ul>{item}</ul>")

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.blocks[1].value == f"<ul>{item}</ul>"


def test_formatting_around_separator_only_still_converts():
    # Formatting that wraps nothing but a separator carries no content.
    html = (
        "<h3>Links</h3><ul>"
        '<li><a href="https://example.com/a">A</a><b> | </b><a href="https://example.com/b">B</a><i> </i></li>'
        "</ul>"
    )

    conversion = convert_paragraph_html(html)

    assert _types(conversion) == ["show_note_link_list"]
    item = conversion.blocks[0].value["items"][0]
    assert item["title"] == "A"
    assert item["extra_links"] == [{"title": "B", "url": "https://example.com/b"}]
    assert item["note"] == ""
    assert conversion.warnings == []


def test_empty_formatting_wrapping_an_element_is_preserved():
    item = '<li><a href="https://example.com/a">A</a><span><svg viewbox="0 0 1 1"></svg></span></li>'

    conversion = convert_paragraph_html(f"<h3>Links</h3><ul>{item}</ul>")

    assert _types(conversion) == ["show_note_heading", "paragraph"]
    assert conversion.blocks[1].value == f"<ul>{item}</ul>"


REALISTIC_SHOWNOTES = (
    "<h2>Shownotes</h2>"
    '<p>Unsere E-Mail für Fragen, Anregungen &amp; Kommentare: <a href="mailto:hallo@example.com">'
    "hallo@example.com</a></p>"
    "<h3>News aus der Szene</h3>"
    "<ul>"
    '<li><a href="https://example.com/python-3-14">Python 3.14</a> | <a href="https://example.com/whatsnew">'
    "What's new</a></li>"
    '<li>Typing:&nbsp;<a href="https://example.com/pep">PEP 695</a> – neue Syntax</li>'
    '<li><strong>Wichtig:</strong> <a href="https://example.com/sec">Security Release</a> | '
    "<code>pip install -U django</code></li>"
    "</ul>"
    '<h3><img alt="Werbung" src="https://example.com/sponsor.png"/> Werbung</h3>'
    '<ul><li><a href="https://example.com/sponsor">Sponsor</a></li></ul>'
    "<h3>Picks</h3>"
    '<ul><li><a href="https://example.com/pick"><em>Fluent</em> Python</a></li>'
    '<li><a href="https://example.com/pick2">Textual</a></li></ul>'
)


def _visible_markup(html):
    """Links, images and inline formatting of an HTML fragment, in order."""
    soup = BeautifulSoup(html, "html.parser")
    return [str(tag) for tag in soup.find_all(["a", "img", "strong", "code", "em"])]


def _rendered_fragments(conversion):
    """Everything a reader can still see after conversion, block by block."""
    fragments = []
    for block in conversion.blocks:
        if block.type == "paragraph":
            fragments.append(block.value)
        elif block.type == "show_note_link_list":
            for item in block.value["items"]:
                links = [(item["title"], item["url"])] + [(e["title"], e["url"]) for e in item["extra_links"]]
                fragments.append("".join(f'<a href="{url}">{title}</a>' for title, url in links))
    return "".join(fragments)


def test_realistic_shownotes_round_trip_keeps_every_link_image_and_format():
    conversion = convert_paragraph_html(REALISTIC_SHOWNOTES)

    assert _types(conversion) == [
        "show_note_heading",  # Shownotes
        "paragraph",  # contact prose
        "show_note_heading",  # News aus der Szene
        "show_note_link_list",  # two clean items
        "paragraph",  # formatted "Wichtig" item
        "paragraph",  # Werbung heading with image + its list
        "show_note_heading",  # Picks
        "paragraph",  # link title with emphasis
        "show_note_link_list",  # Textual
    ]
    # Nothing a reader could see or click is lost: every link, image and
    # inline format of the source is still present, in the original order.
    assert _visible_markup(_rendered_fragments(conversion)) == _visible_markup(REALISTIC_SHOWNOTES)
    preserved = "".join(block.value for block in conversion.blocks if block.type == "paragraph")
    assert "<strong>Wichtig:</strong>" in preserved
    assert "<code>pip install -U django</code>" in preserved
    assert '<img alt="Werbung" src="https://example.com/sponsor.png"/>' in preserved
    assert "<em>Fluent</em> Python" in preserved
    assert len(conversion.warnings) == 3
