"""Turn a Markdown document into Telegraph's node tree.

Telegraph supports a fixed node set — `a`, `aside`, `b`, `blockquote`, `br`,
`code`, `em`, `figcaption`, `figure`, `h3`, `h4`, `hr`, `i`, `iframe`, `img`,
`li`, `ol`, `p`, `pre`, `s`, `strong`, `u`, `ul`, `video` — and only the `href`
and `src` attributes. Anything Markdown can express beyond that set is degraded
to the nearest representation that keeps its information, because a caller who
sees "published" must be able to trust the content survived. See ADR 3.

The mapping, one row per degradation path, each individually tested:

===========================  =================================================
Markdown                     Telegraph page
===========================  =================================================
``h1``                       Promoted to the page title, not emitted
``h2``                       ``h3``
``h3``                       ``h4``
``h4``-``h6``                ``h4``
Table                        One ``pre`` block holding the rendered table
Footnote reference           Link to the footnote entry
Footnote definition          Link list appended at the end of the page
Task list item               ``☑`` / ``☐`` marker inside the ``li``
Raw HTML                     Escaped, emitted as literal text
``img`` alt text             ``em`` caption inside a ``figure``
===========================  =================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.footnote import footnote_plugin

Node = dict[str, Any]

HEADING_LEVELS: Final[dict[str, str]] = {
    "h2": "h3",
    "h3": "h4",
    "h4": "h4",
    "h5": "h4",
    "h6": "h4",
}

# Telegraph has no `h2`, so every heading deeper than `h3` lands on `h4`.
DEEP_HEADING_TAG: Final = "h4"
CHECKED_MARKER: Final = "☑"  # ☑
UNCHECKED_MARKER: Final = "☐"  # ☐
_TASK_MARKER_RE: Final = re.compile(r"^\[( |x|X)\]\s+")

# Inline token types that open a nested element and the tag each produces.
_INLINE_OPENERS: Final[dict[str, str]] = {
    "strong_open": "strong",
    "em_open": "em",
    "s_open": "s",
    "link_open": "a",
}

# Exactly the closers matching `_INLINE_OPENERS`. Enumerated rather than matched
# by a `_close` suffix so an unmatched closer from another plugin cannot pop a
# stack entry it never pushed.
_INLINE_CLOSERS: Final = frozenset(
    {"strong_close", "em_close", "s_close", "link_close"}
)

_BLOCK_CONTAINERS: Final[dict[str, str]] = {
    "paragraph_open": "p",
    "blockquote_open": "blockquote",
}


@dataclass(slots=True)
class ConversionResult:
    """A converted document: the page title plus its node tree."""

    title: str | None
    nodes: list[Node] = field(default_factory=list)


def serialize(nodes: Sequence[Node]) -> str:
    """Encode a node tree the way Telegraph's `content` field expects.

    Telegraph documents `content` as an array of nodes but accepts it as a JSON
    string in a form body. `ensure_ascii=False` matters: escaping non-ASCII would
    inflate the payload against the 64 KB limit for no benefit.
    """

    return json.dumps(list(nodes), ensure_ascii=False)


def _element(tag: str, **attrs: Any) -> Node:
    node: Node = {"tag": tag}
    if attrs:
        node["attrs"] = attrs
    node["children"] = []
    return node


def _children_of(node: Node) -> list[Any]:
    return node.setdefault("children", [])


def _append_text(nodes: list[Any], value: str) -> None:
    """Append text, merging into a neighbouring string to avoid a node per word."""

    if not value:
        return
    if nodes and isinstance(nodes[-1], str):
        nodes[-1] = nodes[-1] + value
        return
    nodes.append(value)


class _Converter:
    """Walks a markdown-it token stream and emits Telegraph nodes.

    Structure comes from a stack of open containers rather than from
    re-deriving parents after the fact: markdown-it emits balanced open/close
    token pairs, so pushing on open and popping on close keeps inline content
    attached to exactly the element it belongs to.
    """

    def __init__(self, tokens: Sequence[Token]) -> None:
        self._tokens = tokens
        self._stack: list[Node] = []
        self._root: list[Any] = []
        self._title: str | None = None
        self._footnotes: list[Node] = []
        self._in_footnote_block = False
        self._cursor = 0
        # Footnote definitions are collected during the walk; the label of the
        # most recent reference tells each definition which link to hang off.
        self._footnote_labels: list[str] = []

    # -- entry point --------------------------------------------------------

    def convert(self) -> ConversionResult:
        while self._cursor < len(self._tokens):
            token = self._tokens[self._cursor]
            jump = self._handle(token)
            self._cursor = jump if jump is not None else self._cursor + 1

        nodes = list(self._root)
        _unwrap_list_item_paragraphs(nodes)
        _apply_task_markers(nodes)
        if self._footnotes:
            nodes.append(_element("hr"))
            nodes.extend(self._footnotes)
        return ConversionResult(title=self._title, nodes=nodes)

    # -- helpers ------------------------------------------------------------

    def _current(self) -> list[Any]:
        """The child list new nodes are appended to."""

        if self._stack:
            return _children_of(self._stack[-1])
        return self._root if not self._in_footnote_block else []

    def _push(self, node: Node) -> None:
        self._current().append(node)
        self._stack.append(node)

    def _pop(self) -> None:
        if self._stack:
            self._stack.pop()

    # -- dispatch -----------------------------------------------------------

    def _handle(self, token: Token) -> int | None:
        """Handle one token. Returns a new cursor when it consumed a range."""

        kind = token.type

        if kind == "heading_open":
            return self._heading_open(token)
        if kind == "heading_close":
            self._pop()
            return None

        if kind in _BLOCK_CONTAINERS:
            self._push(_element(_BLOCK_CONTAINERS[kind]))
            return None
        if kind in {"paragraph_close", "blockquote_close"}:
            self._pop()
            return None

        if kind in {"bullet_list_open", "ordered_list_open"}:
            self._push(_element("ul" if kind.startswith("bullet") else "ol"))
            return None
        if kind in {"bullet_list_close", "ordered_list_close"}:
            self._pop()
            return None

        if kind == "list_item_open":
            self._push(_element("li"))
            return None
        if kind == "list_item_close":
            self._pop()
            return None

        if kind == "hr":
            self._current().append(_element("hr"))
            return None

        if kind in {"fence", "code_block"}:
            node = _element("pre")
            _append_text(_children_of(node), token.content.rstrip("\n"))
            self._current().append(node)
            return None

        if kind == "table_open":
            return self._table()
        if kind == "inline":
            self._inline(token)
            return None

        if kind == "html_block":
            # Markdown's escape hatch has no Telegraph equivalent, so it is shown
            # as literal text. Dropping it would silently lose a block the author
            # explicitly wrote.
            node = _element("p")
            _append_text(_children_of(node), _escape_html(token.content.rstrip("\n")))
            self._current().append(node)
            return None

        if kind == "footnote_block_open":
            self._in_footnote_block = True
            return None
        if kind == "footnote_block_close":
            self._in_footnote_block = False
            return None
        if kind == "footnote_open":
            return self._footnote()

        return None

    # -- headings -----------------------------------------------------------

    def _heading_open(self, token: Token) -> int | None:
        """A level-1 heading is the page title; it is not emitted as a node."""

        if token.tag == "h1":
            self._title = self._heading_text()
            return self._skip_heading()

        self._push(_element(HEADING_LEVELS.get(token.tag, DEEP_HEADING_TAG)))
        return None

    def _skip_heading(self) -> int:
        """Advance past the heading's inline token and its close."""

        index = self._cursor + 1
        while index < len(self._tokens) and self._tokens[index].type != "heading_close":
            index += 1
        return index + 1

    def _heading_text(self) -> str:
        index = self._cursor + 1
        while index < len(self._tokens) and self._tokens[index].type != "heading_close":
            token = self._tokens[index]
            if token.type == "inline":
                return _plain_text(token).strip()
            index += 1
        return ""

    # -- footnotes ----------------------------------------------------------

    def _footnote(self) -> int:
        """Collect a footnote definition into a trailing link list (ADR 3)."""

        label = self._footnote_labels.pop(0) if self._footnote_labels else ""
        index = self._cursor + 1
        parts: list[str] = []
        while index < len(self._tokens) and self._tokens[index].type != "footnote_close":
            token = self._tokens[index]
            if token.type == "inline":
                parts.append(_plain_text(token).strip())
            index += 1

        item = _element("li")
        children = _children_of(item)
        anchor = _element("a", href=f"#fn{label}")
        _append_text(_children_of(anchor), f"{label}.")
        children.append(anchor)
        _append_text(children, " " + " ".join(part for part in parts if part))

        container = _element("ul")
        _children_of(container).append(item)
        self._footnotes.append(container)
        return index

    # -- tables: flattened into a code block (ADR 3) ------------------------

    def _table(self) -> int:
        """Collect the whole table, then emit it as one preformatted block.

        Alignment is lost this way, but the cells survive — which is the point.
        `th`/`td` are self-closing opens; each cell's text is the `inline` token
        that follows it.
        """

        rows: list[list[str]] = []
        depth = 1
        index = self._cursor + 1
        current: list[str] | None = None

        while index < len(self._tokens) and depth > 0:
            token = self._tokens[index]
            if token.type == "table_open":
                depth += 1
            elif token.type == "table_close":
                depth -= 1
            elif token.type == "tr_open":
                current = []
            elif token.type == "tr_close":
                if current is not None:
                    rows.append(current)
                    current = None
            elif token.type == "inline" and current is not None:
                current.append(_plain_text(token).strip())
            index += 1

        node = _element("pre")
        _append_text(_children_of(node), _render_table(rows))
        self._current().append(node)
        return index

    # -- inlines ------------------------------------------------------------

    def _inline(self, token: Token) -> None:
        if token.children:
            for child in token.children:
                if child.type == "footnote_ref":
                    label = str((child.meta or {}).get("label", "") or "")
                    if label and label not in self._footnote_labels:
                        self._footnote_labels.append(label)
        _append_inline(self._current(), token)


def _append_inline(target: list[Any], token: Token) -> None:
    """Translate an inline token's children into the target child list."""

    if token.children is None:
        _append_text(target, token.content)
        return

    stack: list[Node] = []

    def sink() -> list[Any]:
        return _children_of(stack[-1]) if stack else target

    for child in token.children:
        kind = child.type

        if kind == "text":
            _append_text(sink(), child.content)
        elif kind == "code_inline":
            node = _element("code")
            _append_text(_children_of(node), child.content)
            sink().append(node)
        elif kind == "softbreak":
            _append_text(sink(), " ")
        elif kind == "hardbreak":
            sink().append(_element("br"))
        elif kind == "html_inline":
            _append_text(sink(), _escape_html(child.content))
        elif kind in _INLINE_OPENERS:
            node = _element(_INLINE_OPENERS[kind])
            if kind == "link_open":
                node["attrs"] = {"href": child.attrGet("href") or ""}
            sink().append(node)
            stack.append(node)
        elif kind == "image":
            _append_image(sink(), child)
        elif kind == "footnote_ref":
            label = str((child.meta or {}).get("label", "") or "")
            node = _element("a", href=f"#fn{label}")
            _append_text(_children_of(node), f"[{label}]")
            sink().append(node)
        elif kind in _INLINE_CLOSERS:
            if stack:
                stack.pop()
        elif child.content:
            _append_text(sink(), child.content)


def _append_image(target: list[Any], token: Token) -> None:
    """An image becomes a `figure`; Telegraph has no alt attribute (ADR 3)."""

    src = token.attrGet("src") or ""
    alt = _plain_text(token).strip()
    if not src:
        if alt:
            _append_text(target, alt)
        return
    figure = _element("figure")
    children = _children_of(figure)
    children.append(_element("img", src=src))
    if alt:
        caption = _element("em")
        _append_text(_children_of(caption), alt)
        children.append(caption)
    target.append(figure)


def _plain_text(token: Token) -> str:
    """The visible text of an inline token, with markup discarded."""

    if token.children is None:
        return token.content
    return "".join(
        child.content
        for child in token.children
        if child.type in {"text", "code_inline"}
    ) or token.content


def _escape_html(fragment: str) -> str:
    """Render raw HTML as literal text so nothing silently disappears."""

    return (
        fragment.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _render_table(rows: Sequence[Sequence[str]]) -> str:
    """Lay a table out as aligned monospace text."""

    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    widths = [
        max(len(row[col]) if col < len(row) else 0 for row in rows)
        for col in range(columns)
    ]

    def render_row(row: Sequence[str]) -> str:
        cells = [
            (row[col] if col < len(row) else "").ljust(widths[col])
            for col in range(columns)
        ]
        return "| " + " | ".join(cells).rstrip() + " |"

    lines = [render_row(rows[0])]
    lines.append("|" + "|".join("-" * (width + 2) for width in widths) + "|")
    lines.extend(render_row(row) for row in rows[1:])
    return "\n".join(lines)


def _unwrap_list_item_paragraphs(nodes: Sequence[Node]) -> None:
    """Promote a sole `<p>`'s children into its parent `<li>`.

    Markdown wraps list item text in a paragraph, but Telegraph nests inline
    content directly inside `li`. Only a lone paragraph is flattened — a list
    item holding both a paragraph and a nested list keeps the paragraph, so its
    structure survives.
    """

    for node in nodes:
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if not children:
            continue
        if node.get("tag") == "li" and len(children) == 1:
            only = children[0]
            if isinstance(only, dict) and only.get("tag") == "p":
                node["children"] = list(only.get("children", []))
        _unwrap_list_item_paragraphs(
            [child for child in node.get("children", []) if isinstance(child, dict)]
        )


def _apply_task_markers(nodes: Sequence[Node]) -> None:
    """Replace GFM task markers with checkbox characters (ADR 3).

    Telegraph has no task list. GFM does not tokenize the marker — the `[x]`
    arrives as ordinary text at the head of the list item — so it would publish
    literally and the fact that it was a checkbox would be lost.
    """

    for node in nodes:
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if not children:
            continue
        if node.get("tag") == "li":
            _mark_checkbox(children)
        _apply_task_markers([child for child in children if isinstance(child, dict)])


def _mark_checkbox(children: list[Any]) -> None:
    """Replace a leading `[x]`/`[ ]` in a list item's text with a checkbox."""

    index = 0
    while index < len(children):
        child = children[index]
        if isinstance(child, str):
            match = _TASK_MARKER_RE.match(child)
            if match:
                marker = (
                    CHECKED_MARKER
                    if match.group(1).lower() == "x"
                    else UNCHECKED_MARKER
                )
                children[index] = f"{marker} {child[match.end():]}"
            return
        if isinstance(child, dict):
            if child.get("tag") == "p":
                _mark_checkbox(_children_of(child))
                return
            # A leading element (emphasis, link) cannot hold the marker, so the
            # marker must already have been consumed as its own text node.
            return
        return


def convert_markdown(markdown: str) -> ConversionResult:
    """Convert a Markdown document into a Telegraph page body."""

    parser = MarkdownIt("gfm-like", {"linkify": False}).use(footnote_plugin)
    parser.enable("table")
    parser.enable("strikethrough")
    return _Converter(parser.parse(markdown)).convert()


def resolve_title(explicit: str | None, from_document: str | None) -> str:
    """Pick the page title: explicit argument, then document heading, then fail.

    There is deliberately no fallback to the document's opening line of prose. A
    title invented from prose looks like a title but is not one, and the caller
    would never learn that their heading had been ignored.
    """

    if explicit and explicit.strip():
        return explicit.strip()
    if from_document and from_document.strip():
        return from_document.strip()

    from .errors import MissingTitleError

    raise MissingTitleError()


__all__ = [
    "CHECKED_MARKER",
    "ConversionResult",
    "HEADING_LEVELS",
    "UNCHECKED_MARKER",
    "convert_markdown",
    "resolve_title",
    "serialize",
]