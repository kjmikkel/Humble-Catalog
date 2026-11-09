"""The phone card's control is a real button, with the links beside it (#149).

Kept apart from test_webapp_js.py so that work on separate issues does
not keep appending to the end of the same file, where any two open
branches conflict.
"""
import json
import re
from pathlib import Path

from tests.js_harness import eval_js
from tests.test_webapp_js import _item

_STATIC = Path(__file__).resolve().parent.parent / "humble_catalog" / "webapp" / "static"

_LINKED = _item(id=7, name="Harbor Lights",
                bundles=[{"name": "Bundle One",
                          "url": "https://www.humblebundle.com/downloads?key=k1"}])


def _card(read_only=False, mark="() => ''"):
    return eval_js("""(() => {
      app.setReadOnly(%s);
      const html = app.renderCards([%s], %s);
      app.setReadOnly(false);
      return html;
    })()""" % (json.dumps(read_only), json.dumps(_LINKED), mark))


def test_the_card_itself_is_no_longer_a_button():
    # HTML-ARIA (A11Y-9): nothing interactive inside role=button, and the
    # card holds the bundle links.
    article = re.search(r"<article[^>]*>", _card()).group(0)
    assert "role=" not in article
    assert "tabindex" not in article
    assert "data-open" not in article


def test_the_title_is_the_button_and_holds_no_link():
    html = _card()
    button = re.search(r"<button[^>]*card-open[^>]*>(.*?)</button>", html, re.S)
    assert button, html
    assert 'aria-label="Edit Harbor Lights"' in button.group(0)
    assert 'data-open="7"' in button.group(0)
    assert "<a " not in button.group(1)
    # The link is still on the card, as a sibling of the button.
    assert 'class="card-link" href="https://www.humblebundle.com/downloads?key=k1"' in html


def test_a_revealed_card_marks_its_button_not_the_card():
    # showAllRows() focuses "#card-list [data-revealed]", which has to be
    # the focusable button now that the card is not a Tab stop.
    html = _card(mark="() => ' data-revealed tabindex=\"-1\"'")
    assert re.search(r"<button[^>]*card-open[^>]*data-revealed", html)
    assert "data-revealed" not in re.search(r"<article[^>]*>", html).group(0)


def test_the_lan_card_keeps_a_plain_title_and_the_row_marker():
    html = _card(read_only=True, mark="() => ' data-revealed tabindex=\"-1\"'")
    assert "<button" not in html
    assert '<strong class="card-title">' in html
    assert 'data-revealed tabindex="-1"' in re.search(r"<article[^>]*>", html).group(0)


def test_closing_the_sheet_returns_focus_to_the_cards_button():
    focused = eval_js("""(() => {
      dom.reset();
      app.setItems([%s]);
      app.openSheet(7);
      app.closeSheet();
      return dom.focusCalls.at(-1);
    })()""" % json.dumps(_LINKED))
    assert focused == {"selector": '.card-open[data-open="7"]', "preventScroll": True}


def test_the_links_sit_above_the_stretched_button():
    css = (_STATIC / "style.css").read_text(encoding="utf-8")
    assert ".card-open::after { content: \"\"; position: absolute; inset: 0;" in css
    assert ".card.tappable .card-link { position: relative; z-index: 1; }" in css
