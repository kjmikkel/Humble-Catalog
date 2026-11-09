"""Privacy regression check (see CLAUDE.md).

Pulls every distinct item name, author, narrator, genre, series,
publisher, and bundle name from catalog.db and the reference
spreadsheets, then searches all non-data files in the repo for them.
Exits 1 on any hit not on the allowlist below.

Contains no personal data itself — everything is read at runtime.
Run: .venv/Scripts/python scripts/leak_check.py

`ALLOWED` and `build_terms()` are also imported by
`leak_check_history.py`, which runs the same terms against git history.
Keep them importable: nothing at module scope may read the database or
exit, or importing this file would run a second scan as a side effect.
"""
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

import openpyxl

try:
    from wordfreq import zipf_frequency
except ImportError:  # pragma: no cover - the venv always has it
    # This module is a gate, and the pre-commit hook runs it. Failing to
    # import would break committing with nothing on screen saying why.
    raise SystemExit(
        "leak_check needs wordfreq, for the common-word rule. "
        'Install it with:  python -m pip install -e ".[dev]"')

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Known-benign matches. Anything NOT here fails the check; compared
# case-insensitively.
#
# This list is deliberately small, and is meant to stay that way. Every
# entry is itself a disclosure -- it says "some term in this catalog
# equals this string" -- so the list is a cost, paid only where there is
# no alternative. Two things keep it from growing:
#
# - A single ordinary English word never needs an entry. COMMON_ZIPF
#   below exempts it automatically; 50 entries were removed on
#   2026-09-20 when that rule arrived, because it covered them.
# - A fresh collision in the working tree is REWORDED, not added here.
#   An entry earns its place only when rewording is impossible, which in
#   practice means the text is already in pushed history.
#
# Entries record why they are benign and never what kind of catalog term
# they collided with: naming the role turns a weak signal into a usable
# one. For the same reason, nothing here is grouped by category.
ALLOWED = {t.lower() for t in [
    # Public fixture data. Not from anyone's library: these are the
    # worked examples the source and the tests are built on, and they
    # appear verbatim in the committed hardcover fixture.
    "All Systems Red", "Artificial Condition", "Exit Strategy",
    "Fugitive Telemetry", "Network Effect", "Rogue Protocol",
    "Murderbot Diaries", "The Murderbot Diaries",
    "Martha Wells", "Kevin R. Free", "Frank Herbert",

    # Vocabulary the project uses as itself, in prose and in
    # identifiers, throughout the source and the docs. Each is a phrase,
    # so the single-word rule cannot reach it.
    "Machine learning", "Virtual Reality", "Science Fiction",
    "Science Fiction & Fantasy", "Personal Finance", "Political Science",
    "The Outside", "The Score", "The Way",

    # The tool's own subject matter, which the README and the CLI text
    # cannot avoid naming.
    "Humble Bundle", "Humble Music Bundle",

    # Rare tokens -- too rare for the frequency rule to reach, and
    # present in pushed history, which cannot be edited.
    "O'Reilly", "Packt", "Manning Publications", "No Starch Press",
    "GraphicAudio", "Blek", "ustwo",
]}


# Ordinary single words are not disclosures.
#
# The term set is derived from the live catalog, so it grows as the
# library does, and a perfectly good English word becomes forbidden the
# moment some term happens to equal it -- retroactively, in code that was
# clean when it was written. Writing each one into ALLOWED instead
# published a little more of the library every time: 71 of its 79 entries
# were catalog terms when this was added.
#
# So a single token that is common English is exempt. A lone common word
# cannot reconstruct anything, and is indistinguishable from the same
# word used as itself -- which is exactly what makes it weak.
#
# SINGLE TOKENS ONLY, whatever the score. wordfreq will happily rate a
# phrase by combining its tokens, which rates a three-common-word title
# like any other three common words; a phrase can name exactly one work,
# so no phrase is ever exempt. See the design doc:
# docs/superpowers/specs/2026-09-20-leak-check-common-words-design.md
#
# Calibrated 2026-09-20, and chosen from a gap rather than by taste. The
# single-word entries this list had accumulated fall into two groups with
# nothing between them: four brand names at 1.64 and below, and fifty
# ordinary words at 2.96 and above. 2.9 is the highest value that covers
# all fifty, and it sits in the middle of a band 1.3 wide, so a small
# wordfreq shift cannot move the boundary. At this value 161 of the 386
# single-word terms the catalog holds are exempt -- 2.8% of the 5,675
# terms in the raw set, and the number a run reports.
#
# Re-run the calibration in the design doc when upgrading wordfreq;
# tests/test_leak_check.py pins scores either side of this value so a
# bump cannot move the gate quietly.
COMMON_ZIPF = 2.9


def is_common_word(term):
    """True if `term` is a single ordinary English word.

    `str.isalpha()` does the tokenising: it is false for anything with a
    space, hyphen, apostrophe or digit in it, so "science-fiction" and
    "o'reilly" are not single tokens however common their parts. It is
    true for non-ASCII letters, which is intended -- an accented word is
    still one word.
    """
    return term.isalpha() and zipf_frequency(term, "en") >= COMMON_ZIPF


def db_terms(path):
    """Every private term held in the catalog, or none when there is no
    catalog. A fresh clone has no catalog.db, and sqlite3.connect would
    create an empty one and then fail on every query."""
    if not path.exists():
        return set()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    found = set()
    for r in conn.execute("SELECT name FROM items"):
        found.add(r["name"])
    for r in conn.execute("SELECT DISTINCT publisher AS v FROM items WHERE publisher IS NOT NULL"):
        found.add(r["v"])
    for r in conn.execute("SELECT DISTINCT series AS v FROM enrichment WHERE series IS NOT NULL"):
        found.add(r["v"])
    for r in conn.execute("SELECT DISTINCT name AS v FROM bundles"):
        found.add(r["v"])
    for col in ("authors", "narrator", "genre"):
        for r in conn.execute(f"SELECT {col} AS v FROM enrichment WHERE {col} IS NOT NULL"):
            try:
                vals = json.loads(r["v"])
                found.update(vals if isinstance(vals, list) else [vals])
            except (json.JSONDecodeError, TypeError):
                found.add(str(r["v"]))
    return found


TITLE_KEYS = {"name", "title"}
AUTHOR_KEYS = {"author", "authors"}


def sheet_terms(directory):
    """Titles and authors from the reference spreadsheets, if present."""
    found = set()
    for xlsx in directory.glob("*.xlsx"):
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                continue
            cols = {i: str(h).strip().rstrip(":").lower()
                    for i, h in enumerate(header)
                    if h and str(h).strip().rstrip(":").lower() in TITLE_KEYS | AUTHOR_KEYS}
            for row in rows:
                for i in cols:
                    if i < len(row) and row[i] is not None:
                        found.add(str(row[i]).strip())
    return found


def partition_terms(root=ROOT):
    """(terms to search for, terms exempted as common words).

    Both halves are needed: the first is the gate, the second is only
    ever counted, so a run can report how large its blind spot is without
    naming anything in it.

    An empty first half means there is nothing to check against — no
    catalog.db and no spreadsheets — which callers must report rather
    than treat as a pass.
    """
    terms = db_terms(root / "catalog.db") | sheet_terms(root / "Reference spreadsheets")
    terms = {t.strip() for t in terms if t and str(t).strip()}
    terms = {t for t in terms
             if len(t) >= 4 and not t.replace(".", "").isdigit()
             and t.lower() not in ALLOWED}
    exempt = {t for t in terms if is_common_word(t)}
    return terms - exempt, exempt


def build_terms(root=ROOT):
    """Every private term to search for, allowlist and common words
    already applied.

    Kept as its own name and signature because leak_check_history.py
    imports it.
    """
    return partition_terms(root)[0]


NOTHING_TO_CHECK = (
    "SKIPPED: no catalog.db and no reference spreadsheets, so there is "
    "nothing to check against.\nThis is expected in a fresh clone. The "
    "check only means something on a machine\nholding the real library.")

# Gitignored runtime data. These legitimately contain the private library
# -- that is what they are for -- so scanning them only ever cries wolf,
# and a check that always fails is one that stops being read. "backups"
# holds snapshots written by `backup`; a cover archive's entry names are
# machine_names, so it trips on ~120 terms every time.
# "node_modules" is the same case as .venv: third-party code installed from
# package.json (axe-core, #152), gitignored, never committed. axe-core's
# colour-name tables matched a term once.
EXCLUDE_DIRS = {".git", ".venv", "node_modules", "covers", "cache", "backups",
                "__pycache__", "humble_catalog.egg-info", ".playwright-profile",
                ".secrets", "Reference spreadsheets"}

# Matched against the whole FILENAME, not Path.suffix. SQLite's sidecars
# are the reason: `catalog.db-wal` has suffix ".db-wal", so a suffix test
# for ".db" misses it, and the WAL is raw database pages -- it matched 93
# terms and buried the four real findings. Under WAL the sidecar can hold
# thousands of items the main file does not yet have, so this is not a
# small window. All of these are gitignored and can never be committed.
DATA_FILES = (".db", ".db-wal", ".db-shm", ".db-journal", ".bak", ".xlsx")

def should_scan(rel):
    """Whether a repo-relative POSIX path is one the term check reads.

    Shared by both modes so the staged check and the full sweep cannot
    disagree about what counts as a data file.
    """
    parts = pathlib.PurePosixPath(rel).parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return False
    return parts[-1] != "leak_check.py" and not parts[-1].endswith(DATA_FILES)


# A term matches only where it is not buried inside a longer word.
#
# Plain substring matching blocked commits on `UnboundLocalError` and on a
# `unittest.mock` class name, neither of which mentions the library: a term
# happened to spell part of a longer identifier. Every such trip cost a
# reword, and the rewords that were impossible - a name that belongs to the
# language - had to go into ALLOWED instead, which blinds the gate to every
# genuine title containing that word. Word boundaries end that trade.
#
# "Word character" here is alphanumeric but NOT underscore, which is the
# one place this deliberately differs from `\w`. machine_names join words
# with underscores, so treating `_` as part of a word would stop the gate
# seeing a title inside `moonfall_comic` - exactly the shape a leak takes
# in this project. Hyphens and dots are boundaries for the same reason.
WORDISH = r"[^\W_]"
_PATTERNS = {}


def boundary_pattern(term):
    """A compiled, case-insensitive pattern for `term` as a whole word.

    The assertions are added per side rather than using `\\b`, because a
    term may begin or end with punctuation - "O'Reilly", "R-TYPE", a title
    ending in "!" - and `\\b` there asserts the opposite of what is meant.
    Cached: the callers ask for the same terms thousands of times.
    """
    pattern = _PATTERNS.get(term)
    if pattern is None:
        body = re.escape(term)
        if re.match(WORDISH, term):
            body = f"(?<!{WORDISH})" + body
        if re.match(WORDISH, term[-1]):
            body = body + f"(?!{WORDISH})"
        pattern = _PATTERNS[term] = re.compile(body, re.IGNORECASE)
    return pattern


def make_matcher(terms):
    """A callable: text -> the set of terms occurring in it as whole words.

    Shared by the worktree scan and by leak_check_history, so the two can
    never disagree about what counts as a match.

    The cheap substring test runs first and rejects almost everything; the
    pattern only runs for a term already known to be present, so the regex
    cost is paid on hits rather than on every term of every file. That
    ordering is also why this cannot be blinder than the old matcher: the
    filter is the old rule exactly, and the pattern only ever removes a
    hit that the old rule would have reported.
    """
    prepared = [(t, t.lower()) for t in terms]

    def match(text):
        lowered = text.lower()
        return {t for t, low in prepared
                if low in lowered and boundary_pattern(t).search(text)}

    return match


def scan(sources, terms):
    """({term: [label, ...]}, files_scanned) over (label, text) pairs.

    `sources` may be a generator, so the full sweep never holds the whole
    repo in memory at once.
    """
    match = make_matcher(terms)
    hits, nfiles = {}, 0
    for label, text in sources:
        nfiles += 1
        for t in match(text):
            hits.setdefault(t, []).append(label)
    return hits, nfiles


def worktree_sources(root=ROOT):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if not should_scan(rel.as_posix()):
            continue
        try:
            yield str(rel), p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def staged_paths(root=ROOT):
    """Repo-relative paths staged for the current commit.

    ACMR only: a staged deletion carries no content, and a file being
    removed cannot leak anything. -z because a path with a space in it --
    `Reference spreadsheets/` is one -- comes back quoted otherwise.
    """
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\0") if p]


def staged_sources(root=ROOT):
    """(path, staged text) for each staged file worth scanning.

    Read from the INDEX, not the working tree. Staging a file and then
    editing it further leaves two different versions, and the one that
    ships is the staged one -- scanning the file on disk would check a
    version nobody is committing.
    """
    for rel in staged_paths(root):
        if not should_scan(rel):
            continue
        try:
            blob = subprocess.run(["git", "show", f":{rel}"], cwd=root,
                                  capture_output=True, check=True).stdout
        except subprocess.CalledProcessError:
            continue  # vanished from the index between listing and reading
        yield rel, blob.decode("utf-8", errors="ignore")


def main(argv=()):
    # --staged is the pre-commit path: same terms, same rules, but only
    # over what is about to be committed, which turns a whole-repo sweep
    # into something fast enough to run on every commit.
    staged = "--staged" in argv
    terms, exempt = partition_terms()
    if not terms:
        # Say so loudly rather than printing "clean": with nothing to search
        # for, a pass proves nothing, and quietly succeeding would give a
        # contributor false confidence that the gate had run.
        print(NOTHING_TO_CHECK)
        return 0

    hits, nfiles = scan(
        staged_sources() if staged else worktree_sources(), terms)

    where = "staged file" if staged else "file"
    print(f"checked {len(terms)} terms against {nfiles} {where}"
          f"{'' if nfiles == 1 else 's'}")
    # A count, never the words. The size of the blind spot should be
    # visible rather than assumed, and it moves as the library grows.
    if exempt:
        print(f"{len(exempt)} single common words exempt by frequency")
    if hits:
        print(f"LEAK: {len(hits)} term(s) from the private library found "
              f"in {'the staged changes' if staged else 'the repo'}:")
        for t in sorted(hits):
            print(f"  {t!r}: {sorted(set(hits[t]))}")
        print("Fix: replace with invented names from docs/TEST-DATA.md, "
              "or add to ALLOWED above with a comment saying why it is benign.")
        return 1
    print("clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
