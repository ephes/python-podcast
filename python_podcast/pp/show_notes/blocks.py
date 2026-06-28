from __future__ import annotations

from django import forms
from wagtail import blocks

from python_podcast.pp.show_notes.icons import display_icon, kind_choices, materialize_icon

RICH_TEXT_FEATURES = ["bold", "italic", "link"]


def _kind_block() -> blocks.ChoiceBlock:
    return blocks.ChoiceBlock(choices=kind_choices(), default="auto")


class HiddenCharBlock(blocks.CharBlock):
    """CharBlock rendered with a hidden admin widget."""

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self.field.widget = forms.HiddenInput()


def _icon_block() -> blocks.CharBlock:
    # Stored concrete icon. It is system-managed from heading/kind and hidden in
    # the editor so old revisions keep rendering even if headings change later.
    return HiddenCharBlock(required=False, default="")


class IconBlockMixin:
    def clean(self, value):  # type: ignore[no-untyped-def]
        value = super().clean(value)  # pyright: ignore[reportAttributeAccessIssue]
        value["icon"] = materialize_icon(value)
        return value

    def get_context(self, value, parent_context=None):  # type: ignore[no-untyped-def]
        context = super().get_context(value, parent_context)  # pyright: ignore[reportAttributeAccessIssue]
        context["display_kind"] = display_icon(value)
        return context


class ShowNoteExtraLinkBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    url = blocks.URLBlock()

    class Meta:
        icon = "link"
        label = "Extra link"
        label_format = "{title}"


class ShowNoteLinkItemBlock(blocks.StructBlock):
    prefix = blocks.CharBlock(
        required=False,
        help_text="Optional text before the first link, for example 'Visualisierungen:'.",
    )
    title = blocks.CharBlock()
    url = blocks.URLBlock()
    extra_links = blocks.ListBlock(ShowNoteExtraLinkBlock(), required=False)
    note = blocks.CharBlock(
        required=False,
        label="Note / comment",
        help_text="Optional inline note after the link(s), for example 'Starts at the justfile part'.",
    )
    description = blocks.RichTextBlock(
        features=RICH_TEXT_FEATURES,
        required=False,
        help_text="Longer body text rendered below the link row. Most shownote comments belong in Note / comment.",
    )

    class Meta:
        icon = "link"
        label = "Link item"
        label_format = "{title}"


class ShowNoteHeadingBlock(IconBlockMixin, blocks.StructBlock):
    heading = blocks.CharBlock()
    kind = _kind_block()
    icon = _icon_block()

    class Meta:
        icon = "title"
        label = "Show-note heading"
        template = "cast/pp/show_notes/heading.html"


class ShowNoteSponsorBlock(IconBlockMixin, blocks.StructBlock):
    heading = blocks.CharBlock(default="Sponsor")
    kind = _kind_block()
    icon = _icon_block()
    sponsor_name = blocks.CharBlock()
    sponsor_url = blocks.URLBlock()
    copy = blocks.RichTextBlock(features=RICH_TEXT_FEATURES, required=False)
    coupon_code = blocks.CharBlock(required=False)

    class Meta:
        icon = "tag"
        label = "Show-note sponsor"
        template = "cast/pp/show_notes/sponsor.html"


class ShowNoteLinkListBlock(IconBlockMixin, blocks.StructBlock):
    heading = blocks.CharBlock(default="Links")
    show_heading = blocks.BooleanBlock(default=True, required=False)
    show_items = blocks.BooleanBlock(default=True, required=False)
    kind = _kind_block()
    icon = _icon_block()
    intro = blocks.RichTextBlock(features=RICH_TEXT_FEATURES, required=False)
    items = blocks.ListBlock(ShowNoteLinkItemBlock(), required=False)

    class Meta:
        icon = "link"
        label = "Show-note link list"
        template = "cast/pp/show_notes/link_list.html"


def sponsor_block() -> tuple[str, blocks.Block]:
    return "show_note_sponsor", ShowNoteSponsorBlock()


def link_list_block() -> tuple[str, blocks.Block]:
    return "show_note_link_list", ShowNoteLinkListBlock()


def heading_block() -> tuple[str, blocks.Block]:
    return "show_note_heading", ShowNoteHeadingBlock()
