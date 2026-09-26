"""The demo catalog must stay loadable as the schema moves.

Titles are invented -- see docs/TEST-DATA.md. This file is what stops
scripts/demo_catalog.py rotting unnoticed between visual checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import demo_catalog                                    # noqa: E402
from humble_catalog import db                          # noqa: E402


def test_seed_builds_a_loadable_catalog(tmp_path):
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    items = db.fetch_items(db.connect(dbp))
    assert len(items) == len(demo_catalog.DEMO_ROWS)
    # fetch_items is what /api/items and the export both go through, so
    # loading cleanly is the property worth asserting.
    assert all(i["name"] and i["type"] for i in items)


def test_seed_covers_every_item_type(tmp_path):
    # The tool exists for visual checks in general, not one feature, so
    # a type missing here is a viewer surface nobody can eyeball.
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    types = {i["type"] for i in db.fetch_items(db.connect(dbp))}
    assert types == {"ebook", "audiobook", "comic", "music", "android"}


def test_seed_is_rerunnable(tmp_path):
    # main() reuses one temp path across runs; a second seed must not
    # trip the machine_name UNIQUE constraint.
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    demo_catalog.seed(dbp)
    assert len(db.fetch_items(db.connect(dbp))) == len(demo_catalog.DEMO_ROWS)


def test_every_row_lands_in_a_bundle(tmp_path):
    # An item in no bundle renders an empty Bundle cell, which is a
    # state worth being able to see deliberately rather than by accident.
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    assert all(i["bundles"] for i in db.fetch_items(db.connect(dbp)))


# ---- Demo keys -----------------------------------------------------------
# The Keys panel decides everything it shows -- four chips, three empty
# messages, the expiry column -- from state the report DERIVES rather
# than reads, so seeding a chip means seeding its evidence. Without rows
# here the panel only ever renders its "nothing fetched" branch, and no
# visual check of it means anything.
from humble_catalog import keys as keys_report         # noqa: E402


def _report(tmp_path):
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    return keys_report.report(db.connect(dbp))


def test_seed_covers_every_key_state(tmp_path):
    # A state with no row is a chip that cannot be eyeballed, which is
    # the same gap test_seed_covers_every_item_type closes for Library.
    counts = _report(tmp_path)["counts"]
    assert all(counts[state] for state in keys_report.STATES), counts


def test_the_uncheckable_row_comes_from_a_store_with_no_import(tmp_path):
    # "No importer" must not be faked with a state column: it is the
    # absence of a game_imports row, and seeding an uplay import would
    # silently empty that chip.
    report = _report(tmp_path)
    assert "uplay" not in report["libraries"]
    assert [r["product"] for r in report["rows"]
            if r["state"] == "uncheckable"] == ["Verdant Reach"]


def test_the_keys_spread_shows_a_hide_and_both_sides_of_an_expiry(tmp_path):
    # The Hidden chip, the "expired" cell and a live countdown are three
    # more surfaces that render only if some row carries them.
    rows = _report(tmp_path)["rows"]
    assert any(r["hidden_at"] for r in rows)
    assert any(r["expired"] for r in rows)
    assert any(r["expires"] and not r["expired"] for r in rows)


def test_the_uncertain_row_names_what_it_nearly_matched(tmp_path):
    # An uncertain row with no near_match would render the panel's
    # "~ title (score)" hint empty.
    near = [r["near_match"] for r in _report(tmp_path)["rows"]
            if r["state"] == "uncertain"]
    assert near and all(n and n["owned_title"] for n in near)


def test_seeding_keys_twice_does_not_trip_their_primary_keys(tmp_path):
    # external_keys is keyed on (gamekey, machine_name) and hidden_keys
    # on the same pair, so both need clearing before a reseed -- and
    # main() reseeds the same temp file on every run.
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    demo_catalog.seed(dbp)
    assert keys_report.report(db.connect(dbp))["total"] == len(
        demo_catalog.DEMO_KEYS)


# ---- Demo covers ---------------------------------------------------------
# Invented covers, committed as SVG so leak_check reads the titles inside
# them like any other tracked text (a PNG would be pixels only a person
# could review). They live in scripts/demo_covers/, never covers/, whose
# real contents check_no_data_tracked.py refuses.
import re                                              # noqa: E402

import make_demo_covers                                # noqa: E402
from humble_catalog.webapp import create_app           # noqa: E402

COVERS = make_demo_covers.OUT_DIR


def _size(svg_text):
    w = re.search(r'<svg[^>]*\swidth="(\d+)"', svg_text).group(1)
    h = re.search(r'<svg[^>]*\sheight="(\d+)"', svg_text).group(1)
    return int(w), int(h)


def test_every_named_cover_is_committed_at_its_ratio():
    covered = [r for r in demo_catalog.DEMO_ROWS if r.get("cover")]
    assert covered, "no demo row names a cover"
    for row in covered:
        w, h = _size((COVERS / f"{row['mn']}.svg").read_text(encoding="utf-8"))
        rw, rh = row["cover"]
        assert w * rh == h * rw, (row["mn"], (w, h), row["cover"])


def test_the_covers_span_portrait_square_and_landscape():
    # The point is to exercise the layout: a tall book, a square album
    # and one wide banner, which is the float's hardest case.
    shapes = {(1 if w > h else 0 if w == h else -1)
              for w, h in (r["cover"] for r in demo_catalog.DEMO_ROWS
                           if r.get("cover"))}
    assert shapes == {-1, 0, 1}


def test_some_rows_stay_coverless():
    # The coverless card and the "No cover" filter are states to see too.
    assert sum(1 for r in demo_catalog.DEMO_ROWS if not r.get("cover")) >= 2


def test_committed_covers_match_the_generator():
    # Regenerate with scripts/make_demo_covers.py after changing a row;
    # this fails until the committed files catch up, and flags strays.
    expected = make_demo_covers.render_all(demo_catalog.DEMO_ROWS)
    on_disk = {p.name: p.read_text(encoding="utf-8")
               for p in COVERS.glob("*.svg")}
    assert on_disk == expected


def test_seed_points_covered_rows_at_their_cover(tmp_path):
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    by_mn = {i["machine_name"]: i for i in db.fetch_items(db.connect(dbp))}
    for row in demo_catalog.DEMO_ROWS:
        want = f"covers/{row['mn']}.svg" if row.get("cover") else None
        assert by_mn[row["mn"]]["cover_path"] == want, row["mn"]


def test_the_viewer_serves_a_demo_cover(tmp_path):
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    row = next(r for r in demo_catalog.DEMO_ROWS if r.get("cover"))
    client = create_app(db_path=str(dbp), covers_dir=str(COVERS)).test_client()
    resp = client.get(f"/covers/{row['mn']}.svg")
    assert resp.status_code == 200
    assert resp.mimetype == "image/svg+xml"


def test_the_demo_never_lists_the_real_backups(tmp_path):
    # backups_dir defaults to ./backups, and the demo runs from the repo
    # root, where the real snapshots live. Their dates and sizes are
    # real-library metadata in any screenshot of the Tasks tab, which is
    # exactly what the demo exists to keep out of frame.
    dbp = tmp_path / "demo.db"
    demo_catalog.seed(dbp)
    app = demo_catalog.make_app(dbp)
    backups = Path(app.config["BACKUPS_DIR"]).resolve()
    repo = Path(__file__).resolve().parent.parent
    assert repo not in backups.parents and backups != repo
    assert app.test_client().get("/api/backups").get_json() == {"backups": []}


# -- Which humble_catalog the demo serves (#114) ------------------------
# The demo used to put the checkout first on sys.path unconditionally, so
# it served the source tree even from a venv holding the installed wheel.
# The viewer smoke test runs the demo precisely to exercise what a user
# installs, and would have passed on a wheel with no viewer in it (#107).

def test_the_checkout_is_added_when_nothing_else_provides_the_package(
        monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(demo_catalog.importlib.util, "find_spec",
                        lambda name: None)
    demo_catalog._checkout_on_path()
    assert sys.path[0] == str(demo_catalog.ROOT)


def test_an_installed_package_is_left_to_win(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = list(sys.path)
    monkeypatch.setattr(demo_catalog.importlib.util, "find_spec",
                        lambda name: object())
    demo_catalog._checkout_on_path()
    assert sys.path == before
