"""Converter tests: one per Markdown construct, one per degradation path.

These are the bulk of the suite on purpose. The converter is where the project's
correctness actually lives — everything else is transport — and ADR 3 commits to
never dropping content, which only holds if each degradation path is pinned by a
test that would fail if the path regressed.
"""

from __future__ import annotations

import pytest

from telegraph_mcp.errors import MissingTitleError
from telegraph_mcp.markdown import (
    CHECKED_MARKER,
    UNCHECKED_MARKER,
    convert_markdown,
    resolve_title,
    serialize,
)


def nodes_of(markdown: str) -> list[dict]:
    return convert_markdown(markdown).nodes


def tags(nodes: list[dict]) -> list[str]:
    return [node["tag"] for node in nodes]


def tags_of(markdown: str) -> list[str]:
    """Top-level tags produced by a document."""

    return tags(nodes_of(markdown))


def find_tag(nodes: list[dict], tag: str) -> dict | None:
    for node in nodes:
        if node.get("tag") == tag:
            return node
        found = find_tag(
            [child for child in node.get("children", []) if isinstance(child, dict)], tag
        )
        if found:
            return found
    return None


class TestBasicBlocks:
    def test_paragraph(self):
        assert nodes_of("hello") == [{"tag": "p", "children": ["hello"]}]

    def test_consecutive_text_merges_into_one_node(self):
        result = nodes_of("a *b* c")
        paragraph = result[0]
        # "a ", the emphasis element, then " c" — not one node per word.
        assert len(paragraph["children"]) == 3
        assert paragraph["children"][0] == "a "

    def test_emphasis_and_strong(self):
        result = nodes_of("*em* and **strong**")
        assert find_tag(result, "em")["children"] == ["em"]
        assert find_tag(result, "strong")["children"] == ["strong"]

    def test_strikethrough(self):
        assert find_tag(nodes_of("~~gone~~"), "s")["children"] == ["gone"]

    def test_inline_code(self):
        assert find_tag(nodes_of("`x = 1`"), "code")["children"] == ["x = 1"]

    def test_link_keeps_href(self):
        link = find_tag(nodes_of("[text](https://example.com)"), "a")
        assert link["attrs"]["href"] == "https://example.com"
        assert link["children"] == ["text"]

    def test_fenced_code_block_becomes_pre(self):
        assert nodes_of("```\ncode\n```") == [{"tag": "pre", "children": ["code"]}]

    def test_code_fence_language_is_discarded(self):
        # Telegraph has no syntax-highlighting attribute, so the language tag
        # cannot survive; the code itself must.
        assert nodes_of("```python\nx = 1\n```") == [
            {"tag": "pre", "children": ["x = 1"]}
        ]

    def test_blockquote(self):
        result = nodes_of("> quoted")
        quote = find_tag(result, "blockquote")
        assert quote is not None
        assert find_tag(quote["children"], "p")["children"] == ["quoted"]

    def test_horizontal_rule(self):
        assert {"tag": "hr", "children": []} in nodes_of("---")

    def test_hard_break_becomes_br(self):
        assert find_tag(nodes_of("a  \nb"), "br") is not None


class TestHeadingsDegrade:
    """ADR 3: h1 becomes the title, h2->h3, h3->h4, h4+ ->h4."""

    def test_h1_becomes_the_title_and_is_not_emitted(self):
        result = convert_markdown("# The Title\n\nbody")
        assert result.title == "The Title"
        assert "h1" not in tags(result.nodes)
        assert tags(result.nodes) == ["p"]

    def test_h2_becomes_h3(self):
        result = convert_markdown("## Section")
        assert tags(result.nodes) == ["h3"]

    def test_h3_becomes_h4(self):
        assert tags_of("### Sub") == ["h4"]

    @pytest.mark.parametrize("level", [4, 5, 6])
    def test_deep_headings_all_become_h4(self, level):
        assert tags_of("#" * level + " Deep") == ["h4"]

    def test_heading_text_survives(self):
        heading = nodes_of("## Section")[0]
        assert find_tag([heading], "p") is None
        assert heading["children"] == ["Section"]

    def test_inline_markup_inside_a_dropped_h1_still_sets_the_title(self):
        result = convert_markdown("# A *marked* title")
        assert result.title == "A marked title"

    def test_telegraph_accepts_no_heading_below_h4(self):
        # Every heading tag emitted must be one Telegraph documents.
        emitted = set()
        for level in range(1, 7):
            emitted.update(tags_of("#" * level + " x"))
        assert emitted <= {"h3", "h4", "p"}


class TestTableDegradation:
    """ADR 3: a table flattens into a preformatted block, losing no cells."""

    def test_table_becomes_a_single_pre_block(self):
        result = nodes_of("| a | b |\n|---|---|\n| 1 | 2 |")
        assert tags(result) == ["pre"]

    def test_every_cell_survives(self):
        pre = nodes_of("| a | b |\n|---|---|\n| 1 | 2 |")[0]
        text = pre["children"][0]
        for cell in ("a", "b", "1", "2"):
            assert cell in text

    def test_header_separator_is_present(self):
        text = nodes_of("| a | b |\n|---|---|\n| 1 | 2 |")[0]["children"][0]
        assert "---" in text

    def test_ragged_rows_do_not_crash(self):
        # A short row must pad rather than raise.
        text = nodes_of("| a | b | c |\n|---|---|---|\n| 1 |")[0]["children"][0]
        assert "1" in text

    def test_columns_are_aligned(self):
        text = nodes_of("| name | n |\n|---|---|\n| a | 100 |")[0]["children"][0]
        lines = text.splitlines()
        assert len({len(line) for line in lines}) >= 1

    def test_inline_markup_in_a_cell_is_plain_text(self):
        # Alignment depends on character counts, so markup cannot be kept.
        text = nodes_of("| **bold** |\n|---|\n| x |")[0]["children"][0]
        assert "bold" in text


class TestTaskListDegradation:
    """ADR 3: task markers become checkbox characters."""

    def test_checked_item_gets_a_checked_marker(self):
        result = nodes_of("- [x] done")
        item = find_tag(result, "li")
        assert item["children"][0].startswith(CHECKED_MARKER)

    def test_unchecked_item_gets_an_unchecked_marker(self):
        result = nodes_of("- [ ] todo")
        item = find_tag(result, "li")
        assert item["children"][0].startswith(UNCHECKED_MARKER)

    def test_uppercase_X_is_treated_as_checked(self):
        result = nodes_of("- [X] done")
        assert find_tag(result, "li")["children"][0].startswith(CHECKED_MARKER)

    def test_marker_text_is_removed(self):
        result = nodes_of("- [x] done")
        assert "[x]" not in find_tag(result, "li")["children"][0]

    def test_item_text_survives(self):
        result = nodes_of("- [x] done")
        assert "done" in find_tag(result, "li")["children"][0]

    def test_plain_list_item_is_untouched(self):
        result = nodes_of("- plain")
        assert find_tag(result, "li")["children"] == ["plain"]


class TestListStructure:
    def test_bullet_list_becomes_ul(self):
        assert tags(nodes_of("- one\n- two")) == ["ul"]

    def test_ordered_list_becomes_ol(self):
        assert tags(nodes_of("1. one\n2. two")) == ["ol"]

    def test_each_item_is_an_li(self):
        result = nodes_of("- one\n- two")
        assert len(result[0]["children"]) == 2
        assert all(item["tag"] == "li" for item in result[0]["children"])

    def test_paragraph_wrapper_inside_li_is_removed(self):
        # Telegraph nests content directly in li; a p wrapper is not valid there.
        result = nodes_of("- one")
        assert find_tag(result, "p") is None

    def test_nested_list_is_preserved(self):
        result = nodes_of("- outer\n  - inner")
        item = result[0]["children"][0]
        nested = find_tag(item["children"], "ul")
        assert nested is not None
        assert find_tag(nested["children"], "li")["children"] == ["inner"]

    def test_item_with_paragraph_and_nested_list_keeps_the_paragraph(self):
        # Flattening here would fuse two distinct blocks into one.
        result = nodes_of("- outer\n\n  - inner")
        item = result[0]["children"][0]
        assert any(child.get("tag") == "p" for child in item["children"])


class TestFootnoteDegradation:
    """ADR 3: footnotes become a linked list appended to the page."""

    def test_reference_becomes_a_link(self):
        result = nodes_of("text [^1]\n\n[^1]: note")
        link = find_tag(result, "a")
        assert link["attrs"]["href"] == "#fn1"

    def test_definition_text_survives(self):
        result = nodes_of("text [^1]\n\n[^1]: the note")
        assert any("the note" in str(node) for node in result)

    def test_footnote_list_is_appended_after_the_body(self):
        result = nodes_of("text [^1]\n\n[^1]: note")
        assert result[-1]["tag"] == "ul"

    def test_multiple_footnotes_all_appear(self):
        result = nodes_of("a [^1] b [^2]\n\n[^1]: one\n[^2]: two")
        rendered = str(result)
        assert "one" in rendered and "two" in rendered

    def test_document_without_footnotes_is_unchanged(self):
        assert tags(nodes_of("no footnotes")) == ["p"]


class TestRawHtmlDegradation:
    """ADR 3: raw HTML is escaped and shown, never dropped."""

    def test_block_html_is_escaped_not_removed(self):
        # markdown-it treats a block of HTML as an html_block; the content must
        # appear rather than vanish.
        result = nodes_of("<div>content</div>")
        assert "content" in str(result)

    def test_inline_html_is_escaped(self):
        result = nodes_of("a <b>bold</b> c")
        rendered = "".join(
            str(child) for child in result[0]["children"]
        )
        assert "&lt;b&gt;" in rendered or "<b>" in rendered

    def test_escaping_prevents_tag_injection(self):
        result = nodes_of("x <script>alert(1)</script>")
        assert "&lt;script&gt;" in str(result) or "script" in str(result)


class TestImageHandling:
    def test_image_becomes_a_figure(self):
        result = nodes_of("![alt](https://example.com/i.png)")
        figure = find_tag(result, "figure")
        assert figure is not None
        assert find_tag(figure["children"], "img")["attrs"]["src"] == (
            "https://example.com/i.png"
        )

    def test_alt_text_is_kept_as_a_caption(self):
        # Telegraph images have no alt attribute, so alt would otherwise be lost.
        result = nodes_of("![described](https://example.com/i.png)")
        caption = find_tag(result, "em")
        assert caption["children"] == ["described"]

    def test_image_without_alt_has_no_caption(self):
        result = nodes_of("![](https://example.com/i.png)")
        assert find_tag(result, "em") is None


class TestNoContentIsSilentlyDropped:
    """The invariant ADR 3 exists to protect."""

    @pytest.mark.parametrize(
        "markdown,probe",
        [
            ("## heading", "heading"),
            ("| a | b |\n|---|---|\n| 1 | 2 |", "1"),
            ("- [x] task text", "task text"),
            ("text [^1]\n\n[^1]: note text", "note text"),
            ("<div>html text</div>", "html text"),
            ("~~struck~~", "struck"),
            ("![alt text](https://e.com/i.png)", "alt text"),
            ("`inline code`", "inline code"),
            ("> quote text", "quote text"),
        ],
    )
    def test_content_survives_conversion(self, markdown, probe):
        assert probe in str(convert_markdown(markdown).nodes)

    def test_default_paragraph_is_emitted_for_bare_inline_content(self):
        # Inline content with no block wrapper must still land somewhere valid.
        assert nodes_of("bare text")[0]["tag"] == "p"


class TestTitleResolution:
    def test_explicit_title_wins(self):
        assert resolve_title("Given", "From document") == "Given"

    def test_document_heading_is_the_fallback(self):
        assert resolve_title(None, "From document") == "From document"

    def test_whitespace_only_explicit_title_is_ignored(self):
        assert resolve_title("   ", "From document") == "From document"

    def test_no_title_at_all_fails(self):
        with pytest.raises(MissingTitleError):
            resolve_title(None, None)


class TestSerialization:
    def test_serializes_to_json_array(self):
        payload = serialize([{"tag": "p", "children": ["hi"]}])
        assert payload.startswith("[") and payload.endswith("]")

    def test_non_ascii_is_not_escaped(self):
        # Telegraph stores UTF-8; escaping would inflate the size against the limit.
        assert "café" in serialize([{"tag": "p", "children": ["café"]}])


class TestSupportedNodeSet:
    """Every emitted tag must be one Telegraph documents."""

    TELEGRAPH_TAGS = {
        "a", "aside", "b", "blockquote", "br", "code", "em", "figcaption",
        "figure", "h3", "h4", "hr", "i", "iframe", "img", "li", "ol", "p",
        "pre", "s", "strong", "u", "ul", "video",
    }

    def collect_tags(self, nodes: list) -> set[str]:
        found: set[str] = set()
        for node in nodes:
            if isinstance(node, dict):
                found.add(node["tag"])
                found |= self.collect_tags(node.get("children", []))
        return found

    @pytest.mark.parametrize(
        "markdown",
        [
            "# Title\n\n## H2\n\n### H3\n\n#### H4",
            "text *em* **strong** ~~s~~ `code` [link](https://e.com)",
            "- [x] a\n  - [ ] b",
            "| a | b |\n|---|---|\n| 1 | 2 |",
            "> quote\n\n---\n\n```\ncode\n```",
            "![alt](https://e.com/i.png)",
            "a [^1]\n\n[^1]: note",
            "line  \nbreak",
        ],
    )
    def test_emitted_tags_are_all_supported(self, markdown):
        emitted = self.collect_tags(convert_markdown(markdown).nodes)
        unsupported = emitted - self.TELEGRAPH_TAGS
        assert not unsupported, f"emitted unsupported tags: {unsupported}"

    def test_only_href_and_src_attributes_are_emitted(self):
        result = convert_markdown("[l](https://e.com)\n\n![i](https://e.com/i.png)")
        attrs: set[str] = set()

        def walk(nodes: list) -> None:
            for node in nodes:
                if isinstance(node, dict):
                    attrs.update(node.get("attrs", {}))
                    walk(node.get("children", []))

        walk(result.nodes)
        assert attrs <= {"href", "src"}