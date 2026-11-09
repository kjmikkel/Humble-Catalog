"""Serve the catalog viewer against a throwaway catalog of INVENTED
titles.

Point any visual check at this rather than the real catalog. A viewer
screenshot shows titles, counts, bundle names, ratings, tags and notes,
and no automated check reads pixels -- `leak_check.py` sees compressed
bytes and `check_no_data_tracked.py` filters paths -- so a screenshot of
the real library passes `verify` without complaint. See the Privacy
section of CLAUDE.md.

Every title here comes from docs/TEST-DATA.md. This file is tracked, so
`leak_check.py` scans it like any other committed text; that is the
point of keeping the demo data in the repo rather than in a scratch file.

    python scripts/demo_catalog.py

Serves on port 8099 -- deliberately not 8087, which `serve` uses and
`stop` targets.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _checkout_on_path():
    """Serve the checkout only when nothing else provides the package.

    This used to insert the checkout unconditionally, so the demo served
    the source tree even from a venv holding the installed wheel -- and
    the viewer smoke test (scripts/smoke_viewer.py, #114), which runs the
    demo to exercise what a user installs, would have passed on a wheel
    with no viewer in it (#107). The dev venv's editable install resolves
    to the checkout anyway, so day-to-day use is unchanged.
    """
    if importlib.util.find_spec("humble_catalog") is None:
        sys.path.insert(0, str(ROOT))


_checkout_on_path()

from humble_catalog import db                         # noqa: E402
from humble_catalog.titles import clean_game_title     # noqa: E402
from humble_catalog.webapp import create_app           # noqa: E402

PORT = 8099

# The date the demo's one game-library import claims to have run.
DEMO_IMPORTED_AT = "2026-01-01T00:00:00+00:00"

DEMO_BUNDLES = [
    ("bk1", "Humble Book Bundle: Test by Example Press", "2020-03-02"),
    ("au1", "Humble Audiobook Bundle: Epic Tales 2020 by Example Audio",
     "2021-06-14"),
    ("cm1", "Humble Comics Bundle: Shadow Hound", "2022-01-09"),
    ("gm1", "Humble Game Bundle: Samples", "2023-08-21"),
    ("kv1", "Humble Game Bundle: Key Vault", "2024-01-02"),
    ("ex1", "Humble Game Bundle: Expiring Keys", "2024-05-06"),
]

# An imported Steam library, so the Keys panel has a store it can check
# against. uplay is deliberately absent: a key for a store with no import
# is how a row reaches the "No importer" chip, and that distinction is
# the one the panel exists to draw.
#
# Every title is from docs/TEST-DATA.md.
DEMO_GAMES = [
    ("steam", "g3001", "Widget Quest"),
    ("steam", "g3002", "Neon Drifter"),
    ("steam", "g3003", "Starfall Rally"),
]

# One key per state the report can produce, because the panel's four
# chips and its three empty-state messages are all decided by this
# spread. States are derived, never stored -- keys.report classifies each
# row against DEMO_GAMES -- so what is seeded here is the evidence:
#   Widget Quest         in the library          -> matched (counted only)
#   Starfall Rally Turbo near Starfall Rally     -> uncertain
#   Cinder Vale          steam, no match         -> unredeemed, and hidden
#   Amber Hollow         live expiry_date        -> unredeemed, expiring
#   Glass Meridian       expiry_date long past   -> unredeemed, expired
#   Verdant Reach        uplay, never imported   -> uncheckable
DEMO_KEYS = [
    ("kv1", "widgetquest_steam", "Widget Quest", "steam", {}),
    ("kv1", "starfallturbo_steam", "Starfall Rally Turbo", "steam", {}),
    ("kv1", "cindervale_steam", "Cinder Vale", "steam", {}),
    ("kv1", "verdantreach_uplay", "Verdant Reach", "uplay", {}),
    ("ex1", "amberhollow_steam", "Amber Hollow", "steam",
     {"expiry_date": "2099-08-11T00:00:00"}),
    ("ex1", "glassmeridian_steam", "Glass Meridian", "steam",
     {"expiry_date": "2020-02-29T00:00:00"}),
]

# (gamekey, machine_name) of the one key the owner has marked resolved,
# so the Hidden chip is not permanently empty.
DEMO_HIDDEN = [("kv1", "cindervale_steam", "2026-07-31T00:00:00+00:00")]

# A spread chosen to light up the viewer's surfaces, not just one
# feature: every type, a same-type duplicate pair for the Duplicates
# panel, a low-confidence row for the Review panel, a pair of
# near-titles and an accented one for search, and enough
# ratings/tags/series that the columns are not all empty.
#
# Every title is from docs/TEST-DATA.md.
DEMO_ROWS = [
    # -- a same-type duplicate pair (Duplicates panel) ----------------
    {"mn": "widget_2e", "name": "Building Widget Services 2e",
     "type": "ebook", "bundle": "bk1", "publisher": "Example Press",
     "rating": 4, "genre": ["Programming"], "status": "matched"},
    {"mn": "widget_2nd", "name": "Building Widget Services, 2nd Edition",
     "type": "ebook", "bundle": "bk1", "publisher": "Example Press",
     "status": "matched"},
    # -- a low-confidence row (Review panel) --------------------------
    {"mn": "quiet_harbor", "name": "The Quiet Harbor: A Novel",
     "type": "ebook", "bundle": "bk1", "status": "low_confidence",
     "candidates": [
         {"source": "hardcover", "title": "The Quiet Harbor",
          "authors": ["Alex Penner"], "genre": "Fiction", "series": None,
          "series_number": None, "rating": 4.1, "narrator": None,
          "illustrator": None, "extra": {}, "confidence": 0.72}]},
    # -- search foils: a near-title, and an accent ---------------------
    {"mn": "quiet_life", "name": "A Quiet Life in Harbors", "type": "ebook",
     "bundle": "bk1", "status": "matched"},
    {"mn": "cafe_clocks", "name": "Café of Broken Clocks", "type": "ebook",
     "bundle": "bk1", "rating": 3, "status": "matched"},
    # -- a fully annotated row: rating, tag, note, read status ---------
    {"mn": "unrelated", "name": "Unrelated Book", "type": "ebook",
     "bundle": "bk1", "rating": 2, "tags": ["lent out"],
     "comment": "Borrowed by a friend.", "read_status": "read",
     "status": "matched"},
    # -- audiobooks, one with the full series/narrator set -------------
    {"mn": "axebearer", "name": "Axebearer (Grim & Fell)",
     "type": "audiobook", "bundle": "au1", "rating": 5,
     "genre": ["Fantasy"], "series": "The Elder Realm", "series_number": 1,
     "authors": ["Alex Penner"], "narrator": "Sam Reader",
     "read_status": "read", "status": "matched"},
    {"mn": "starless_war", "name": "The Starless War", "type": "audiobook",
     "bundle": "au1", "genre": ["Science Fiction"],
     "read_status": "reading", "status": "matched"},
    # -- comics, one with an illustrator ------------------------------
    {"mn": "shadowhound_v1", "name": "Shadow Hound Vol 1", "type": "comic",
     "bundle": "cm1", "publisher": "Example Comics", "genre": ["Manga"],
     "authors": ["Bo Writer"], "illustrator": "Alex Artist",
     "read_status": "want_to_read", "status": "matched"},
    {"mn": "moonfall_v1", "name": "MOONFALL, Vol. 1", "type": "comic",
     "bundle": "cm1", "status": "matched"},
    # -- android and music --------------------------------------------
    {"mn": "cooltower_android", "name": "Cool Tower Defense",
     "type": "android", "bundle": "gm1", "publisher": "Indie Dev Co",
     "status": "matched"},
    {"mn": "cooltower_ost", "name": "Sample Game OST", "type": "music",
     "bundle": "gm1", "status": "matched"},
    {"mn": "some_album", "name": "Some Album", "type": "music",
     "bundle": "gm1", "status": "matched"},
]


# Each row's cover shape as (width, height), for make_demo_covers.py.
# A spread for the layout: tall books and comics, square audiobooks and
# albums, one wide banner (the floated cover's hardest case), and three
# rows with no cover at all, so the coverless card and the "No cover"
# filter stay visible. Merged into DEMO_ROWS as each row's `cover`.
DEMO_COVERS = {
    "widget_2e": (2, 3), "widget_2nd": (2, 3), "quiet_harbor": (2, 3),
    "quiet_life": (2, 3), "cafe_clocks": (2, 3),
    "axebearer": (1, 1), "starless_war": (1, 1),
    "shadowhound_v1": (2, 3),
    "cooltower_android": (16, 9),
    "some_album": (1, 1),
    # no cover: unrelated, moonfall_v1, cooltower_ost
}
for _row in DEMO_ROWS:
    if _row["mn"] in DEMO_COVERS:
        _row["cover"] = DEMO_COVERS[_row["mn"]]

# The committed covers (see make_demo_covers.py). Served read-only as the
# demo's covers_dir; never the real covers/.
COVERS_DIR = Path(__file__).resolve().parent / "demo_covers"


def seed(db_path):
    """Build a demo catalog at `db_path`, replacing any existing rows.

    Rerunnable: main() reuses one temp path, so a second run must not
    trip the machine_name UNIQUE constraint.
    """
    conn = db.connect(db_path)
    # Child-first, so foreign keys stay satisfied while emptying.
    for table in ("item_bundles", "enrichment", "items", "hidden_keys",
                  "external_keys", "games", "game_imports", "bundles"):
        conn.execute(f"DELETE FROM {table}")
    for gamekey, name, purchased in DEMO_BUNDLES:
        conn.execute(
            "INSERT INTO bundles (gamekey, name, url, purchased_at) "
            "VALUES (?,?,?,?)",
            (gamekey, name, f"https://example.invalid/{gamekey}", purchased))
    for row in DEMO_ROWS:
        cur = conn.execute(
            "INSERT INTO items (machine_name, name, type, publisher, "
            "my_rating, user_tags, user_comment, read_status, cover_path) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (row["mn"], row["name"], row["type"], row.get("publisher"),
             row.get("rating"), db.tags_to_json(row.get("tags")),
             row.get("comment"), row.get("read_status", "unread"),
             # The viewer draws /<cover_path> and serves /covers/<file>
             # from covers_dir, so the prefix is covers/ whatever folder
             # the files actually sit in.
             f"covers/{row['mn']}.svg" if row.get("cover") else None))
        item_id = cur.lastrowid
        conn.execute("INSERT INTO item_bundles (item_id, gamekey) VALUES (?,?)",
                     (item_id, row["bundle"]))
        conn.execute(
            "INSERT INTO enrichment (item_id, genre, series, series_number, "
            "authors, narrator, illustrator, status, candidates) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            # narrator and illustrator are in db.TAG_FIELDS, so they are
            # JSON arrays like genre and authors -- not the plain TEXT
            # their singular names suggest. tags_to_json wraps a bare
            # string as a one-entry list.
            (item_id, db.tags_to_json(row.get("genre")), row.get("series"),
             row.get("series_number"), db.tags_to_json(row.get("authors")),
             db.tags_to_json(row.get("narrator")),
             db.tags_to_json(row.get("illustrator")),
             row.get("status", "matched"),
             json.dumps(row["candidates"]) if row.get("candidates") else None))
    for store, store_id, title in DEMO_GAMES:
        conn.execute(
            "INSERT INTO games (store, store_id, title, normalized_title, "
            "imported_at, source_timestamp) VALUES (?,?,?,?,?,?)",
            (store, store_id, title, clean_game_title(title),
             DEMO_IMPORTED_AT, None))
    conn.execute(
        "INSERT INTO game_imports (store, imported_at, count, source) "
        "VALUES (?,?,?,?)",
        ("steam", DEMO_IMPORTED_AT, len(DEMO_GAMES), "demo"))
    for gamekey, machine_name, human_name, key_type, raw in DEMO_KEYS:
        conn.execute(
            "INSERT INTO external_keys (gamekey, machine_name, human_name, "
            "key_type, raw) VALUES (?,?,?,?,?)",
            (gamekey, machine_name, human_name, key_type, json.dumps(raw)))
    for gamekey, machine_name, hidden_at in DEMO_HIDDEN:
        conn.execute(
            "INSERT INTO hidden_keys (gamekey, machine_name, hidden_at) "
            "VALUES (?,?,?)", (gamekey, machine_name, hidden_at))
    conn.commit()
    conn.close()


def demo_db_path(base=None):
    """Where the demo catalog lives: <base>/humble-catalog-demo/catalog.db.

    Named catalog.db, in a folder of its own, because Tasks -> Run spawns
    the CLI, which has no --db flag and opens catalog.db in its working
    directory. The job runner works in the folder holding the viewer's
    database, so this is what keeps a demo job on the demo (#143). base
    defaults to the system temp directory: never beside the real
    catalog.db, and never inside the repo, where a stray copy would sit
    outside .gitignore's rules.
    """
    folder = Path(base or tempfile.gettempdir()) / "humble-catalog-demo"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_private(folder)
    return folder / "catalog.db"


def _check_private(folder):
    """Refuse a demo folder someone else could have prepared.

    On Linux and macOS the temp directory is shared, so the fixed name can
    already exist, made by another user. Jobs run in this folder and the
    viewer serves its catalog, so it must be ours and writable by no one
    else. Windows gives every user a temp directory of their own, and its
    permissions do not map onto these bits, so there is nothing to check.
    """
    if not hasattr(os, "getuid"):
        return
    st = folder.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        raise SystemExit(
            f"{folder} is not a private folder of yours (owner or "
            "permissions). Remove it, or move it aside, and run the demo "
            "again.")


def make_app(db_path):
    """The demo viewer, with every data directory pointed away from the
    real ones beside the repo's catalog.db.

    covers_dir is the committed invented covers, never the real covers/.
    backups_dir is backups/ beside the demo catalog -- where a backup job
    run from the demo writes -- never ./backups: the demo runs from the
    repo root, and the Tasks tab's restore picker would otherwise list the
    real snapshots, their dates and sizes in frame in any screenshot.
    """
    app = create_app(
        db_path=str(db_path), covers_dir=str(COVERS_DIR),
        backups_dir=str(Path(db_path).resolve().parent / "backups"))
    add_gallery(app)
    return app


GALLERY_JS = Path(__file__).resolve().parent / "demo_gallery.js"
GALLERY_THEMES = ("light", "dark")

# The gallery's own layout. Colours come only from the viewer's tokens, so
# each frame shows the components on the palette they really sit on.
GALLERY_CSS = """
<style>
  /* The viewer's body never scrolls (each section owns the viewport), so
     <main> becomes the gallery's scroller. */
  main { overflow-y: auto; }
  .gallery { padding: 1rem; display: grid; gap: 1.5rem;
             grid-template-columns: minmax(0, 1fr); }
  .gallery-group h2 { font-size: 1rem; margin: 0 0 .5rem; }
  .gallery-group { display: flex; flex-wrap: wrap; gap: 1rem; align-items: start; }
  .gallery-group h2 { flex-basis: 100%; }
  .gallery-state { margin: 0; padding: .5rem; border: 1px solid var(--border);
                   border-radius: 6px; max-width: 100%; }
  .gallery-state figcaption { color: var(--muted); font-size: .8rem; margin-bottom: .4rem; }
  .gallery-note { color: var(--muted); margin: 0; }
  .gallery-table { overflow-x: auto; max-width: 100%; }
  /* The sheet is position: fixed in the viewer; here it sits in the flow. */
  #edit-sheet.gallery-sheet { position: static; transform: none; max-height: none;
                              inset: auto; width: min(100%, 26rem); }
</style>
"""


def gallery_frame_html(index_html, theme):
    """The real index.html, pinned to `theme`, with the gallery appended.

    The pin runs after the page's own theme script, which reads the saved
    choice from localStorage: both frames share one origin and so one
    saved theme, and would otherwise draw the same palette twice.
    """
    if theme not in GALLERY_THEMES:
        raise ValueError(theme)
    pin = (f'<script>document.documentElement.dataset.theme = "{theme}";'
           f'</script>{GALLERY_CSS}</head>')
    html = index_html.replace("</head>", pin, 1)
    return html.replace(
        "</body>", '<script src="/dev/gallery.js"></script>\n</body>', 1)


GALLERY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Component gallery (demo)</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #888; }
  /* Side by side only when each frame clears the viewer's 600 px phone
     breakpoint: below it the table and its editor are not drawn at all.
     Narrower windows stack the two frames. */
  .frames { display: grid; gap: 4px;
            grid-template-columns: repeat(auto-fit, minmax(min(100%, 44rem), 1fr)); }
  iframe { border: 0; width: 100%; height: 100vh; }
</style>
</head>
<body>
<div class="frames">
  <iframe src="/dev/gallery/frame?theme=light" title="Gallery, light theme"></iframe>
  <iframe src="/dev/gallery/frame?theme=dark" title="Gallery, dark theme"></iframe>
</div>
</body>
</html>
"""


def add_gallery(app):
    """/dev/gallery: every component in its states, light and dark side by
    side (#153). Demo-only: registered here, never by create_app, so
    neither `serve` nor the LAN viewer has it, and its script lives in
    scripts/, outside the wheel.
    """
    from flask import Response, abort, request, send_file

    @app.get("/dev/gallery")
    def gallery():
        return Response(GALLERY_PAGE, mimetype="text/html")

    @app.get("/dev/gallery/frame")
    def gallery_frame():
        theme = request.args.get("theme", "light")
        if theme not in GALLERY_THEMES:
            abort(404)
        index = Path(app.static_folder, "index.html").read_text(encoding="utf-8")
        return Response(gallery_frame_html(index, theme), mimetype="text/html")

    @app.get("/dev/gallery.js")
    def gallery_js():
        return send_file(GALLERY_JS, mimetype="text/javascript")


def main():
    # A fixed folder inside the system temp directory: stable enough to
    # reopen between runs. See demo_db_path for why the file is catalog.db.
    db_path = demo_db_path()
    seed(db_path)
    print(f"Demo catalog: {db_path}")
    print(f"Serving {len(DEMO_ROWS)} invented items and "
          f"{len(DEMO_KEYS)} invented keys on "
          f"http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    make_app(db_path).run(host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
