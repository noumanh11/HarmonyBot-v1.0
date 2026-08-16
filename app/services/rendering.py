"""Markdown rendering with sanitisation.

The frontend assigns bot replies via ``innerHTML``. v1 piped raw model output
through ``markdown2`` straight into that, so any HTML the model emitted - a
``<script>`` tag echoed back from a prompt-injected page, say - executed in the
user's browser. Everything here is escaped first, then whitelisted.
"""

from __future__ import annotations

import bleach
import markdown2

_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "blockquote",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
}
_ALLOWED_ATTRS = {"a": ["href", "title", "rel", "target"]}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]


def render_markdown(text: str) -> str:
    """Convert Markdown to HTML that is safe to inject into the page."""
    html = markdown2.markdown(
        text,
        # safe_mode escapes any raw HTML the model produced before we parse it.
        safe_mode="escape",
        extras=["fenced-code-blocks", "tables", "break-on-newline"],
    )
    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Outbound links open safely rather than handing the opener to the target.
    return bleach.linkify(cleaned, callbacks=[_set_link_attrs], skip_tags=["pre", "code"])


def _set_link_attrs(attrs: dict, new: bool = False) -> dict:
    attrs[(None, "target")] = "_blank"
    attrs[(None, "rel")] = "noopener noreferrer nofollow"
    return attrs
