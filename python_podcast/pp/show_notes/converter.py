"""Conservative converter from legacy shownote HTML to structured blocks.

The converter is intentionally pure: it takes the HTML of a single ``paragraph``
detail child and returns an ordered list of replacement blocks plus warnings. It
never touches the database. The management command in
``pp/management/commands/convert_show_notes.py`` is responsible for loading
episodes, preserving sibling blocks and writing Wagtail revisions.

Design rules (see the conversion spec):

* Split a paragraph by headings (``h1``-``h6``).
* A standalone heading becomes ``show_note_heading``.
* A heading immediately followed by a ``ul``/``ol`` becomes a
  ``show_note_link_list``.
* Contact/intro prose stays as a ``paragraph``.
* Anything ambiguous (nested lists, block content, items without a single web
  link, non-separator text between links) is preserved verbatim as a
  ``paragraph`` with a warning rather than risk a lossy conversion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from python_podcast.pp.show_notes.icons import materialize_icon

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
LIST_TAGS = {"ul", "ol"}

# Inline formatting tags that may legitimately wrap prefix/note text.
INLINE_TEXT_TAGS = {"strong", "b", "em", "i", "code", "span", "sup", "sub", "small", "u"}
# Block-level tags inside a list item signal a richer structure we will not flatten.
BLOCK_TAGS = {"p", "div", "blockquote", "pre", "table", "ul", "ol", "img"} | HEADING_TAGS

_SEPARATOR_CHARS = "|/–—·•-"
_SEPARATOR_RE = re.compile(rf"^[\s{re.escape(_SEPARATOR_CHARS)}]+")
_SEPARATOR_TRAIL_RE = re.compile(rf"[\s{re.escape(_SEPARATOR_CHARS)}]+$")
_WEB_SCHEMES = ("http://", "https://")

# Largest "topic label + sub-links" group we will flatten into a single link
# item. Bigger groups are preserved as prose to avoid an unreadable link row.
MAX_GROUP_SUBITEMS = 6
# A group label longer than this is treated as descriptive prose rather than a
# short topic label, so the group is preserved instead of flattened.
MAX_GROUP_LABEL_LENGTH = 60


@dataclass
class ConvertedBlock:
    """One replacement block.

    ``type`` is ``show_note_heading``, ``show_note_link_list`` or ``paragraph``.
    For show-note blocks ``value`` is the raw struct dict; for paragraphs it is
    the HTML string.
    """

    type: str
    value: object


@dataclass
class ParagraphConversion:
    blocks: list[ConvertedBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changed: bool = False


def convert_paragraph_html(html: str) -> ParagraphConversion:
    """Convert one paragraph's HTML into structured shownote blocks."""
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = [node for node in soup.contents]

    builder = _Builder()
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if isinstance(node, Tag) and node.name in HEADING_TAGS:
            index = builder.handle_heading(node, nodes, index)
        else:
            # Everything else - including <br> and whitespace - is buffered as
            # prose so separators survive; a list here has no preceding heading
            # and stays untouched. Pure-whitespace buffers are dropped on flush.
            builder.add_to_pending(node)
            index += 1

    builder.flush_pending()
    return ParagraphConversion(blocks=builder.blocks, warnings=builder.warnings, changed=builder.changed)


class _Builder:
    def __init__(self) -> None:
        self.blocks: list[ConvertedBlock] = []
        self.warnings: list[str] = []
        self.changed = False
        self._pending: list[object] = []

    # -- pending prose --------------------------------------------------
    def add_to_pending(self, node: object) -> None:
        self._pending.append(node)

    def flush_pending(self) -> None:
        if not self._pending:
            return
        html = "".join(str(node) for node in self._pending).strip()
        self._pending = []
        if _has_meaningful_content(html):
            self.blocks.append(ConvertedBlock("paragraph", html))

    # -- headings -------------------------------------------------------
    def handle_heading(self, heading: Tag, nodes: list[object], index: int) -> int:
        self.flush_pending()
        heading_text = _clean_text(heading.get_text())
        if not heading_text:
            # Nothing useful in this heading; preserve it verbatim.
            self.add_to_pending(heading)
            return index + 1

        if heading.find("a") is not None:
            # A show_note_heading only stores plain text, so converting a heading
            # that contains a link would drop the link. Preserve it verbatim.
            self.warnings.append("Heading contains a link; preserved verbatim to keep the link.")
            self.add_to_pending(heading)
            return index + 1

        next_index = _next_meaningful_index(nodes, index + 1)
        next_node = nodes[next_index] if next_index is not None else None

        if isinstance(next_node, Tag) and next_node.name in LIST_TAGS:
            self._convert_list_section(heading_text, next_node)
            return next_index + 1

        self._emit_heading(heading_text)
        return index + 1

    def _convert_list_section(self, heading_text: str, list_tag: Tag) -> None:
        if list_tag.name == "ol":
            # Ordered lists carry meaningful numbering; converting (or splitting)
            # them would renumber or drop the order, so preserve them verbatim.
            self._emit_heading(heading_text)
            self.warnings.append("Ordered list preserved verbatim to keep its numbering.")
            self.add_to_pending(list_tag)
            return

        entries, warnings = parse_link_list(list_tag)
        self.warnings.extend(warnings)

        if entries is None:
            # Malformed list (stray content): keep the heading, preserve whole.
            self._emit_heading(heading_text)
            self.add_to_pending(list_tag)
            return

        kinds = {kind for kind, _payload in entries}
        if kinds == {"item"}:
            # Every item is clean: one link list carrying the heading.
            self._emit_link_list(heading_text, [payload for _kind, payload in entries])
            return
        if kinds == {"preserve"}:
            # Nothing convertible: heading plus the preserved list.
            self._emit_heading(heading_text)
            self.add_to_pending(list_tag)
            return

        # Mixed: convert the clean items, preserve only the ambiguous ones, in
        # order, under a single standalone heading.
        self._emit_heading(heading_text)
        self._emit_mixed_entries(heading_text, entries, list_tag.name)

    def _emit_mixed_entries(self, heading_text: str, entries: list[tuple[str, object]], list_name: str) -> None:
        run_items: list[dict] = []
        run_preserve: list[Tag] = []

        def flush_items() -> None:
            if run_items:
                self._emit_link_list(heading_text, list(run_items), show_heading=False)
                run_items.clear()

        def flush_preserve() -> None:
            if run_preserve:
                html = f"<{list_name}>" + "".join(str(li) for li in run_preserve) + f"</{list_name}>"
                if _has_meaningful_content(html):
                    self.blocks.append(ConvertedBlock("paragraph", html))
                run_preserve.clear()

        for kind, payload in entries:
            if kind == "item":
                flush_preserve()
                run_items.append(payload)  # type: ignore[arg-type]
            else:
                flush_items()
                run_preserve.append(payload)  # type: ignore[arg-type]
        flush_items()
        flush_preserve()

    def _emit_heading(self, heading_text: str) -> None:
        value = {"heading": heading_text, "kind": "auto", "icon": ""}
        value["icon"] = materialize_icon(value)
        self.blocks.append(ConvertedBlock("show_note_heading", value))
        self.changed = True

    def _emit_link_list(self, heading_text: str, items: list[dict], *, show_heading: bool = True) -> None:
        value = {
            "heading": heading_text,
            "show_heading": show_heading,
            "show_items": True,
            "kind": "auto",
            "icon": "",
            "intro": "",
            "items": items,
        }
        value["icon"] = materialize_icon(value)
        self.blocks.append(ConvertedBlock("show_note_link_list", value))
        self.changed = True


def parse_link_list(list_tag: Tag) -> tuple[list[tuple[str, object]] | None, list[str]]:
    """Classify a ``ul``/``ol`` into ordered entries.

    Returns ``(entries, warnings)`` where each entry is ``("item", value_dict)``
    for a convertible link item or ``("preserve", li_tag)`` for an ambiguous one.
    ``entries`` is ``None`` when the list itself is malformed (stray non-item
    content) and must be preserved whole.
    """
    # Any direct child that is not an <li> (stray text or block content) means the
    # list is malformed; preserve it as prose rather than drop that content.
    for child in list_tag.children:
        if isinstance(child, NavigableString):
            if _clean_text(str(child)):
                return None, [f"List <{list_tag.name}> has direct text outside list items; preserved as prose."]
        elif isinstance(child, Tag) and child.name != "li":
            return None, [
                f"List <{list_tag.name}> has a direct <{child.name}> outside list items; preserved as prose."
            ]

    list_items = [child for child in list_tag.find_all("li", recursive=False)]
    if not list_items:
        return None, [f"List <{list_tag.name}> has no direct items; preserved as prose."]

    entries: list[tuple[str, object]] = []
    warnings: list[str] = []
    for li in list_items:
        item, warning = parse_list_item(li)
        if item is None:
            entries.append(("preserve", li))
            warnings.append(f"Ambiguous list item preserved as prose: {warning}")
        else:
            entries.append(("item", item))
    return entries, warnings


def parse_list_item(li: Tag) -> tuple[dict | None, str | None]:
    """Parse a single ``li`` into a link-item dict or flag it as ambiguous.

    A flat ``li`` (one logical line of links) is parsed directly. A ``li`` shaped
    as a topic label followed by a single nested list of sub-links is flattened
    into one item (label -> prefix, sub-links -> main link + extra links).
    """
    nested = _direct_nested_list(li)
    if nested is not None:
        return _parse_grouped_item(li, nested)
    return _parse_flat_item(li)


def _parse_flat_item(li: Tag) -> tuple[dict | None, str | None]:
    """Parse a flat ``li`` (no nested list) into a link-item dict."""
    # Reject nested lists / block content outright.
    if li.find(list(BLOCK_TAGS)) is not None:
        return None, "contains nested list or block-level content"

    tokens = _tokenize_item(li)
    if tokens is None:
        return None, "contains a link nested inside formatting"

    links = [token for token in tokens if token[0] == "link"]
    if not links:
        return None, "has no link"

    for _kind, payload in links:
        if not payload["url"].lower().startswith(_WEB_SCHEMES):
            return None, "has a non-web link"

    # Partition tokens around the first link.
    first_link_pos = next(i for i, token in enumerate(tokens) if token[0] == "link")
    prefix_text = _clean_text("".join(t[1] for t in tokens[:first_link_pos] if t[0] == "text"))

    main = links[0][1]
    extra_links = [{"title": link[1]["title"], "url": link[1]["url"]} for link in links[1:]]

    # Any text that appears strictly between two links must be a pure separator.
    last_link_pos = max(i for i, token in enumerate(tokens) if token[0] == "link")
    between = "".join(t[1] for i, t in enumerate(tokens) if t[0] == "text" and first_link_pos < i < last_link_pos)
    if not _is_separator_only(between):
        return None, "has non-separator text between links"

    trailing = "".join(t[1] for i, t in enumerate(tokens) if t[0] == "text" and i > last_link_pos)
    note = _strip_separators(_clean_text(trailing))

    prefix = f"{prefix_text} " if prefix_text else ""
    return {
        "prefix": prefix,
        "title": main["title"],
        "url": main["url"],
        "extra_links": extra_links,
        "note": note,
        "description": "",
    }, None


def _direct_nested_list(li: Tag) -> Tag | None:
    """Return the single direct ``ul``/``ol`` child of ``li``, else ``None``."""
    direct_lists = [child for child in li.children if isinstance(child, Tag) and child.name in LIST_TAGS]
    if len(direct_lists) != 1:
        return None
    return direct_lists[0]


def _parse_grouped_item(li: Tag, nested: Tag) -> tuple[dict | None, str | None]:
    """Flatten a ``topic label + nested single-link sub-items`` ``li``.

    The label becomes the item ``prefix``, the first sub-link the main link, the
    rest ``extra_links``, and a lone sub-item note the item ``note``. Anything
    that would lose structure (multi-link sub-items, several notes, very large
    groups, deeper nesting) is reported as ambiguous so the caller preserves it.
    """
    label_tokens = _tokenize_item(li, skip=nested)
    if label_tokens is None or any(kind == "link" for kind, _ in label_tokens):
        return None, "group label contains a link or unsupported markup"
    label = _clean_text("".join(payload for kind, payload in label_tokens if kind == "text"))
    if not label:
        return None, "nested list without a topic label"
    if len(label) > MAX_GROUP_LABEL_LENGTH:
        # A long label is descriptive prose, not a short topic label; flattening
        # it into a prefix (and demoting peers to extra links) would mislead.
        return None, "nested group label is descriptive prose, not a topic label"

    # The nested list must contain only <li> items, nothing stray.
    for child in nested.children:
        if isinstance(child, NavigableString):
            if _clean_text(str(child)):
                return None, "nested list has text outside its items"
        elif isinstance(child, Tag) and child.name != "li":
            return None, "nested list has non-item content"

    sub_items = nested.find_all("li", recursive=False)
    if not sub_items:
        return None, "nested list has no items"
    if len(sub_items) > MAX_GROUP_SUBITEMS:
        return None, "nested group is too large to flatten"

    links: list[dict] = []
    notes: list[tuple[int, str]] = []
    for position, sub in enumerate(sub_items):
        if _direct_nested_list(sub) is not None:
            return None, "nested group is more than two levels deep"
        item, _warning = _parse_flat_item(sub)
        if item is None:
            return None, "a nested sub-item could not be parsed safely"
        if item["extra_links"] or item["prefix"]:
            return None, "a nested sub-item has multiple links or its own prefix"
        links.append({"title": item["title"], "url": item["url"]})
        if item["note"]:
            notes.append((position, item["note"]))
    if len(notes) > 1:
        return None, "nested group has more than one note"
    # The flat item has a single, trailing note field. A note can only be placed
    # faithfully when it belongs to the last sub-link; otherwise it would render
    # after every link and read as describing the wrong one -> preserve instead.
    if notes and notes[0][0] != len(sub_items) - 1:
        return None, "nested group note belongs to a non-final sub-link"

    return {
        "prefix": _label_prefix(label),
        "title": links[0]["title"],
        "url": links[0]["url"],
        "extra_links": links[1:],
        "note": notes[0][1] if notes else "",
        "description": "",
    }, None


def _label_prefix(label: str) -> str:
    label = _SEPARATOR_TRAIL_RE.sub("", label).rstrip(":").rstrip()
    return f"{label}: "


def _tokenize_item(li: Tag, skip: Tag | None = None) -> list[tuple[str, object]] | None:
    """Flatten an ``li`` into an ordered list of ('text', str) / ('link', dict).

    ``skip`` is an optional direct child (e.g. a nested list) to ignore. Returns
    ``None`` if a link is nested inside an inline formatting tag, which we treat
    as too ambiguous to convert safely.
    """
    tokens: list[tuple[str, object]] = []
    for child in li.children:
        if child is skip:
            continue
        if isinstance(child, NavigableString):
            tokens.append(("text", str(child)))
        elif isinstance(child, Tag):
            if child.name == "a":
                tokens.append(("link", {"title": _clean_text(child.get_text()), "url": child.get("href", "")}))
            elif child.name == "br":
                tokens.append(("text", " "))
            elif child.name in INLINE_TEXT_TAGS:
                if child.find("a") is not None:
                    return None
                tokens.append(("text", child.get_text()))
            else:
                # Unknown tag: be conservative.
                return None
    return tokens


def _next_meaningful_index(nodes: list[object], start: int) -> int | None:
    for i in range(start, len(nodes)):
        if not _is_blank(nodes[i]):
            return i
    return None


def _is_blank(node: object) -> bool:
    if isinstance(node, NavigableString):
        return not _clean_text(str(node))
    if isinstance(node, Tag) and node.name == "br":
        return True
    return False


def _has_meaningful_content(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    # Any real element (link, image, embed, iframe, hr, table, ...) is content
    # worth keeping. Only buffers that are purely whitespace and <br> are dropped.
    if any(tag.name != "br" for tag in soup.find_all(True)):
        return True
    return bool(_clean_text(soup.get_text()))


def _clean_text(text: str) -> str:
    text = (text or "").replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def _is_separator_only(text: str) -> bool:
    return _strip_separators(_clean_text(text)) == ""


def _strip_separators(text: str) -> str:
    text = _SEPARATOR_RE.sub("", text)
    text = _SEPARATOR_TRAIL_RE.sub("", text)
    return text.strip()
