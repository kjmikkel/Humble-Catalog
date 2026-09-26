import base64
import binascii
import datetime as dt
import hmac
import http.client
import io
import json
import re
import shutil
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path
import requests
from flask import (Flask, Response, current_app, g, jsonify, request,
                   send_from_directory)
from werkzeug.serving import WSGIRequestHandler, make_server
from humble_catalog import (bundle_preview, choice_preview, db, dedupe,
                            editions, export, handoff, humble_api, jobs, keys,
                            stats, url_import)
from humble_catalog.enrich import EDITABLE_FIELDS, apply_candidate
from humble_catalog.sources.base import candidate

# The only authorities the viewer answers to. Everything here is served
# on 127.0.0.1, so any other name means the request was addressed
# somewhere else and merely arrived here -- which is exactly what DNS
# rebinding looks like: a page on evil.com whose name is re-pointed at
# 127.0.0.1 becomes same-origin with the viewer, and same-origin policy
# stops protecting the catalog. The browser keeps sending Host: evil.com,
# so refusing unknown hosts closes it.
LOOPBACK_AUTHORITIES = frozenset({"127.0.0.1", "localhost", "[::1]"})

# Large enough for any ratings workbook, small enough that a request
# cannot spend the machine's memory. The body is base64, so the encoded
# form is ~4/3 of this; the cap is checked on the DECODED bytes.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def host_is_loopback(host_header):
    """True when the Host header addresses this machine by a loopback name.

    The port is deliberately not checked. The security property comes from
    the *name*: a browser sets Host from the URL it was given and a page
    cannot forge it cross-origin, so an attacker cannot present a loopback
    name they do not already control. Pinning the port would add no defence
    and would break a legitimate `serve --port` or HUMBLE_PORT override.
    """
    if not host_header:
        # HTTP/1.1 requires Host. Absent, there is nothing to validate, so
        # fail closed rather than guess.
        return False
    authority = host_header.strip().lower()
    if authority.startswith("["):        # IPv6 literal: [::1] or [::1]:8087
        name = authority.partition("]")[0] + "]"
    else:
        name = authority.partition(":")[0]
    return name in LOOPBACK_AUTHORITIES


def _sorted_candidates(raw):
    # Single source of truth for candidate ordering: /api/review presents
    # this order and /choose receives an index into it, so both must sort
    # identically (stable sort keeps stored order on confidence ties).
    cands = json.loads(raw or "[]")
    cands.sort(key=lambda c: c.get("confidence", 0), reverse=True)
    return cands

def _json_object_or_none():
    """The request's JSON body when it is an object, else None.

    For a route that reads no field but must still refuse a malformed
    request before doing any work (`/api/choice-preview`, issue #20).
    `_json_object` cannot answer that: it folds every non-object into
    `{}`, which is exactly the body a legitimate caller sends.
    """
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _json_object():
    """The request's JSON body when it is an object, else an empty dict.

    Every route reads its body through here or through
    `_json_object_or_none`, which this wraps, so no route can disagree
    with another about what a usable one is. `grep -n "get_json"` over
    this file returns exactly one site, which is in that helper.

    `or {}` was the idiom here and is NOT a type check: it substitutes the
    default only for a FALSY body, so `{}` and `null` were handled while a
    non-empty JSON array or string sailed through and then had no `.get`.
    Nineteen of the twenty-four POST routes answered 500 that way. Every
    route already validates the FIELD it reads, so handing them an empty
    dict turns each of those into that route's own 400.

    `silent=True` folds malformed JSON in as well, so a bad body earns the
    same JSON error object as every other refusal rather than Werkzeug's
    HTML 400 page, which the viewer's JS cannot parse.
    """
    body = _json_object_or_none()
    return {} if body is None else body


def _text_field(data, key):
    """A named field as a stripped string, or None when it cannot be one.

    The field-level counterpart of `_json_object`, and the same mistake
    one level down: `(data.get("x") or "").strip()` reads as a default
    and is not a type check, so a number survived `or ""` and then had no
    `.strip`. Six routes answered 500 that way.

    Absent, non-string and blank-after-stripping all answer None, because
    every caller treats the three identically - none of them can act on a
    tag name that is not a name - and folding them here keeps that
    decision in one place rather than in six.
    """
    value = data.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _url_from_body():
    """The `url` field of the request's JSON body, or None.

    Shared by the two routes that take a URL. A `url` that is not a string
    is a wrong value rather than a wrong shape, and answers None so the
    caller returns 400 instead of failing on `.strip`.
    """
    url = _json_object().get("url")
    return url.strip() if isinstance(url, str) else None

def _conn():
    """The request's catalog connection, opened on first use.

    Module-level rather than a closure inside create_app, so the read and
    write route groups -- registered by separate functions, and on two
    different apps -- share one definition of "the connection".
    """
    if "conn" not in g:
        g.conn = db.connect(current_app.config["DB_PATH"])
    return g.conn


def _new_app(db_path, covers_dir, read_only):
    """A bare app: config and connection teardown, no routes, no guards."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["DB_PATH"] = db_path
    app.config["COVERS_DIR"] = Path(covers_dir).resolve()
    app.config["READ_ONLY"] = read_only

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    return app


def _register_read_routes(app):
    """The routes a read-only viewer needs, and nothing else.

    This is the whole of what the LAN app serves (create_lan_app), so a
    route belongs here only if it reads and a paired phone should reach
    it. The maintenance reads (/api/review, /api/duplicates) are
    deliberately NOT here: they are only useful beside the writes they
    feed. test_lan_app_serves_only_the_pinned_read_routes pins this list.
    """
    conn = _conn
    covers = app.config["COVERS_DIR"]
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/covers/<path:filename>")
    def cover(filename):
        return send_from_directory(covers, filename)

    @app.get("/api/items")
    def items():
        rows = db.fetch_items(conn())
        # Attached HERE and not in fetch_items, which is shared with CSV
        # and XLSX export: an edition link is a derived view, while the
        # export stays a serialization of what the catalog stores. One
        # O(n) pass over the payload, no per-item query.
        #
        # The key is absent rather than [] for the rows with no sibling,
        # which is nearly all of them on a real catalog.
        by_id = {i["id"]: i for i in rows}
        for group in editions.find_groups(conn()):
            for iid in group:
                by_id[iid]["editions"] = [
                    {"id": o, "type": by_id[o]["type"], "name": by_id[o]["name"]}
                    for o in group if o != iid]
        return jsonify({"items": rows})

    @app.get("/api/stats")
    def catalog_stats():
        # A reshaping of stats.report, never a second count: the CLI and
        # this route must not be able to disagree. GET with no parameters
        # -- the report is always the whole catalog, so there is nothing
        # to pass, and nothing about the library reaches a query string.
        #
        # The viewer does not read this. Its statistics panel counts the
        # visible rows in stats.js (see the Statistics panel comment in
        # catalog.js), and a whole-catalog count could not answer a
        # filtered table. Kept as a documented read API: it is what the
        # parity tests and the read-route probes assert against, and a
        # LAN client gets the same report the CLI prints.
        sections, total = stats.report(db.fetch_items(conn()))
        return jsonify({
            "total": total,
            "sections": [
                {"key": key, "label": label,
                 "rows": [{"label": row_label, "count": count}
                          for row_label, count in rows]}
                for key, label, rows in sections]})

    @app.get("/api/keys")
    def key_report():
        # The same shape keys.report returns, jsonified and nothing more:
        # the CLI and this panel must not be able to disagree, which is the
        # rule /api/stats follows. GET with no parameters -- the report is
        # always the whole key set, so there is nothing to pass, and
        # nothing about the library reaches a query string.
        return jsonify(keys.report(conn()))

    @app.get("/api/status")
    def status():
        rows = conn().execute("SELECT * FROM run_status WHERE phase != 'done'").fetchall()
        return jsonify({"runs": [dict(r) for r in rows],
                        "read_only": app.config["READ_ONLY"]})


def _register_write_routes(app):
    """Every route that writes, runs a job, reaches the network, or feeds one
    of those. Registered only by create_app, never on the LAN app."""
    conn = _conn

    def _key_ref():
        """(gamekey, machine_name) from the request body, or (None, None).

        Both travel in a POST body, never a query string: machine_name is
        derived from the product title, so it names something owned, and
        query strings reach access logs and browser history. Same reason
        filter-aware export posts its id list rather than passing it.
        """
        data = _json_object()
        gamekey, machine_name = data.get("gamekey"), data.get("machine_name")
        if not isinstance(gamekey, str) or not gamekey \
                or not isinstance(machine_name, str) or not machine_name:
            return None, None
        return gamekey, machine_name

    @app.post("/api/keys/hide")
    def hide_key():
        gamekey, machine_name = _key_ref()
        if gamekey is None:
            return jsonify({"error": "gamekey and machine_name required"}), 400
        exists = conn().execute(
            "SELECT 1 FROM external_keys WHERE gamekey=? AND machine_name=?",
            (gamekey, machine_name)).fetchone()
        if not exists:
            return jsonify({"error": "no such key"}), 400
        # OR IGNORE, so hiding twice keeps the first timestamp rather than
        # refreshing it: the date answers "when did I decide this", and a
        # second click is not a second decision.
        conn().execute(
            "INSERT OR IGNORE INTO hidden_keys "
            "(gamekey, machine_name, hidden_at) VALUES (?,?,?)",
            (gamekey, machine_name,
             dt.datetime.now(dt.timezone.utc).isoformat()))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/keys/unhide")
    def unhide_key():
        gamekey, machine_name = _key_ref()
        if gamekey is None:
            return jsonify({"error": "gamekey and machine_name required"}), 400
        # No existence check against external_keys, unlike hide, and not an
        # oversight: a hide outlives the key it names -- every hide is
        # stale straight after a reset -- and those are exactly the rows
        # most in need of removing. Do not "tidy" this into symmetry.
        conn().execute(
            "DELETE FROM hidden_keys WHERE gamekey=? AND machine_name=?",
            (gamekey, machine_name))
        conn().commit()
        return jsonify({"ok": True})

    def _item_exists(item_id):
        return conn().execute("SELECT 1 FROM items WHERE id=?",
                              (item_id,)).fetchone() is not None

    @app.post("/api/items/<int:item_id>/rating")
    def set_rating(item_id):
        # The star widget renders 1..5 and sends null to clear (catalog.js
        # `stars`), so that is the entire domain. A value outside it is
        # refused rather than clamped: storing something the user did not
        # choose is worse than saying no. Validation and the existence
        # check follow read-status, which is the pattern for every
        # user-owned field.
        data = _json_object()
        if "rating" not in data:
            return jsonify({"error": "rating required"}), 400
        rating = data["rating"]
        # bool before int: True is an int in Python and would store as 1.
        if rating is not None and (isinstance(rating, bool)
                                   or not isinstance(rating, int)
                                   or not 1 <= rating <= 5):
            return jsonify({"error": "rating must be null or 1-5"}), 400
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        conn().execute("UPDATE items SET my_rating=? WHERE id=?",
                       (rating, item_id))
        conn().commit()
        return jsonify({"ok": True})

    # User-owned fields. These deliberately follow the /rating pattern and
    # never reach apply_hand_edit, so writing them leaves pre_edit NULL and
    # the row stays open to re-enrichment.
    @app.post("/api/items/<int:item_id>/user-tags")
    def set_user_tags(item_id):
        tags = _json_object().get("tags")
        if not isinstance(tags, list):
            return jsonify({"error": "tags must be a list"}), 400
        # Entries too, not just the list. `db.normalize_tags` coerces with
        # str(), which is right for the import paths it also serves - a
        # number in a spreadsheet cell is a genre - but here it turned
        # {"tags": [null]} into a tag literally spelled None, stored with
        # a 200. Refusing at this boundary leaves that coercion intact for
        # the callers that want it.
        if not all(isinstance(t, str) for t in tags):
            return jsonify({"error": "tags must be strings"}), 400
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        value = db.tags_to_json(db.normalize_tags(conn(), db.USER_TAGS, tags))
        conn().execute("UPDATE items SET user_tags=? WHERE id=?",
                       (value, item_id))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/comment")
    def set_comment(item_id):
        # The key must be PRESENT, the same rule /rating states and for a
        # sharper reason: an absent comment used to mean "clear it", so a
        # body carrying no fields at all performed a destructive write.
        # Once a malformed body reads as an empty object rather than
        # raising, that turns a client bug into silent data loss. Clearing
        # is still done the documented way, by sending a blank string.
        body = _json_object()
        if "comment" not in body:
            return jsonify({"error": "comment required"}), 400
        comment = body["comment"]
        if comment is not None and not isinstance(comment, str):
            return jsonify({"error": "comment must be a string"}), 400
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        comment = (comment or "").strip() or None
        conn().execute("UPDATE items SET user_comment=? WHERE id=?",
                       (comment, item_id))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/type")
    def set_type(item_id):
        new_type = _json_object().get("type")
        if new_type not in ("ebook", "audiobook", "comic", "music"):
            return jsonify({"error": "bad type"}), 400
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        conn().execute("UPDATE items SET type=?, type_overridden=1 WHERE id=?",
                       (new_type, item_id))
        conn().commit()
        return jsonify({"ok": True})

    # read_status is user-owned, like /rating: its own route, never routed
    # through apply_hand_edit, so it never touches pre_edit or hand_edited.
    READ_STATUSES = ("want_to_read", "unread", "reading", "read", "dnf")

    @app.post("/api/items/<int:item_id>/read-status")
    def set_read_status(item_id):
        status = _json_object().get("status")
        if status not in READ_STATUSES:
            return jsonify({"error": "bad status"}), 400
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        conn().execute("UPDATE items SET read_status=? WHERE id=?",
                       (status, item_id))
        conn().commit()
        return jsonify({"ok": True})

    @app.get("/api/review")
    def review():
        rows = conn().execute(
            "SELECT i.id, i.name, i.type, i.cover_path, e.status, e.candidates "
            "FROM items i JOIN enrichment e ON e.item_id = i.id "
            "WHERE e.status IN ('low_confidence','unmatched')").fetchall()
        out = []
        for r in rows:
            cands = _sorted_candidates(r["candidates"])
            out.append({"id": r["id"], "name": r["name"], "type": r["type"],
                        "cover_path": r["cover_path"], "status": r["status"],
                        "candidates": cands,
                        "best": cands[0].get("confidence", 0) if cands else 0})
        out.sort(key=lambda x: (x["best"], x["name"]), reverse=True)
        return jsonify({"items": out})

    @app.get("/api/duplicates")
    def duplicates():
        out = []
        for ids in dedupe.find_groups(conn()):
            members = []
            for iid in ids:
                r = conn().execute(
                    "SELECT i.id, i.machine_name, i.name, i.type, i.cover_path, "
                    "i.publisher, i.my_rating, e.genre, e.series, e.hand_edited "
                    "FROM items i JOIN enrichment e ON e.item_id=i.id "
                    "WHERE i.id=?", (iid,)).fetchone()
                m = dict(r)
                m["genre"] = db.tags_from_json(m["genre"])
                m["edited"] = bool(m.pop("hand_edited"))
                m["bundles"] = [b["name"] for b in conn().execute(
                    "SELECT b.name FROM bundles b "
                    "JOIN item_bundles ib ON ib.gamekey=b.gamekey "
                    "WHERE ib.item_id=? ORDER BY b.name", (iid,))]
                members.append(m)
            out.append(members)
        return jsonify({"groups": out})

    @app.post("/api/merge")
    def merge():
        data = _json_object()
        keep_id, drop_id = data.get("keep_id"), data.get("drop_id")
        if not isinstance(keep_id, int) or not isinstance(drop_id, int) \
                or keep_id == drop_id:
            return jsonify({"error": "two distinct item ids required"}), 400
        rows = {r["id"]: r["type"] for r in conn().execute(
            "SELECT id, type FROM items WHERE id IN (?,?)", (keep_id, drop_id))}
        if len(rows) != 2:
            return jsonify({"error": "no such item"}), 400
        # An ebook and its audiobook are different files from different
        # bundles, so they stay separate rows. `editions.py` supplies the
        # relationship instead -- this refusal is half an answer without
        # it.
        if rows[keep_id] != rows[drop_id]:
            return jsonify({"error": "items have different types; an ebook "
                            "and its audiobook stay separate"}), 400
        db.merge_items(conn(), keep_id, drop_id)
        return jsonify({"ok": True})

    @app.post("/api/dismiss_pair")
    def dismiss_pair():
        data = _json_object()
        id_a, id_b = data.get("id_a"), data.get("id_b")
        if not isinstance(id_a, int) or not isinstance(id_b, int) or id_a == id_b:
            return jsonify({"error": "two distinct item ids required"}), 400
        rows = conn().execute(
            "SELECT machine_name FROM items WHERE id IN (?,?)",
            (id_a, id_b)).fetchall()
        if len(rows) != 2:
            return jsonify({"error": "no such item"}), 400
        a, b = sorted(r["machine_name"] for r in rows)
        conn().execute(
            "INSERT OR IGNORE INTO dismissed_pairs (a, b) VALUES (?,?)", (a, b))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/reopen")
    def reopen(item_id):
        # No body is read at all -- reopen takes none, and tests post it
        # bare -- so the only thing to check is that the item is real.
        if not _item_exists(item_id):
            return jsonify({"error": "no such item"}), 404
        conn().execute(
            "UPDATE enrichment SET status='low_confidence' "
            "WHERE item_id=? AND status != 'pending'", (item_id,))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/apply")
    def apply_arbitrary(item_id):
        cand = _json_object().get("candidate")
        if not isinstance(cand, dict) or not cand.get("source") or not cand.get("title"):
            return jsonify({"error": "candidate with source and title required"}), 400
        apply_candidate(conn(), item_id, cand, cand.get("confidence", 1.0),
                        "manually_fixed")
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/edit")
    def edit(item_id):
        fields = _json_object().get("fields")
        if not isinstance(fields, dict) or not fields:
            return jsonify({"error": "fields required"}), 400
        clean = {}
        for key, value in fields.items():
            if key not in EDITABLE_FIELDS:
                return jsonify({"error": f"'{key}' is not editable"}), 400
            if key in db.TAG_FIELDS:
                if not isinstance(value, list):
                    return jsonify({"error": f"'{key}' must be a list of tags"}), 400
                if key == "genre":
                    value = db.normalize_tags(conn(), db.GENRE, value)
                clean[key] = db.tags_to_json(value)
            elif key == "source_url" and value not in (None, ""):
                try:
                    clean[key] = url_import.normalize_url(str(value).strip())
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 400
            elif value in (None, ""):
                clean[key] = None
            elif key == "series_number":
                try:
                    clean[key] = float(value)
                except (TypeError, ValueError):
                    return jsonify({"error": "series_number must be a number"}), 400
            else:
                clean[key] = str(value)
        if not db.apply_hand_edit(conn(), item_id, clean):
            return jsonify({"error": "no such item"}), 404
        return jsonify({"ok": True})

    @app.post("/api/genres/rename")
    def rename_genre():
        data = _json_object()
        old = _text_field(data, "old")
        new = _text_field(data, "new")
        if not old or not new:
            return jsonify({"error": "old and new tag names required"}), 400
        changed = db.rename_tag(conn(), db.GENRE, old, new)
        if changed is None:
            return jsonify({"error": f"no such genre tag: {old}"}), 404
        return jsonify({"changed": changed})

    @app.post("/api/genres/delete")
    def delete_genre():
        data = _json_object()
        tag = _text_field(data, "tag")
        if not tag:
            return jsonify({"error": "tag required"}), 400
        changed = db.delete_tag(conn(), db.GENRE, tag)
        if changed is None:
            return jsonify({"error": f"no such genre tag: {tag}"}), 404
        return jsonify({"changed": changed})

    # The user-tag vocabulary is a separate pool from genre: these mirror
    # the /api/genres routes, one TagColumn argument apart.
    @app.post("/api/user-tags/rename")
    def rename_user_tag():
        data = _json_object()
        old = _text_field(data, "old")
        new = _text_field(data, "new")
        if not old or not new:
            return jsonify({"error": "old and new tag names required"}), 400
        changed = db.rename_tag(conn(), db.USER_TAGS, old, new)
        if changed is None:
            return jsonify({"error": f"no such user tag: {old}"}), 404
        return jsonify({"changed": changed})

    @app.post("/api/user-tags/delete")
    def delete_user_tag():
        tag = _text_field(_json_object(), "tag")
        if not tag:
            return jsonify({"error": "tag required"}), 400
        changed = db.delete_tag(conn(), db.USER_TAGS, tag)
        if changed is None:
            return jsonify({"error": f"no such user tag: {tag}"}), 404
        return jsonify({"changed": changed})

    @app.post("/api/user-tags/bulk")
    def bulk_user_tags():
        data = _json_object()
        ids = data.get("ids")
        tag = _text_field(data, "tag")
        action = data.get("action")
        if not isinstance(ids, list) or not ids:
            return jsonify({"error": "ids must be a non-empty list"}), 400
        if not all(isinstance(i, int) for i in ids):
            return jsonify({"error": "ids must be integers"}), 400
        if not tag:
            return jsonify({"error": "tag required"}), 400
        if action not in ("add", "remove"):
            return jsonify({"error": "action must be 'add' or 'remove'"}), 400
        # Unknown ids are ignored rather than rejected: the catalog can
        # change under a page that has been open a while.
        #
        # The ids and not a count: they are the set an undo has to act on,
        # and a count beside them would be a second derivation of one fact.
        # The client says ids.length.
        return jsonify({"ids": db.bulk_user_tag(conn(), ids, tag, action)})

    @app.post("/api/items/<int:item_id>/revert")
    def revert(item_id):
        row = conn().execute("SELECT pre_edit FROM enrichment WHERE item_id=?",
                             (item_id,)).fetchone()
        if row is None or row["pre_edit"] is None:
            return jsonify({"error": "nothing to revert"}), 400
        snapshot = json.loads(row["pre_edit"])
        # Only restore what the snapshot actually captured. A key missing
        # because it predates the field joining EDITABLE_FIELDS means "not
        # recorded", not "was null" - writing NULL there destroys live data.
        restore = [f for f in EDITABLE_FIELDS if f in snapshot]
        conn().execute(
            # Authorship flips rather than being set: pre_edit always holds
            # the OTHER author's values. Reverting a hand edit shows the
            # enriched values again (not edited); reverting a re-enriched row
            # gives the typed values back (edited once more).
            "UPDATE enrichment SET pre_edit=NULL, hand_edited=NOT hand_edited"
            + "".join(f", {f}=?" for f in restore)
            + " WHERE item_id=?",
            (*(snapshot[f] for f in restore), item_id))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/override")
    def set_override(item_id):
        """Queue (or unqueue) one hand-edited row for re-enrichment.

        One-shot: the next enrich run consumes the flag. Nothing changes
        until that run, so this is safe to toggle freely.
        """
        want = _json_object().get("override")
        if not isinstance(want, bool):
            return jsonify({"error": "override must be a boolean"}), 400
        row = conn().execute("SELECT hand_edited FROM enrichment WHERE item_id=?",
                             (item_id,)).fetchone()
        if row is None:
            return jsonify({"error": "no such item"}), 404
        if want and not row["hand_edited"]:
            # not an error of degree: an un-edited row is already eligible
            return jsonify({"error": "only hand-edited rows need an override"}), 400
        conn().execute("UPDATE enrichment SET enrich_override=? WHERE item_id=?",
                       (1 if want else 0, item_id))
        conn().commit()
        return jsonify({"ok": True})

    @app.post("/api/items/<int:item_id>/fetch_url")
    def fetch_url(item_id):
        url = _url_from_body()
        if not url:
            return jsonify({"error": "url required"}), 400
        try:
            cand = url_import.resolve(conn(), url)
        # MetadataUnavailable first: it is not a ValueError, but keeping the
        # order explicit documents that a rejected URL must never degrade to
        # a link-only candidate.
        except (url_import.MetadataUnavailable, requests.RequestException) as exc:
            row = conn().execute("SELECT name FROM items WHERE id=?",
                                 (item_id,)).fetchone()
            if row is None:
                return jsonify({"error": "no such item"}), 404
            cand = candidate(source=url_import.host_of(url),
                             title=row["name"], url=url)
            cand["link_only"] = True
            cand["reason"] = str(exc)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"candidate": cand})

    @app.post("/api/bundle-preview")
    def bundle_preview_route():
        # POST, not GET, for the reason filter-aware export chose one: a
        # bundle URL in a query string reaches access logs and history.
        # Nothing here writes to the catalog -- the report is a question,
        # not a fact about the library.
        url = _url_from_body()
        if not url:
            return jsonify({"error": "url required"}), 400
        try:
            bundle = bundle_preview.fetch_bundle(url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except requests.RequestException as exc:
            # An upstream failure, not a bad request: 502 keeps a retired
            # bundle distinguishable from a URL we refused.
            return jsonify({"error": str(exc)}), 502
        return jsonify(bundle_preview.preview(conn(), bundle, url=url))

    @app.post("/api/choice-preview")
    def choice_preview_route():
        # Reads no field: Choice is always "this month". POST rather than
        # GET because this is a credentialed network action whose response
        # is a fact about what the owner holds -- neither belongs in a
        # query string that reaches access logs and browser history.
        #
        # It still requires an object, and checks before fetching: a
        # malformed request must not start a browser or a network call.
        if _json_object_or_none() is None:
            return jsonify({"error": "JSON object required"}), 400
        try:
            hub = choice_preview.fetch_choice()
        except humble_api.NotLoggedIn:
            # 409, never 401: nothing about this request's authorization is
            # wrong, and the fix is a command run in a terminal. The server
            # must not attempt the login itself -- manual_login blocks on a
            # browser window it cannot see.
            return jsonify({"error": "Humble session expired -- run "
                                     "`python -m humble_catalog login`, "
                                     "then try again."}), 409
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except requests.RequestException as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify(choice_preview.preview(conn(), hub))

    @app.post("/api/items/<int:item_id>/choose")
    def choose(item_id):
        # The index is compared against the candidate list below, so it has
        # to be an int before that comparison, not after it: a string index
        # raised TypeError here rather than answering 400. bool is excluded
        # for the reason /rating excludes it.
        idx = _json_object().get("candidate")
        if not isinstance(idx, int) or isinstance(idx, bool):
            return jsonify({"error": "candidate index required"}), 400
        row = conn().execute("SELECT candidates FROM enrichment WHERE item_id=?",
                             (item_id,)).fetchone()
        # An item with no enrichment row has nothing to choose from. That
        # is a missing target, not a bad index.
        if row is None:
            return jsonify({"error": "no such item"}), 404
        cands = _sorted_candidates(row["candidates"])
        if not (0 <= idx < len(cands)):
            return jsonify({"error": "bad candidate index"}), 400
        cand = cands[idx]
        apply_candidate(conn(), item_id, cand,
                        cand.get("confidence", 1.0), "manually_fixed")
        return jsonify({"ok": True})

    def _export_request():
        # (ids, error_response). GET is the whole catalog at a plain URL --
        # what a bookmark, a curl, or a script wants. POST carries the ids
        # the viewer is showing, in the order it shows them; the filter
        # predicate lives only in the browser, so the row set has to
        # arrive from there. Not a GET query string: a list of item ids
        # describes the private library, and query strings reach access
        # logs and history.
        #
        # Shared by both format routes so they cannot drift on what a
        # malformed body means.
        #
        # `columns` rides along because the row set and the column set are
        # independent choices that arrive in the same click. A non-list is
        # a 400 like `ids`; an unknown NAME is not -- export._columns drops
        # it, because stored browser state outlives a schema rename.
        if request.method != "POST":
            return None, None, None
        body = _json_object()
        ids = body.get("ids")
        if not isinstance(ids, list):
            return None, None, (jsonify({"error": "ids must be a list"}), 400)
        columns = body.get("columns")
        if columns is not None and not isinstance(columns, list):
            return None, None, (jsonify({"error": "columns must be a list"}), 400)
        return ids, columns, None

    @app.route("/api/export.csv", methods=["GET", "POST"])
    def export_csv():
        ids, columns, err = _export_request()
        if err:
            return err
        buf = io.StringIO(newline="")
        export.write_csv(conn(), buf, ids=ids, columns=columns)
        # utf-8-sig prepends the BOM: same bytes the CLI export writes.
        return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition":
                                 "attachment; filename=catalog.csv"})

    @app.route("/api/export.xlsx", methods=["GET", "POST"])
    def export_xlsx():
        # A sibling route, not a ?format= parameter: the suffix is what
        # makes the GET form bookmarkable and self-describing.
        ids, columns, err = _export_request()
        if err:
            return err
        buf = io.BytesIO()  # binary: openpyxl owns the encoding
        export.write_xlsx(conn(), buf, ids=ids, columns=columns)
        return Response(
            buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument"
                     ".spreadsheetml.sheet",
            headers={"Content-Disposition":
                     "attachment; filename=catalog.xlsx"})

    def _runner():
        return app.config["JOB_RUNNER"]

    def _slot():
        return app.config.get("HANDOFF")

    def _handoff_pending():
        """A 409 while a handoff waits, else None.

        The server is about to step down; a job spawned now would hold
        the catalog open under a restore, or be wiped under a reset.
        """
        slot = _slot()
        pending = slot.busy() if slot is not None else None
        if pending:
            return jsonify({"error": f"the viewer is handing {pending} to "
                            "the terminal"}), 409
        return None

    @app.get("/api/backups")
    def backups():
        # So restore is chosen from a list, never typed as a path.
        return jsonify({"backups": handoff.list_backups(
            app.config["BACKUPS_DIR"])})

    @app.post("/api/jobs/handoff")
    def handoff_job():
        """Queue login, reset or restore for the terminal serve runs in.

        The answer goes out before the server steps down; the page then
        shows the takeover screen and waits for `generation` to move.
        The page's two clicks only ARM this. reset and restore still ask
        for a typed word at the console, and that is the real guard.
        """
        data = _json_object_or_none()
        if data is None:
            return jsonify({"error": "a JSON object is required"}), 400
        slot = _slot()
        command = _text_field(data, "command")
        if slot is None:
            return jsonify({"error": _no_terminal_message(command)}), 409
        options = data.get("options") or {}
        if not command:
            return jsonify({"error": "command required"}), 400
        if not isinstance(options, dict):
            return jsonify({"error": "options must be an object"}), 400
        running = _runner().state()["running"]
        if running:
            # restore cannot swap a file a job holds open, and reset must
            # not wipe the catalog under one.
            return jsonify({"error": f"{running['command']} is running; "
                            "cancel it or let it finish first"}), 409
        try:
            # handoff.argv whitelists the command and matches the snapshot
            # against the listing; nothing else from the body reaches argv.
            line = handoff.argv(command, options, data.get("snapshot"),
                                app.config["BACKUPS_DIR"])
            generation = slot.request(command, line)
        except jobs.Busy as exc:
            return jsonify({"error": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"command": command, "generation": generation})

    @app.post("/api/jobs/start")
    def start_job():
        refused = _handoff_pending()
        if refused:
            return refused
        data = _json_object()
        command = _text_field(data, "command")
        options = data.get("options") or {}
        if not command:
            return jsonify({"error": "command required"}), 400
        if not isinstance(options, dict):
            return jsonify({"error": "options must be an object"}), 400
        try:
            # jobs.argv does the whitelisting, inside start(): an unknown
            # command and a bad option value are the same class of refusal
            # and must not be re-implemented here, or the two could drift.
            job = _runner().start(command, options,
                                  force=bool(data.get("force")))
        except jobs.Busy as exc:
            return jsonify({"error": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(job), 202

    @app.post("/api/jobs/cancel")
    def cancel_job():
        if not _runner().cancel():
            return jsonify({"error": "nothing is running"}), 409
        return jsonify({"ok": True}), 202

    @app.post("/api/jobs/import-sheets")
    def import_sheets_job():
        """Upload one workbook and run import-sheets over it.

        Base64 inside JSON rather than a multipart form, and that is a
        security decision rather than a taste one: form-encoded and
        multipart are exactly the body types a cross-origin HTML form can
        send, and refusing them is what stops a page you visit driving
        this API. Keeping "every write endpoint takes JSON only" true
        without exceptions is worth an unglamorous encoding.
        """
        refused = _handoff_pending()
        if refused:
            return refused
        data = _json_object()
        name = _text_field(data, "filename")
        content = data.get("content_b64")
        if not name or not isinstance(content, str):
            return jsonify({"error": "filename and content_b64 required"}), 400
        # The name is kept as given, so it must be a bare .xlsx file name:
        # import-sheets decides ebooks-vs-audiobooks from the FILE NAME, so
        # it cannot be sanitised away, which makes rejecting any path
        # separator or traversal the only safe rule.
        #
        # The separators are spelled out rather than left to pathlib:
        # Path(r"C:\evil.xlsx").name is "evil.xlsx" on Windows and the
        # whole string on POSIX, so a check built on it would mean two
        # different things on the two platforms -- and the weaker of the
        # two is the one that lets a path through.
        if not name.lower().endswith(".xlsx") or name.strip(".") == "" \
                or any(sep in name for sep in ("/", "\\", ":")):
            return jsonify({"error": "filename must be a plain .xlsx name"}), 400
        try:
            blob = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"error": "content_b64 is not valid base64"}), 400
        if len(blob) > MAX_UPLOAD_BYTES:
            return jsonify({"error": "file too large"}), 400
        tmpdir = tempfile.mkdtemp(prefix="humble-import-")
        path = Path(tmpdir) / name
        path.write_bytes(blob)
        try:
            # cleanup runs after the CHILD exits, not here: the file has to
            # outlive this request, and the runner is the only thing that
            # knows when the import is done with it.
            job = _runner().start(
                "import_sheets", {}, args=[str(path)],
                cleanup=lambda: shutil.rmtree(tmpdir, ignore_errors=True),
                force=bool(data.get("force")))
        except jobs.Busy as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": str(exc)}), 409
        except ValueError as exc:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": str(exc)}), 400
        return jsonify({**job, "path": str(path)}), 202

    @app.get("/api/jobs")
    def job_state():
        state = _runner().state()
        # The progress rows come from run_status, the same table
        # /api/status reads, so the page never has two disagreeing
        # accounts of how far a run has got.
        state["progress"] = [dict(r) for r in conn().execute(
            "SELECT * FROM run_status WHERE phase != 'done'")]
        slot = _slot()
        state["handoff"] = ({"available": True, **slot.state()} if slot
                            else {"available": False, "generation": 0,
                                  "pending": None, "last": None})
        return jsonify(state)

def create_app(db_path="catalog.db", covers_dir="covers", backups_dir="backups"):
    app = _new_app(db_path, covers_dir, read_only=False)
    # Where `backup` writes by default, relative to the working directory
    # like catalog.db itself. The restore picker lists it.
    app.config["BACKUPS_DIR"] = backups_dir
    # One runner per app. Held in config rather than a module global so a
    # test can swap in a stub, and so two apps in one process (the suite
    # makes several) never share a job slot.
    app.config["JOB_RUNNER"] = jobs.JobRunner(db_path=db_path)
    # Set by serve(), which is the only thing that can drain a handoff.
    # A bare create_app() (the demo server, launch.json) leaves it None
    # and the handoff route says so rather than queueing into nothing.
    app.config["HANDOFF"] = None

    @app.before_request
    def refuse_foreign_hosts():
        # Before routing, so a foreign caller cannot reach any handler --
        # not even by getting the content type right on a write.
        if not host_is_loopback(request.headers.get("Host")):
            return Response(
                "Refused: the catalog viewer only answers requests "
                "addressed to localhost.\n",
                status=403, mimetype="text/plain")

    _register_read_routes(app)
    _register_write_routes(app)
    return app

PAIR_COOKIE = "hc_lan"
# Chrome caps cookie lifetime at 400 days; asking for more buys nothing.
PAIR_MAX_AGE = 400 * 24 * 3600
NOT_PAIRED = ("Not paired: open the pairing link that "
              "`python -m humble_catalog serve --lan` prints.\n")
# A page, not a 303. A link opened from a QR-scanner app has no initiating
# site, and Chrome may withhold a SameSite=Strict cookie on the redirected
# request; a same-origin refresh is an ordinary same-site navigation.
PAIRED_PAGE = """<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=/">
<title>Paired</title><p>Paired. <a href="/">Open the catalog</a>.</p>"""


def _same_token(given, token):
    # Bytes, because compare_digest refuses a str with non-ASCII in it,
    # and a hostile query string is exactly where that would arrive.
    return hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))


def create_lan_app(db_path="catalog.db", covers_dir="covers", *, host, port,
                   token):
    """The read-only viewer a paired phone reaches over the LAN.

    Registers the read group and nothing else, so a write route here is not
    blocked, it is absent. Every request must name this app's own address
    in Host (the LAN counterpart of refuse_foreign_hosts) and carry the
    pairing cookie, except /pair, which is how the cookie is obtained.
    """
    if not token:
        # Fails closed: an empty token would match an absent cookie.
        raise ValueError("the LAN app needs a non-empty pairing token")
    app = _new_app(db_path, covers_dir, read_only=True)
    authority = f"{host}:{port}".lower()

    @app.before_request
    def guard():
        if (request.headers.get("Host") or "").strip().lower() != authority:
            return Response(
                "Refused: this viewer only answers requests addressed to "
                f"{authority}.\n", status=403, mimetype="text/plain")
        if request.path == "/pair":
            return None
        if not _same_token(request.cookies.get(PAIR_COOKIE, ""), token):
            return Response(NOT_PAIRED, status=403, mimetype="text/plain")
        return None

    @app.get("/pair")
    def pair():
        if not _same_token(request.args.get("token", ""), token):
            print(f"serve --lan: refused a pairing attempt from "
                  f"{request.remote_addr}")
            return Response(NOT_PAIRED, status=403, mimetype="text/plain")
        resp = Response(PAIRED_PAGE, mimetype="text/html")
        resp.set_cookie(PAIR_COOKIE, token, max_age=PAIR_MAX_AGE, path="/",
                        secure=True, httponly=True, samesite="Strict")
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    _register_read_routes(app)
    return app

_QUERY = re.compile(r"\?[^\s#]*")


class LanRequestHandler(WSGIRequestHandler):
    """Werkzeug's handler, minus the query string in the access log.

    /pair?token=... would otherwise print the pairing token again for
    every attempt, right or wrong. Only the logged line changes; the
    request itself is untouched.
    """

    def log_request(self, code="-", size="-"):
        kept = {k: self.__dict__[k] for k in ("path", "requestline")
                if k in self.__dict__}
        for k, v in kept.items():
            setattr(self, k, _QUERY.sub("", v))
        try:
            super().log_request(code, size)
        finally:
            self.__dict__.update(kept)


def _run_all(servers, slot=None):
    """Serve every server on its own thread until Ctrl-C or a handoff,
    then stop all. Returns the handoff request taken from `slot`, or None
    when it was Ctrl-C.

    Polled with sleep() rather than join(): on Windows a bare join() is not
    interrupted by Ctrl-C, so the process would ignore it. The same poll
    checks the slot, so no extra thread or event is needed.
    """
    threads = [threading.Thread(target=s.serve_forever, daemon=True)
               for s in servers]
    for t in threads:
        t.start()
    handoff_request = None
    try:
        while any(t.is_alive() for t in threads):
            handoff_request = slot.take() if slot is not None else None
            if handoff_request is not None:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for s in servers:
            s.shutdown()
            s.server_close()
    return handoff_request


def _bind(wanted, error_cls, hint):
    """Build (and so bind) every server before any starts, so a busy port
    stops the whole command rather than leaving half of it running."""
    servers = []
    for h, p, app, kw in wanted:
        try:
            servers.append(make_server(h, p, app, threaded=True, **kw))
        except (OSError, SystemExit) as exc:
            # Werkzeug 3.1 catches the bind OSError itself, prints a line
            # and calls sys.exit(1); a raw OSError is caught too, in case
            # it ever stops doing that.
            for s in servers:
                s.server_close()
            detail = f" ({exc})" if isinstance(exc, OSError) else ""
            raise error_cls(
                f"cannot listen on {h}:{p}{detail} -- {hint}") from exc
    return servers


def _serve_loop(wanted, slot, viewer_url, error_cls, hint, servers):
    """Serve; on a handoff, step down, run it, and serve again.

    `servers` is the first round, already bound by serve() so that a busy
    port is reported before the browser opens. Every way the command can
    end -- an exit code, Ctrl-C, a failed spawn, or a bug in this loop's
    own handling -- still rebinds, because a reset that crashed and left
    no viewer and no explanation is the failure this loop exists to
    prevent. Only Ctrl-C while SERVING ends it. The browser is not
    reopened: the page reconnects by itself, and a second webbrowser.open
    would be a second tab after every handoff.

    The same app objects are rebound each round, so the job runner's last
    result and the slot's generation survive the restart.
    """
    while True:
        handoff_request = _run_all(servers, slot)
        if handoff_request is None:
            return
        code = None
        try:
            code = handoff.run_in_terminal(handoff_request["command"],
                                           handoff_request["argv"])
        except Exception:                     # noqa: BLE001 - see docstring
            traceback.print_exc()
        finally:
            slot.finish(code)
        servers = _bind(wanted, error_cls, hint)
        print(f"Viewer back at {viewer_url}", flush=True)


LAN_HINT = ("choose another port with --lan-port (or --port for the viewer "
            "itself)")


def viewer_running(port, timeout=1.0):
    """Whether this catalog's viewer already answers on 127.0.0.1:`port`.

    A second `serve` usually means "show me the catalog" (#97). Only an
    answer shaped like /api/status counts, so a port held by anything
    else still gets the usual "cannot listen" error. http.client, not
    requests: it ignores proxy settings, and this must reach loopback.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/api/status")
        resp = conn.getresponse()
        if resp.status != 200:
            return False
        body = json.loads(resp.read())
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        conn.close()
    return isinstance(body, dict) and {"runs", "read_only"} <= body.keys()


def _no_terminal_message(command):
    """Why a viewer with no terminal refuses a handoff, and what to do."""
    reason = ("this viewer has no terminal to hand over to (it was "
              "started detached, with --no-handoff, or not by `serve`)")
    if command not in handoff.COMMANDS:
        return reason
    line = f"python -m humble_catalog {command}"
    if command == "restore":
        line += " backups/<snapshot>"
    return f"{reason}; run `{line}` in a terminal instead"


def _handoff_slot(terminal_commands):
    """The slot login, reset and restore are handed over through, or None
    when there is no terminal for them to run in (#98)."""
    if terminal_commands and handoff.terminal_available():
        return handoff.HandoffSlot()
    print("login, reset and restore are off in this viewer: it has no "
          "terminal to hand them to. Run them with "
          "`python -m humble_catalog <command>` in a terminal.")
    return None


def serve(db_path="catalog.db", port=8087, lan=None, terminal_commands=True):
    viewer_url = f"http://127.0.0.1:{port}/"
    if lan is None and viewer_running(port):
        # Before the handoff slot, whose notice would describe a viewer
        # this command never starts.
        print(f"Viewer already running at {viewer_url} -- opening it.")
        webbrowser.open(viewer_url)
        return
    # Not named `handoff`: that would shadow the module this file uses.
    slot = _handoff_slot(terminal_commands)
    if lan is None:
        app = create_app(db_path=db_path)
        app.config["HANDOFF"] = slot
        wanted = [("127.0.0.1", port, app, {})]
        # Bound before the browser opens, so a busy port is reported
        # instead of opening a tab onto whatever already holds it.
        hint = "choose another port with --port"
        servers = _bind(wanted, SystemExit, hint)
        print(f"Viewer: {viewer_url}  (Ctrl-C to stop)")
        webbrowser.open(viewer_url)
        _serve_loop(wanted, slot, viewer_url, SystemExit, hint, servers)
        return

    from humble_catalog import lan as lanmod
    # Everything that can be refused is checked before any file under lan/
    # is written: a typo must not rotate the token or mint an authority.
    lanmod.check_port(port, "--port")
    lan_port = lan.port if lan.port is not None else port + 1
    lanmod.check_port(lan_port, "--lan-port")
    if lan.setup:
        # The certificate download listens one above the LAN viewer.
        lanmod.check_port(lan_port + 1, "--lan-port (--setup also uses "
                          "the port above it)")
    host = lan.host or lanmod.lan_address()
    lanmod.private_address(host)

    lan_dir = lanmod.lan_dir_for(db_path)
    token = (lanmod.rotate_token(lan_dir) if lan.new_token
             else lanmod.load_or_create_token(lan_dir))
    _ca_key, ca_cert = lanmod.ensure_ca(lan_dir)
    crt, key = lanmod.issue_server_cert(lan_dir, host)

    # Every server is built -- and so every port bound -- before any
    # starts, so a busy port stops the whole command rather than leaving
    # half of it running.
    loopback = create_app(db_path=db_path)
    loopback.config["HANDOFF"] = slot
    wanted = [
        ("127.0.0.1", port, loopback, {}),
        (host, lan_port,
         create_lan_app(db_path=db_path, host=host, port=lan_port, token=token),
         {"ssl_context": lanmod.ssl_context(crt, key),
          "request_handler": LanRequestHandler}),
    ]
    if lan.setup:
        wanted.append((host, lan_port + 1, lanmod.ca_download_app(lan_dir), {}))
    servers = _bind(wanted, lanmod.LanStateError, LAN_HINT)

    lanmod.print_instructions(
        f"https://{host}:{lan_port}/pair?token={token}",
        viewer_url=viewer_url,
        ca_url=f"http://{host}:{lan_port + 1}/ca.crt" if lan.setup else None,
        fingerprint=lanmod.ca_fingerprint(ca_cert) if lan.setup else None)
    webbrowser.open(viewer_url)
    _serve_loop(wanted, slot, viewer_url, lanmod.LanStateError, LAN_HINT,
                servers)
