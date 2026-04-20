"""Escape decoding — the single transformation Tier 1 runs.

Decodes backslash escapes (\\n, \\t, \\r), HTML entities (&amp;, &#x2019;,
etc.), and URL percent-encoding. This is a *prerequisite* for all
downstream normalization — after escape decoding the raw bytes are
interpretable text; before it, rules would fire on the wrong characters.

Intentionally does NOT touch underscores, case, or whitespace collapsing.
The Tier 1 contract is: compound tokens survive this step verbatim.
"""

from __future__ import annotations

import html
import re
from urllib.parse import unquote


VERSION = "v1"

_BACKSLASH_MAP = {
    "\\n": "\n",
    "\\t": "\t",
    "\\r": "\r",
    "\\\\": "\\",
}
_BACKSLASH_PATTERN = re.compile(r"\\[nrt\\]")


def _decode_backslash(s: str) -> str:
    return _BACKSLASH_PATTERN.sub(lambda m: _BACKSLASH_MAP[m.group(0)], s)


def escape_decode(s: str) -> str:
    """Run the full escape-decoding chain.

    Order matters: percent-decode first so that encoded entities like
    %26amp%3B become &amp; and can be handled by the HTML entity pass.
    """
    if not s:
        return s
    try:
        s = unquote(s)
    except Exception:
        pass
    s = html.unescape(s)
    s = _decode_backslash(s)
    return s
