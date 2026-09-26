import argparse
import importlib.util
import sys
from pathlib import Path

# Import name -> name to install, for every runtime dependency declared in
# pyproject.toml. Listed here rather than read from installed metadata
# because the case this catches is precisely the one where the package is
# *not* installed: humble_catalog imported straight out of the source tree
# by an interpreter that never had the dependencies. tests/test_main.py
# asserts this stays in step with pyproject.
RUNTIME_DEPENDENCIES = {
    "requests": "requests",
    "flask": "flask",
    "playwright": "playwright",
    "rapidfuzz": "rapidfuzz",
    "openpyxl": "openpyxl",
    "cryptography": "cryptography",
    "qrcode": "qrcode",
}


def missing_dependencies():
    """Declared dependencies this interpreter cannot see.

    find_spec rather than import: it answers the same question without
    executing module code, so the healthy path costs almost nothing.
    """
    return sorted(package for module, package in RUNTIME_DEPENDENCIES.items()
                  if importlib.util.find_spec(module) is None)


def check_dependencies():
    """Explain a wrong interpreter instead of dying four imports deep.

    A forgotten activation does not announce itself on Windows: bare
    `python` resolves to the Microsoft Store stub, which exists, and from
    the repo root it imports humble_catalog out of the source tree (cwd is
    on sys.path) before failing on the first third-party import. The
    result reads as a broken install. Naming the interpreter is what makes
    the real cause visible.
    """
    missing = missing_dependencies()
    if not missing:
        return
    is_are = "is" if len(missing) == 1 else "are"
    print(f"Cannot run: {', '.join(missing)} {is_are} not installed.",
          file=sys.stderr)
    print(f"Interpreter: {sys.executable}", file=sys.stderr)
    print("That is usually the wrong Python rather than a broken install. "
          "Activate the\nproject's virtual environment, or name its "
          "interpreter explicitly:", file=sys.stderr)
    print(r"    .venv\Scripts\python -m humble_catalog ...   (Windows)",
          file=sys.stderr)
    print("    .venv/bin/python -m humble_catalog ...       (macOS, Linux)",
          file=sys.stderr)
    raise SystemExit(1)


def harden_stdio():
    """Print what the stream cannot encode as an escape, never raise.

    Progress lines name owned titles, and a terminal run redirected to a
    file writes with the locale code page: one title with a character
    cp1252 lacks ended a long job with UnicodeEncodeError (#102). A
    `\\u0307` in a log is a better outcome than a lost harvest. The
    viewer's jobs get real UTF-8 instead (jobs.py); this is the backstop
    for everything else.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def main():
    # The subcommands print in declaration order, so they are declared in
    # the order you would run them: enrich matches against what harvest
    # cached, and listing it first told a first-time reader to run the two
    # backwards. The epilog says the same thing in words for anyone who
    # reads the list as an alphabet of equals.
    parser = argparse.ArgumentParser(
        prog="humble_catalog",
        description="Local searchable catalog of your HumbleBundle "
                    "e-books, audiobooks and comics.",
        epilog="'update' runs the whole import below in one go. "
               "Usual order: 'extract' to fetch your library, 'harvest' to "
               "fill the metadata cache (slow and resumable - Google Books' "
               "daily quota means several days), 'enrich' to match that "
               "cache to your items (seconds), then 'serve' to browse. If "
               "a source fills nothing, 'check' says whether its key works; "
               "if a harvest is slow, 'harvest --failures' and 'harvest "
               "--runs' say why. README.md has the detail.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_extract = sub.add_parser("extract", help="Fetch owned bundles from HumbleBundle")
    p_extract.add_argument("--refetch", action="store_true",
                           help="Re-fetch all bundles, refreshing the cache")
    p_extract.add_argument("--no-login", action="store_true",
                           help="Fail if the saved session has expired "
                                "instead of opening a login window (used by "
                                "the viewer, which cannot show one)")
    p_update = sub.add_parser(
        "update",
        help="The whole import in one go: extract, harvest, enrich, and "
             "series from titles",
        description="Runs extract, harvest, enrich and 'enrich --series' in "
                    "that order, stopping at the first step that fails. A "
                    "harvest that runs out of a source's daily quota does "
                    "NOT stop it: enrichment uses what is cached, and "
                    "running update again later picks the harvest up where "
                    "it stopped.")
    p_update.add_argument("--no-login", action="store_true",
                          help="Fail if the saved session has expired "
                               "instead of opening a login window (used by "
                               "the viewer)")
    p_update.add_argument("--games", action="store_true",
                          help="Also import your game libraries at the end")
    p_update.add_argument("--no-harvest", action="store_true",
                          help="Skip the harvest: refresh from what is "
                               "already cached (no metadata requests)")
    sub.add_parser("login", help="Open a browser to (re)log in to HumbleBundle")
    sub.add_parser("reparse", help="Re-classify items from the local cache (no network)")
    p_harvest = sub.add_parser(
        "harvest",
        help="Fetch all external sources in parallel into the cache "
             "(run once; resumable)",
        description="Fetches every relevant metadata source for every book "
                    "and comic into the local cache. Hours, and Google "
                    "Books' daily quota means several days - but it is "
                    "resumable, so rerunning picks up where it stopped. "
                    "--failures, --runs and --forget-runs do not harvest: "
                    "they read the database and exit, spending no requests "
                    "and no quota.")
    p_harvest.add_argument("--ignore-quota", action="store_true",
                           help="Retry sources recorded as out of quota "
                                "instead of serving them from cache (use "
                                "after adding a key with a bigger allowance)")
    p_harvest.add_argument("--failures", action="store_true",
                           help="List titles that failed in past runs, most "
                                "persistent first, and exit without "
                                "harvesting (prints titles you own)")
    p_harvest.add_argument("--runs", action="store_true",
                           help="Show what each past run cost - titles, live "
                                "requests, failure rate - and exit")
    p_harvest.add_argument("--forget-runs", action="store_true",
                           help="Delete the recorded run history and exit")
    p_enrich = sub.add_parser(
        "enrich", help="Fill in metadata from external APIs",
        description="Matches items against the harvested cache and fills "
                    "genre, series, ratings and narrator. Purely local and "
                    "quick, so it is safe to re-run whenever the matcher "
                    "changes. Run 'harvest' first: with an empty cache "
                    "there is nothing to match against.")
    p_enrich.add_argument("--retry", action="store_true",
                          help="Also reprocess items that previously found no match")
    p_enrich.add_argument("--reset", action="store_true",
                          help="Wipe ALL enrichment back to pending and exit "
                               "(your ratings and type overrides are kept)")
    p_enrich.add_argument("--reset-reviews", action="store_true",
                          help="Wipe only manual review choices back to pending "
                               "and exit")
    p_enrich.add_argument("--override-edited", action="store_true",
                          help="Re-enrich EVERY hand-edited item (asks for "
                               "confirmation; per-item Revert stays available)")
    p_enrich.add_argument("--credits", action="store_true",
                          help="Fill writer/illustrator for matched comics "
                               "(Comic Vine top-up; resumable)")
    p_enrich.add_argument("--series", action="store_true",
                          help="Fill series name and number from each item's "
                               "own title where no source supplied them "
                               "(local, instant, safe to repeat)")
    sub.add_parser("reset", help="Wipe the derived catalog for a clean "
                                 "rebuild (keeps downloads, covers, harvest "
                                 "history, and your ratings/tags/comments)")
    sub.add_parser("check", help="Test each metadata API (and its key) with "
                                 "one live search")
    sub.add_parser("stats", help="Report what is in the catalog: counts by "
                                 "type, ratings, reading status, enrichment "
                                 "coverage, gaps and genres (no network)")
    p_serve = sub.add_parser("serve", help="Open the searchable catalog")
    p_serve.add_argument("--port", type=int, default=8087,
                         help="Port to listen on (default: 8087)")
    p_serve.add_argument("--lan", action="store_true",
                         help="Also serve a read-only copy to paired devices "
                              "on your home network, over HTTPS")
    p_serve.add_argument("--lan-host", metavar="IP",
                         help="The LAN address to listen on (default: "
                              "detected)")
    p_serve.add_argument("--lan-port", type=int, metavar="N",
                         help="The LAN port (default: --port + 1)")
    p_serve.add_argument("--setup", action="store_true",
                         help="With --lan: also offer the certificate to "
                              "install on a phone, once")
    p_serve.add_argument("--new-token", action="store_true",
                         help="With --lan: replace the pairing token, "
                              "unpairing every device")
    p_export = sub.add_parser("export", help="Write the whole catalog to a "
                                             "CSV or XLSX file "
                                             "(Excel/Sheets-ready)")
    p_export.add_argument("path", nargs="?", default="catalog.csv",
                          help="Destination file; its suffix picks the "
                               "format, .csv or .xlsx (default: catalog.csv)")
    p_export.add_argument("--columns",
                          help="Comma-separated subset of the export's "
                               "columns, e.g. 'title,authors,my_rating' "
                               "(default: all of them, in their usual "
                               "order, which a subset also keeps)")
    p_import = sub.add_parser(
        "import-sheets",
        help="Import ratings/metadata from the reference spreadsheets "
             "(gap-fill only; unmatched rows are reported, not guessed)")
    p_import.add_argument(
        "files", nargs="*",
        help="Workbook paths (default: the two files under "
             "'Reference spreadsheets')")
    p_backup = sub.add_parser(
        "backup",
        help="Write a timestamped snapshot of the catalog (no network)")
    p_backup.add_argument(
        "dest", nargs="?", default="backups",
        help="Destination directory (default: backups)")
    p_backup.add_argument(
        "--covers", action="store_true",
        help="Also snapshot the cover files, as a zip beside the database")
    p_restore = sub.add_parser(
        "restore",
        help="Put a snapshot back over the catalog (asks for confirmation)")
    p_restore.add_argument(
        "snapshot", help="Snapshot .db file written by `backup`")
    p_restore.add_argument(
        "--covers", action="store_true",
        help="Also restore the cover archive paired with that snapshot")
    p_bundle = sub.add_parser(
        "bundle",
        help="Show how much of a live bundle you already own, per tier",
        description="Shows, for each tier, how many items you already own "
                    "and which titles that tier adds over the cheaper ones. "
                    "Books are matched exactly, by the same internal id "
                    "your catalog stores. Games are matched by title and "
                    "only approximately, so treat the game counts as a "
                    "strong hint and check anything you would base a "
                    "purchase on. Run 'import-games' first or every game "
                    "reads as new. Read-only, and needs no login.")
    p_bundle.add_argument(
        "url", help="A humblebundle.com bundle page URL")
    sub.add_parser(
        "choice",
        help="Show how much of this month's Humble Choice you already own",
        description="Shows how many of this month's Humble Choice games you "
                    "already own, counting games in your imported libraries "
                    "and games you hold as an unclaimed Humble key. Games "
                    "are matched by title and only approximately, so treat "
                    "the counts as a strong hint and check anything you "
                    "would base a purchase on. Run 'import-games' first or "
                    "every game reads as new. Read-only, but it needs your "
                    "Humble login -- Choice pages carry nothing when signed "
                    "out.")
    sub.add_parser(
        "import-games",
        help="Import your Steam/Heroic game libraries, so `bundle` can "
             "count games you already own (approximate; title-matched)")
    p_keys = sub.add_parser(
        "keys",
        help="Report Humble store keys whose game is in no imported "
             "library -- probably never claimed",
        description="Lists store keys from past bundles whose game appears "
                    "in none of the libraries you have imported. Run "
                    "'import-games' first, or every key looks unclaimed. A "
                    "key is checked only against its own store, and by "
                    "title and approximately, so treat a row as somewhere "
                    "to look rather than a verdict. Rows you have hidden "
                    "in the viewer are left out; 'keys --hidden' lists "
                    "those instead. This command never writes.")
    p_keys.add_argument(
        "--all", action="store_true",
        help="Also list the keys with no expiry date and the ones that "
             "have already expired")
    p_keys.add_argument(
        "--hidden", action="store_true",
        help="List the keys you have hidden in the viewer, instead of the "
             "report")
    args = parser.parse_args()
    # After parsing, so --help still works on a broken environment: it is
    # stdlib-only, and it is how you find the command names to begin with.
    check_dependencies()
    harden_stdio()
    if args.command == "extract":
        from humble_catalog import extract, humble_api
        try:
            extract.run(refetch=args.refetch, allow_login=not args.no_login)
        except humble_api.NotLoggedIn:
            # A message and a non-zero exit, not a traceback: the viewer
            # shows the last log lines verbatim, and this is the one
            # failure it must translate into an action the user can take.
            raise SystemExit("HumbleBundle session expired -- run "
                             "'python -m humble_catalog login', then "
                             "try again.")
    elif args.command == "update":
        from humble_catalog import humble_api, update
        try:
            update.run(allow_login=not args.no_login, games=args.games,
                       no_harvest=args.no_harvest)
        except humble_api.NotLoggedIn:
            # The same words as extract's exit: the viewer's job panel
            # recognises them and offers its Log in button.
            raise SystemExit("HumbleBundle session expired -- run "
                             "'python -m humble_catalog login', then "
                             "try again.")
    elif args.command == "login":
        from humble_catalog import humble_api
        humble_api.login()
    elif args.command == "reparse":
        from humble_catalog import extract
        extract.reparse()
    elif args.command == "harvest":
        from humble_catalog import harvest
        if args.forget_runs:
            harvest.forget_runs()
        elif args.runs:
            harvest.report_runs()
        elif args.failures:
            harvest.report_failures()
        else:
            harvest.run(ignore_quota=args.ignore_quota)
    elif args.command == "reset":
        from humble_catalog import reset
        reset.run()
    elif args.command == "enrich":
        from humble_catalog import enrich
        if args.override_edited and (args.reset or args.reset_reviews):
            parser.error("--override-edited cannot be combined with --reset "
                         "or --reset-reviews (--reset would wipe the hand "
                         "edits the override exists to carry through)")
        if args.reset or args.reset_reviews:
            enrich.reset(reviews_only=not args.reset)
        elif args.series:
            enrich.fill_series()
        elif args.credits:
            enrich.credits()
        elif args.override_edited:
            enrich.override_edited(retry=args.retry)
        else:
            enrich.run(retry=args.retry)
    elif args.command == "check":
        from humble_catalog import check
        check.run()
    elif args.command == "stats":
        from humble_catalog import db, stats
        conn = db.connect()
        try:
            stats.run(conn)
        finally:
            conn.close()
    elif args.command == "serve":
        from humble_catalog import webapp
        needs_lan = [flag for flag, given in (
            ("--lan-host", args.lan_host), ("--lan-port", args.lan_port),
            ("--setup", args.setup), ("--new-token", args.new_token)) if given]
        if needs_lan and not args.lan:
            parser.error(f"{', '.join(needs_lan)} needs --lan")
        if not args.lan:
            webapp.serve(port=args.port)
        else:
            from humble_catalog.lan import LanOptions, LanStateError
            try:
                webapp.serve(port=args.port, lan=LanOptions(
                    host=args.lan_host, port=args.lan_port,
                    setup=args.setup, new_token=args.new_token))
            except LanStateError as exc:
                sys.exit(f"serve --lan: {exc}")
    elif args.command == "export":
        from humble_catalog import db, export
        # The suffix is the only format signal. A --format flag could only
        # duplicate or contradict the filename beside it, and guessing a
        # format for an unknown suffix would write a mislabelled file.
        suffix = Path(args.path).suffix.lower()
        if suffix not in (".csv", ".xlsx"):
            parser.error(f"cannot tell the format from '{args.path}': "
                         "give a path ending in .csv or .xlsx")
        # Unknown names are fatal here although the web route drops them:
        # a typo on a command line is a mistake being made right now, and
        # silently handing back a file missing 'authors' is worse than
        # refusing. Order is not honoured -- export._columns forces the
        # canonical one -- so this only has to validate.
        columns = None
        if args.columns is not None:
            columns = [c.strip() for c in args.columns.split(",") if c.strip()]
            unknown = [c for c in columns if c not in export.COLUMNS]
            if unknown:
                parser.error("unknown column(s): " + ", ".join(unknown))
            if not columns:
                parser.error("--columns needs at least one column name")
        conn = db.connect()
        try:
            if suffix == ".xlsx":
                with open(args.path, "wb") as fh:  # openpyxl owns encoding
                    count = export.write_xlsx(conn, fh, columns=columns)
            else:
                with open(args.path, "w", encoding="utf-8-sig",
                          newline="") as fh:
                    count = export.write_csv(conn, fh, columns=columns)
        finally:
            conn.close()
        print(f"Wrote {count} items to {args.path}")
    elif args.command == "import-sheets":
        from humble_catalog import import_sheets
        import_sheets.run(args.files or None)
    elif args.command == "backup":
        from humble_catalog import backup
        backup.run(dest=args.dest, with_covers=args.covers)
    elif args.command == "restore":
        from humble_catalog import backup
        backup.restore(args.snapshot, with_covers=args.covers)
    elif args.command == "import-games":
        from humble_catalog import import_games
        import_games.run()
    elif args.command == "keys":
        from humble_catalog import keys
        keys.run(show_all=args.all, hidden=args.hidden)
    elif args.command == "bundle":
        from humble_catalog import bundle_preview
        try:
            bundle_preview.run(args.url)
        except ValueError as exc:
            # A rejected URL is the user's mistake being made right now,
            # so it reads as a usage error rather than a traceback.
            parser.error(str(exc))
    elif args.command == "choice":
        from humble_catalog import choice_preview
        try:
            choice_preview.run()
        except ValueError as exc:
            # A month that cannot be read is a condition to report, not a
            # traceback -- same stance as the bundle command's bad URL.
            parser.error(str(exc))

if __name__ == "__main__":
    main()
