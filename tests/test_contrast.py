"""The viewer's colour tokens meet WCAG contrast in all four theme blocks.

style.css defines every colour twice per theme -- once under
prefers-color-scheme and once under the explicit [data-theme] override --
so a fix made to one copy alone would pass a browser check in one mode and
fail in the other. This reads the tokens straight from the file and checks
each pair the viewer actually draws (#147).
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parent.parent / "humble_catalog" / "webapp"
       / "static" / "style.css").read_text(encoding="utf-8")

# Where each block's declarations begin. The dark media block nests a
# :root, so it is found from the @media line.
BLOCKS = {
    "light (default)": r"^:root \{",
    "dark (system)": r"^@media \(prefers-color-scheme: dark\)",
    "light (chosen)": r'^:root\[data-theme="light"\]',
    "dark (chosen)": r'^:root\[data-theme="dark"\]',
}


def _tokens(name):
    start = re.search(BLOCKS[name], CSS, re.M).end()
    body = CSS[start:CSS.index("\n}", start)]
    raw = dict(re.findall(r"--([\w-]+):\s*([^;]+);", body))
    # One level of var() is all the file uses.
    return {k: raw[v[6:-1]] if v.startswith("var(--") else v.strip()
            for k, v in raw.items()}


def _luminance(hex_):
    rgb = [int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
           for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _expand(hex_):
    h = hex_.lstrip("#")
    return "#" + "".join(c * 2 for c in h) if len(h) == 3 else hex_


# (foreground, background, minimum, what it is). Literal colours are
# written as such; everything else is a token name.
PAIRS = [
    ("star", "surface", 3, "lit star on a row"),
    ("star", "surface-alt", 3, "lit star on a striped row"),
    ("star-off", "surface", 3, "unlit star on a row"),
    ("star-off", "surface-alt", 3, "unlit star on a striped row"),
    ("#fff", "badge-danger", 4.5, "review badge / armed button text"),
    ("badge-info-fg", "badge-info", 4.5, "edited / edition badge text"),
    ("bg", "muted", 4.5, "queued badge text"),
    ("danger", "surface", 4.5, "error text on a panel"),
    ("danger", "bg", 4.5, "error text on the page"),
]


@pytest.mark.parametrize("block", BLOCKS)
@pytest.mark.parametrize("fg,bg,minimum,what", PAIRS)
def test_drawn_colour_pairs_meet_wcag_contrast(block, fg, bg, minimum, what):
    t = _tokens(block)
    colour = lambda c: _expand(c if c.startswith("#") else t[c])  # noqa: E731
    ratio = _ratio(colour(fg), colour(bg))
    assert ratio >= minimum, f"{what} in {block}: {ratio:.2f}:1 < {minimum}:1"
