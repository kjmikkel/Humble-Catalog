"""The demo-only component gallery (#153): /dev/gallery on the demo viewer.

The gallery draws every component with the viewer's own renderers, so
what can rot is the wiring: the routes, the theme pin, and the names it
calls. Whether the page draws is checked in a real browser, by eye."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import demo_catalog                                    # noqa: E402
from humble_catalog.webapp import create_app           # noqa: E402

STATIC = ROOT / "humble_catalog" / "webapp" / "static"
GALLERY_JS = ROOT / "scripts" / "demo_gallery.js"


@pytest.fixture()
def client(tmp_path):
    dbp = tmp_path / "catalog.db"
    demo_catalog.seed(dbp)
    return demo_catalog.make_app(dbp).test_client()


def test_the_gallery_page_frames_both_themes(client):
    html = client.get("/dev/gallery").get_data(as_text=True)
    assert 'src="/dev/gallery/frame?theme=light"' in html
    assert 'src="/dev/gallery/frame?theme=dark"' in html


@pytest.mark.parametrize("theme", demo_catalog.GALLERY_THEMES)
def test_a_frame_is_the_real_viewer_pinned_to_its_theme(client, theme):
    html = client.get(f"/dev/gallery/frame?theme={theme}").get_data(as_text=True)
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    # The real page: every viewer script, in order, then the gallery last.
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts == re.findall(r'<script src="([^"]+)"', index) + ["/dev/gallery.js"]
    # The pin comes after the saved-theme script, or that would win: both
    # frames share one origin and so one saved theme.
    saved, pin = html.index('localStorage.getItem("hc-theme")'), \
        html.index(f'dataset.theme = "{theme}"')
    assert saved < pin < html.index("</head>")


def test_an_unknown_theme_is_not_served(client):
    assert client.get("/dev/gallery/frame?theme=sepia").status_code == 404
    with pytest.raises(ValueError):
        demo_catalog.gallery_frame_html("<head></head>", '"><script>')


def test_the_gallery_script_is_served(client):
    resp = client.get("/dev/gallery.js")
    assert resp.status_code == 200
    assert resp.mimetype == "text/javascript"
    # Bytes, not text: read_text folds a Windows checkout's CRLF to LF,
    # while send_file serves the file as it is on disk.
    assert resp.get_data() == GALLERY_JS.read_bytes()


def test_the_real_viewer_has_no_gallery(tmp_path):
    """Demo-only: `serve` and the LAN viewer never register it, and its
    script lives in scripts/, outside every package the wheel ships."""
    dbp = tmp_path / "catalog.db"
    demo_catalog.seed(dbp)
    client = create_app(db_path=str(dbp)).test_client()
    for path in ("/dev/gallery", "/dev/gallery/frame?theme=light", "/dev/gallery.js"):
        assert client.get(path).status_code == 404, path
    assert not (STATIC / "demo_gallery.js").exists()


# What the gallery calls or reassigns from the viewer's shared scope. A
# rename there would leave the gallery throwing in a browser while every
# other test passed, so each must still be defined at the top level of
# one of the viewer's scripts.
VIEWER_NAMES = [
    "items", "pending", "isNarrow", "openEditor", "editingId", "editingTags",
    "statusFilter", "syncStatusChips", "renderKeys", "liveBundles",
    "renderBrowse", "chipFilters", "renderFilterChips", "renderActiveFilters",
    "reportWriteError", "nameExtras", "stars", "tagBadges", "statusSelect",
    "READ_STATUS", "renderCards", "sheetFor", "esc", "$", "Autocomplete",
]


def _top_level_names():
    names = set()
    for js in STATIC.glob("*.js"):
        text = js.read_text(encoding="utf-8")
        names |= set(re.findall(r"^(?:async\s+)?function\s+([\w$]+)", text, re.M))
        for decl in re.findall(r"^(?:const|let|var)\s+([^=;]+)", text, re.M):
            names |= set(re.findall(r"[\w$]+", decl))
    return names


def test_every_viewer_name_the_gallery_uses_still_exists():
    missing = set(VIEWER_NAMES) - _top_level_names()
    assert not missing, f"renamed or removed from the viewer: {sorted(missing)}"


def test_the_list_above_covers_what_the_gallery_uses():
    """Non-vacuous: every listed name really is used by the gallery, and
    the renderers the issue asks for are among them."""
    source = GALLERY_JS.read_text(encoding="utf-8")
    # Not a property (x.items), but a spread (...READ_STATUS) counts.
    unused = [n for n in VIEWER_NAMES
              if not re.search(rf"(?<![\w$])(?<![^.]\.){re.escape(n)}(?![\w$])", source)]
    assert not unused, unused
    for renderer in ("stars", "sheetFor", "renderCards", "statusSelect",
                     "tagBadges", "nameExtras", "renderFilterChips"):
        assert f"{renderer}(" in source
