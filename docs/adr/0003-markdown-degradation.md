# 3. Markdown constructs Telegraph cannot represent are degraded, not dropped

Date: 2026-02-13

## Status

Accepted

## Context

Telegraph accepts a fixed set of node types: `a`, `aside`, `b`, `blockquote`,
`br`, `code`, `em`, `figcaption`, `figure`, `h3`, `h4`, `hr`, `i`, `iframe`,
`img`, `li`, `ol`, `p`, `pre`, `s`, `strong`, `u`, `ul`, `video`. Elements
outside that set — and any attributes other than `href` and `src` — do not
exist as far as Telegraph is concerned.

CommonMark and GFM both produce constructs with no direct equivalent: `h1` and
`h2`, tables, footnotes, task list items, and raw HTML.

Dropping these would be the worst available outcome. The caller sees a
successful publication and has no signal that the document they published is not
the document they wrote. Silent data loss in a publishing tool is a correctness
bug, not a rendering limitation.

## Decision

Every unsupported construct is mapped to the nearest supported representation
that preserves its information:

| Markdown                | Telegraph page                                               |
| ----------------------- | ------------------------------------------------------------ |
| `h1`                    | Promoted to the Page title; not emitted as a node            |
| `h2`                    | `h3`                                                         |
| `h3`                    | `h4`                                                         |
| `h4`–`h6`               | `h4`                                                         |
| Table                   | One `pre` code block containing the rendered table           |
| Footnote reference      | Link to a footnote entry                                     |
| Footnote definition     | Entry in a linked list appended at the end of the page       |
| Task list `- [x]` / `[ ]` | `☑` / `☐` textual markers within the `li`                  |
| Raw HTML                | Escaped and emitted as literal text                          |
| Image `alt` text        | `em` caption inside a `figure` (Telegraph has no `alt`)      |

No construct is dropped.

## Consequences

The mapping loses fidelity in specific, visible ways: table alignment is gone
once flattened into a code block, and deeply nested headings all collapse to
`h4`, so a `h2` and an `h5` become indistinguishable on the published page. Both
are acceptable because the text survives and a reader can still follow the
document — unlike the alternative, where the content simply is not there.

These paths are the most failure-prone code in the project and are unit-tested
individually, one test per row of the table above.