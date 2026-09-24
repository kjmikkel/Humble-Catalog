// The Library section: the table, its filters, sorting, the column
// picker, export, and bulk tagging -- plus the statistics summary, which
// describes the very rows the table is showing and so is read beside it
// rather than in a section of its own.
let sortKey = "name", sortAsc = true;

// Chip filters. Chips (picked from autocomplete) filter by exact tag
// membership, combined per the field's all/any mode; free text in the
// box is a live substring filter on top. A future filterable column
// joins by adding one registry entry here + one input in index.html.
// Order here mirrors the filter bar and the table columns.
const chipFilters = {
  genre:  {accessor: i => i.genre,
           chips: [], mode: "all", text: ""},
  // series and publisher are scalars, not arrays: wrap them so the
  // accessor keeps the array contract that passesChipFilters, the vocab
  // builder's flatMap, and tagCounts all rely on. scalar also hides the
  // all/any toggle, which for one-value-per-item fields is unsatisfiable.
  series: {accessor: i => i.series ? [i.series] : [],
           chips: [], mode: "any", text: "", scalar: true},
  authors: {accessor: i => i.authors,
            chips: [], mode: "all", text: ""},
  // The Narrator/Artist column shows narrator || illustrator, so the
  // filter spans both; a union rather than the column's either/or, so an
  // item carrying both stays findable under either name.
  narrator: {accessor: i => [...i.narrator, ...i.illustrator],
             chips: [], mode: "all", text: ""},
  publisher: {accessor: i => i.publisher ? [i.publisher] : [],
              chips: [], mode: "any", text: "", scalar: true},
  bundle: {accessor: i => i.bundles.map(b => b.name),
           chips: [], mode: "all", text: ""},
  // The personal vocabulary is its own pool, never merged with genre: a
  // genre "Fantasy" and a user tag "fantasy" mean different things, so
  // they stay separately selectable. Fields AND together, so picking one
  // of each narrows rather than widens.
  user_tags: {accessor: i => i.user_tags,
              chips: [], mode: "all", text: ""},
  // Free text, not a vocabulary: suggesting whole notes as chips would be
  // useless, so this filters on typed text only. scalar and textOnly mean
  // different things -- scalar marks one-value-per-item (hiding an
  // unsatisfiable all/any toggle), textOnly suppresses the vocabulary UI.
  user_comment: {accessor: i => i.user_comment ? [i.user_comment] : [],
                 chips: [], mode: "any", text: "", scalar: true, textOnly: true},
};

function passesChipFilters(item) {
  return Object.values(chipFilters).every(f => {
    const tags = f.accessor(item);
    if (f.chips.length) {
      const has = (c) => tags.includes(c);
      if (!(f.mode === "all" ? f.chips.every(has) : f.chips.some(has)))
        return false;
    }
    return !f.text || tags.some(t => t.toLowerCase().includes(f.text));
  });
}

// Match state for the current query, refilled by every visible() call
// and read by render(). Module state consumed by an innerHTML rebuild,
// the same shape as editingTags and genresOpen.
//
// Cleared inside visible() rather than in the search handler because
// shownRows() also calls visible(): spans surviving into a later render
// are exactly the kind of stale-state bug the JS harness exists to catch.
const matchScores = new Map(), matchSpans = new Map();

// Reading-status filter: an "any of the ticked states" set. Not a
// chipFilters entry -- that registry is for open-ended text vocabularies
// with an all/any toggle, and "all" is unsatisfiable for a one-value
// field. Empty means no status constraint.
const statusFilter = new Set();

// Relevance ordering is a flag rather than a sortKey value: sortValue()
// would otherwise have to answer "what is this item's relevance", which
// is a property of the item AND the current query, not of the item.
// Typing turns it on, clicking a column header turns it off.
let relevanceSort = false;
const relevanceActive = () => relevanceSort && $("#search").value.trim() !== "";

// What a reader is told about the ordering that .sort-ind shows a
// sighted user. "none" rather than an absent attribute: on a table that
// IS sorted, silence on the other headers reads as "not sortable".
const ariaSortFor = (key) =>
  key === sortKey && !relevanceActive()
    ? (sortAsc ? "ascending" : "descending") : "none";

// Folding a name is the per-keystroke cost that is trivially avoidable;
// the tier matching is not. Cleared whenever the catalog reloads.
const foldCache = new Map();
const cachedFold = (item) => {
  let folded = foldCache.get(item.id);
  if (!folded) foldCache.set(item.id, folded = Fuzzy.fold(item.name));
  return folded;
};

function visible() {
  const q = $("#search").value.trim();
  const type = $("#f-type").value, flag = $("#f-flag").value;
  const rating = $("#f-rating").value;
  matchScores.clear();
  matchSpans.clear();
  return items.filter(i => {
    // Name only: every other field it used to span now has its own
    // filter, so a catch-all here would just duplicate them. Matching is
    // fuzzy: see fuzzy.js for the tiers and the 0.4 cutoff.
    if (q) {
      const m = Fuzzy.score(q, i.name, cachedFold(i));
      if (m.score < 0.4) return false;
      matchScores.set(i.id, m.score);
      matchSpans.set(i.id, m.spans);
    }
    if (type && i.type !== type) return false;
    if (rating && i.my_rating !== +rating) return false;
    if (statusFilter.size && !statusFilter.has(i.read_status || "unread"))
      return false;
    if (!passesChipFilters(i)) return false;
    if (flag === "multi" && i.bundles.length < 2) return false;
    if (flag === "review" && !["low_confidence", "unmatched"].includes(i.status)) return false;
    // "review" deliberately spans low_confidence AND unmatched, which is
    // the workflow question. Each state also gets its own flag, named for
    // itself, so a stats panel row showing 4 unmatched jumps to exactly
    // those 4 rather than to the 8 the union holds.
    if (ENRICHMENT_STATES.includes(flag) && i.status !== flag) return false;
    // unrated / nocover / nourl all share one shape: keep only items the
    // selected gap predicate calls empty. Non-gap flags miss gapEmpty and
    // fall through to their own checks below.
    if (gapEmpty[flag] && !gapEmpty[flag](i)) return false;
    // Membership, not content: the notes text filter and the user-tag chip
    // filter both match everything on an empty query, so neither can answer
    // "what have I annotated at all?". Guards follow tagBadges/person -- a
    // partial payload from an older server has blanked this page before.
    if (flag === "notes" && !(i.user_comment || "").trim()) return false;
    if (flag === "mytags" && !(i.user_tags || []).length) return false;
    if (flag === "override" && !i.override) return false;
    return true;
  }).sort((a, b) => {
    if (relevanceActive())
      return (matchScores.get(b.id) || 0) - (matchScores.get(a.id) || 0)
          || String(a.name).localeCompare(String(b.name));
    const av = sortValue(a, sortKey), bv = sortValue(b, sortKey);
    const cmp = typeof av === "number" || typeof bv === "number"
      ? (av || 0) - (bv || 0) : String(av).localeCompare(String(bv));
    return sortAsc ? cmp : -cmp;
  });
}

// The sort value for a column. Most columns sort on the raw field, but the
// Narrator/Artist column shows narrator‖illustrator (so it sorts on the same
// via person()), and Bundle has no scalar field — it is an array of {name}.
function sortValue(item, key) {
  if (key === "narrator") return person(item).join(", ");
  if (key === "bundle") return item.bundles.map(b => b.name).join(", ");
  // Number, not the key string: alphabetical would interleave the states
  // meaninglessly. A missing status sorts as unread, matching visible().
  if (key === "read_status")
    return READ_STATUS_ORDER[item.read_status ?? "unread"] ?? READ_STATUS_ORDER.unread;
  return item[key] ?? "";
}

// Reading status. Stored as stable snake_case keys; the array is the
// single source of both the labels and the lifecycle order (used by the
// status sort in sortValue). Kept in sync with export.py's READ_STATUS_LABELS.
const READ_STATUS = [
  ["want_to_read", "Want to read"],
  ["unread", "Unread"],
  ["reading", "Reading"],
  ["read", "Read"],
  ["dnf", "DNF"],
];
const READ_STATUS_LABEL = Object.fromEntries(READ_STATUS);
const READ_STATUS_ORDER = Object.fromEntries(READ_STATUS.map(([k], n) => [k, n]));

// A missing status reads as unread: an older server, or any partial
// payload, can omit the field, and the column is NOT NULL DEFAULT 'unread'
// on the server anyway. Guards match tagBadges/person.
function statusSelect(i) {
  const cur = i.read_status || "unread";
  return `<select class="read-status-select rs-${cur}" data-id="${i.id}">`
    + READ_STATUS.map(([k, label]) =>
        `<option value="${k}"${k === cur ? " selected" : ""}>${label}</option>`
      ).join("")
    + "</select>";
}

// The status cell: a control on the full viewer, text on the LAN one.
function statusCell(i) {
  if (!READ_ONLY) return statusSelect(i);
  const cur = i.read_status || "unread";
  return `<span class="rs-text rs-${cur}">${READ_STATUS_LABEL[cur]}</span>`;
}

function stars(item) {
  // Read-only: plain text, with no data-id for the click handler to act on.
  if (READ_ONLY)
    return item.my_rating ? `<span class="star-text">${"★".repeat(item.my_rating)}</span>` : "";
  // One radiogroup per row, so crossing the table costs one tab stop per
  // row rather than five -- the difference between Tab being usable at
  // catalog size and not. The roving tabindex sits on the current rating,
  // the star a returning keyboard user is most likely to want, or on the
  // first star when nothing is set and there is no rating to return to.
  const tabbable = item.my_rating || 1;
  let html = "";
  for (let n = 1; n <= 5; n++) {
    // Each star is named with the action its own activation performs.
    // Clicking the current rating clears it -- the only way to un-rate
    // from the table -- so that star says so rather than "Rate n", which
    // is what made the clear undiscoverable. The sheet names the same
    // action with a Clear button; the Mine column has no room for one.
    // The title stays for the mouse tooltip; aria-label carries the same
    // words to a reader, which a title alone does not do reliably.
    const label = item.my_rating === n
      ? "Clear rating" : `Rate ${n} star${n === 1 ? "" : "s"}`;
    // The fill is cumulative but the selection is not: three stars are
    // lit at a rating of three, while only the third is checked, so a
    // reader announces one selected radio rather than three.
    html += `<span class="star ${item.my_rating >= n ? "on" : ""}" `
          + `role="radio" aria-checked="${item.my_rating === n}" `
          + `aria-label="${label}" title="${label}" `
          + `tabindex="${n === tabbable ? 0 : -1}" `
          + `data-id="${item.id}" data-n="${n}">★</span>`;
  }
  return `<span class="rating-group" role="radiogroup" aria-label="Rating" `
       + `data-id="${item.id}">${html}</span>`;
}

// What a keypress inside a rating group should do: which star to focus,
// and what rating to store (null clears it). Answers null when the key is
// not the group's, so the listener can leave the event alone -- Tab has to
// keep leaving the group.
//
// A pure function rather than logic inside the keydown listener: the JS
// test harness stubs addEventListener, so a rule written in a listener
// cannot be tested at all. See tests/test_webapp_js.py (#39).
//
// `focused` is the star the key was pressed on (1-5). `current` is the
// row's rating, or null when it is unrated.
function ratingForKey(key, focused, current) {
  // Selection follows focus, so landing on a star is choosing it.
  const at = (n) => ({focus: n, rating: n});
  // Clamped, not wrapped. Every move posts, so wrapping would turn one
  // keypress at either end into a five-star mis-rating.
  const clamp = (n) => Math.min(5, Math.max(1, n));
  switch (key) {
    case "ArrowRight": case "ArrowUp":   return at(clamp(focused + 1));
    case "ArrowLeft":  case "ArrowDown": return at(clamp(focused - 1));
    case "Home": return at(1);
    case "End":  return at(5);
    case "Enter": case " ":
      // The keyboard reading of the click that clears: activating the
      // star that already holds the rating un-rates the row.
      return {focus: focused, rating: current === focused ? null : focused};
    default: return null;
  }
}

// Store `rating` for item `id`, then put focus back on star `star`.
//
// The focus restore is not a nicety. render() rebuilds the table's
// innerHTML, so the star that was just used no longer exists and focus
// falls back to the body -- which a mouse never notices and a keyboard
// user hits on the very next arrow key. preventScroll for the reason
// closeSheet() has it: the row is already where the user is looking.
async function applyRating(id, star, rating) {
  const item = items.find(i => i.id === id);
  const previous = item ? item.my_rating : null;
  // The model moves, and focus returns, BEFORE the request goes out.
  // Arrow keys repeat when held, which is how a rating gets moved
  // several stars at once; waiting for the response leaves the focused
  // star reporting a stale rating for the length of a round trip, and
  // the repeat recomputes from it -- two quick presses moved one star.
  // Nothing is lost by going first: post() never inspects the response,
  // so a rejected write already updated the row under the old order.
  if (item) item.my_rating = rating;
  render();
  const focus = () => document.querySelector(
    `.rating-group[data-id="${id}"] .star[data-n="${star}"]`)
    ?.focus({preventScroll: true});
  focus();
  try {
    await post(`/api/items/${id}/rating`, {rating});
  } catch (err) {
    // Offline. Optimism is only honest if it is undone: the row must
    // not keep showing a rating the server never took.
    if (item) item.my_rating = previous;
    render();
    focus();
    return;
  }
  // No refreshStats() here any more: render() counts the panel itself
  // since #43, so both render() calls above have already redrawn it --
  // and from the rows in memory, so it no longer trails the table by a
  // round trip either.
}

let editingId = null;
let editingTags = null;  // {field: [tags]} while a row is being edited

const vocab = (field) =>
  [...new Set(items.flatMap(i => i[field] || []))].sort();

const tagCounts = (accessor) => {
  const counts = new Map();
  for (const i of items)
    for (const t of accessor(i) || []) counts.set(t, (counts.get(t) || 0) + 1);
  return counts;
};

function chipCell(field) {
  return `<td class="ac-wrap">${editingTags[field].map((t, idx) =>
      `<span class="tag">${esc(t)}<button class="tag-x" data-f="${field}"
             data-i="${idx}" title="Remove">&times;</button></span>`).join("")}
    <input class="tag-input" data-f="${field}" placeholder="add...">
  </td>`;
}

// Re-attach after every render: the table is rebuilt via innerHTML.
function wireTagInputs() {
  for (const input of document.querySelectorAll(".tag-input")) {
    const field = input.dataset.f;
    Autocomplete.attach(
      input,
      () => vocab(field).filter(v => !editingTags[field].includes(v)),
      (value) => {
        if (!editingTags[field].includes(value)) editingTags[field].push(value);
        render();
        document.querySelector(`.tag-input[data-f="${field}"]`)?.focus();
      },
      () => tagCounts(i => i[field]));
  }
}

// Decide whether a save needs to post /edit at all.
//
// Every /edit call snapshots the row and marks it hand-edited, which
// locks it against re-enrichment. So a save that only changed the user
// tags or the note must NOT post /edit -- otherwise jotting a private
// note would silently lock the row, defeating the whole reason those
// columns live on `items` instead of `enrichment`.
//
// `item` is the pre-edit item from /api/items; `fields` is what the form
// is about to send: source_url, series, series_number (strings from the
// inputs) plus the genre/authors/narrator|illustrator tag arrays.
//
// Biased toward posting: a false negative silently drops a real edit,
// which is far worse than a false positive (an unnecessary "edited"
// badge). So anything unrecognised or ambiguous returns true.
function shouldPostEnrichmentEdit(item, fields) {
  if (!item) return true;                 // unknown row: never skip a save
  // Inputs yield trimmed strings ("2", "" when cleared) while the item
  // holds typed values (2.0, null), so compare in the form's terms.
  const asForm = (v) => v == null ? "" : String(v);
  for (const [key, value] of Object.entries(fields)) {
    if (Array.isArray(value)) {
      const before = item[key] || [];      // order counts: reordering is an edit
      if (before.length !== value.length
          || before.some((t, idx) => t !== value[idx])) return true;
    } else if (asForm(item[key]) !== asForm(value)) {
      return true;
    }
  }
  return false;
}

// The Narrator/Artist column shows narrator || illustrator; edit whichever
// has values, defaulting by type (comics get illustrator).
function personField(i) {
  if ((i.narrator || []).length) return "narrator";
  if ((i.illustrator || []).length) return "illustrator";
  return i.type === "comic" ? "illustrator" : "narrator";
}

// Same missing-array tolerance as tagBadges: this feeds it, and reading
// .length off an absent field would throw before it ever got there.
const person = (i) => (i.narrator || []).length ? i.narrator : (i.illustrator || []);

// The rows the viewer is currently showing: the bulk bar's target and the
// export's payload. `filtered` says whether the view is actually narrowed:
// bulk removal is gated on it, so "remove from every item" is never one
// click away.
function shownRows() {
  const rows = visible();
  return {ids: rows.map(i => i.id), count: rows.length,
          filtered: rows.length < items.length};
}

// Single-level undo for the two bulk tag operations. `user_tags` sits
// outside pre_edit by design, so neither has a revert to reach for.
//
// Browser memory deliberately, and not a table: this exists to correct a
// mistake while its result is still on screen. A persisted undo answers a
// different question -- "undo something from last Tuesday" -- and answers
// it badly, since the catalog moves underneath a stored operation. One
// that visibly disappears on reload never promises what it cannot keep.
//
// `action` is already the INVERSE verb, stored ready to post, so firing
// the undo has no branching left to get wrong.
let lastTagOp = null;   // null | {ids, tag, action}

function renderBulkBar() {
  const {count, filtered} = shownRows();
  const tag = $("#bulk-tag").value.trim();
  const addBtn = $("#bulk-add"), removeBtn = $("#bulk-remove");
  addBtn.textContent = `Add to ${count} shown`;
  removeBtn.textContent = `Remove from ${count} shown`;
  addBtn.disabled = !tag || count === 0;
  // Removing is unrecoverable -- user_tags has no pre_edit snapshot -- so
  // it needs an actual filter, not just a confirmation.
  removeBtn.disabled = !tag || count === 0 || !filtered;
  $("#bulk-note").textContent =
    !filtered && tag ? "Narrow the view to remove." : "";
  // No stored label: the text is derived here, so it cannot disagree with
  // the operation the click will actually perform.
  const undoBtn = $("#bulk-undo");
  undoBtn.hidden = !lastTagOp;
  if (lastTagOp)
    undoBtn.textContent = lastTagOp.action === "add"
      ? `Undo: restore "${lastTagOp.tag}" to ${lastTagOp.ids.length} items`
      : `Undo: remove "${lastTagOp.tag}" from ${lastTagOp.ids.length} items`;
}

// The exporter's columns, mirrored here to render the picker. Duplicated
// across the language boundary on purpose -- the alternative is a request
// just to learn the column constants -- and pinned by a test that fails if
// export.py's COLUMNS and this list drift apart.
const EXPORT_COLUMNS = [
  "title", "type", "publisher", "authors", "genre", "series",
  "series_number", "narrator", "illustrator", "my_rating",
  "external_rating", "rating_source", "formats", "bundles",
  "first_purchased", "status", "edited", "user_tags", "user_comment",
  "read_status",
];

// The selection lives here, not in the checkboxes: the boxes are a
// rendering of this set. Reading state back out of the DOM would also be
// untestable, since the JS harness has no real elements.
let exportColumns = new Set(EXPORT_COLUMNS);

function saveColumnSelection() {
  // Guarded like hc-theme: the test sandbox has no localStorage.
  if (typeof localStorage === "undefined") return;
  localStorage.setItem("hc-export-columns", JSON.stringify([...exportColumns]));
}

// Stored state can outlive a COLUMNS rename by months, so this is the
// boundary where old browser state meets the current column list. Every
// way of being unusable -- absent, unparseable, not an array, or naming
// only columns that no longer exist -- collapses to the same answer:
// select everything. That is the one default that is never a silent
// surprise, since a narrowed export is what needs justifying, not a
// complete one.
function loadColumnSelection() {
  if (typeof localStorage === "undefined") return;
  let stored;
  try {
    stored = JSON.parse(localStorage.getItem("hc-export-columns"));
  } catch {
    // Corrupt JSON is not worth a message: the fallback IS the fix, and
    // the next toggle overwrites it.
    return;
  }
  if (!Array.isArray(stored)) return;
  // Filter first, then check: a stored list naming only columns that have
  // since been renamed is indistinguishable from having no preference at
  // all, and must not leave the picker empty with the button disabled and
  // no explanation.
  const known = stored.filter(c => EXPORT_COLUMNS.includes(c));
  if (known.length) exportColumns = new Set(known);
}

// The count is the whole justification for persisting the selection: a
// narrowed export is then never invisible.
function renderColumnCount() {
  $("#column-picker-summary").textContent =
    `Columns (${exportColumns.size}/${EXPORT_COLUMNS.length})`;
}

// Rendered from EXPORT_COLUMNS rather than hand-written into index.html,
// so a column added to export.py cannot be silently missing here.
//
// Only for the cases where the boxes disagree with the set: startup, and
// Select all/none. NOT for a plain toggle -- see toggleColumn.
function renderColumnPicker() {
  $("#column-picker-body").innerHTML = EXPORT_COLUMNS.map(c =>
    `<label><input type="checkbox" class="col-check" data-col="${c}"` +
    `${exportColumns.has(c) ? " checked" : ""}> ${esc(c)}</label>`).join("");
  renderColumnCount();
}

function toggleColumn(name, on) {
  if (on) exportColumns.add(name); else exportColumns.delete(name);
  saveColumnSelection();
  // Deliberately NOT renderColumnPicker(): rebuilding the list detaches
  // the checkbox that was just clicked, so the dismiss-on-click handler
  // then tests contains() against a node no longer in the document,
  // reads the click as landing elsewhere, and closes the panel
  // mid-click. The click already put the box in the right state, so only
  // the count is stale.
  renderColumnCount();
  renderExportButton();
}

// The label doubles as the blast-radius readout: with no filter active
// the export IS the whole catalog. It says WHAT ROWS only -- the format
// is the select's job, so each fact is stated in one place. Disabled at
// zero rows, because a header-only file reads as a bug rather than as an
// empty result.
function renderExportButton() {
  const {count, filtered} = shownRows();
  const btn = $("#export");
  btn.textContent = filtered ? `Download ${count} shown` : "Download all";
  btn.disabled = count === 0 || exportColumns.size === 0;
}

// The rows on screen, posted as ids because the filter predicate lives
// here and not on the server. A Blob rather than a plain link: the request
// has to be a POST, since ids in a query string would put a description of
// the library into access logs and browser history.
async function downloadExport() {
  const {ids, filtered} = shownRows();
  if (!ids.length) return;
  // Not persisted: format is a choice made at the moment of clicking, not
  // a standing preference. The fallback covers a stubbed or absent select.
  const fmt = $("#export-format").value || "csv";
  // Canonical order is the server's job (export._columns), so this posts
  // a set, not an order.
  const columns = EXPORT_COLUMNS.filter(c => exportColumns.has(c));
  const resp = await post(`/api/export.${fmt}`, {ids, columns});
  if (!resp.ok) {
    // Names the format: "could not build the CSV" after clicking XLSX
    // would send someone looking in the wrong place.
    alert(`Could not build the ${fmt.toUpperCase()} file.`);
    return;
  }
  // Content-Disposition stops being authoritative once we materialize the
  // file ourselves, so the filename is decided here -- which is also where
  // `filtered` already is. A filtered export is a different artifact and
  // must not silently overwrite the full one in the downloads folder.
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement("a");
  a.href = url;
  // Narrowed on EITHER axis: fewer rows or fewer columns both make this a
  // different artifact, which must not overwrite the full catalog file.
  const narrowed = filtered || columns.length < EXPORT_COLUMNS.length;
  a.download = `catalog${narrowed ? "-filtered" : ""}.${fmt}`;
  a.click();
  URL.revokeObjectURL(url);
}

async function runBulk(el, action) {
  const {ids} = shownRows();
  const tag = $("#bulk-tag").value.trim();
  if (!tag || !ids.length) return;
  return armOrFire(el, async () => {
    const resp = await post("/api/user-tags/bulk", {ids, tag, action});
    if (!resp.ok) {
      alert((await resp.json()).error || "Could not apply the tag.");
      return;
    }
    const {ids: changedIds} = await resp.json();
    // Only the rows that actually changed, and only when there are any:
    // undoing over the ids we SENT would strip the tag from rows that
    // carried it beforehand, and an empty list is nothing to offer.
    lastTagOp = changedIds.length
      ? {ids: changedIds, tag,
         action: action === "add" ? "remove" : "add"}
      : null;
    const verb = action === "add" ? "Added to" : "Removed from";
    await load();
    // Before the note, never after: renderBulkBar() writes #bulk-note
    // unconditionally, so redrawing the button afterwards would wipe the
    // result the owner just asked for.
    renderBulkBar();
    $("#bulk-note").textContent =
      `${verb} ${changedIds.length} of ${ids.length} items.`;
  });
}

// No armOrFire. The other two buttons arm-then-confirm because they are
// the destructive direction; this is the recovering one, and two clicks
// to recover from a mistake is friction pointing the wrong way.
async function undoBulk() {
  if (!lastTagOp) return;
  const {ids, tag, action} = lastTagOp;
  const resp = await post("/api/user-tags/bulk", {ids, tag, action});
  if (!resp.ok) {
    alert((await resp.json()).error || "Could not undo.");
    return;
  }
  const {ids: changedIds} = await resp.json();
  // Cleared whether or not every row came back: single level, no redo.
  // The original operation is one click away in this same bar.
  lastTagOp = null;
  await load();
  renderBulkBar();          // before the note; see runBulk
  const verb = action === "add" ? "Restored" : "Removed";
  $("#bulk-note").textContent =
    `${verb} "${tag}" on ${changedIds.length} of ${ids.length} items.`;
}

// Every filter currently narrowing the table, summarised in the main
// column so it survives the sidebar being folded away. This is the rule
// that makes collapsing safe: a filter you cannot see is a filter you
// cannot know to clear, and a folded sidebar would otherwise hide the
// reason the table looks empty.
//
// The remove buttons deliberately do NOT carry `tag-x`. That class is
// tested in the click chain AFTER `chip-x`, so an element carrying it
// without `chip-x` falls through to the row-edit branch and splices the
// edit buffer instead of clearing a filter.
// Sidebar collapse, persisted beside the theme. Safe only because
// renderActiveFilters() keeps every active filter visible in the main
// column regardless of what the sidebar is doing.
const sidebarCollapsed = () =>
  (typeof localStorage !== "undefined")
  && localStorage.getItem("hc-sidebar") === "1";

// Two behaviours, split at the width where style.css stops showing the
// sidebar by default. Wider, the button collapses the sidebar and the choice
// is saved. Narrower, the sidebar starts hidden and the button opens it
// (.expanded) for this page only: saved, an open panel would push the cards
// off a phone screen on every visit. The saved collapse is not applied
// there, because .collapsed hides the filters outright and would stop the
// button ever opening them.
const SIDEBAR_NARROW_QUERY = "(max-width: 900px)";
const sidebarNarrow = () =>
  typeof matchMedia === "function" && matchMedia(SIDEBAR_NARROW_QUERY).matches;
let sidebarOpenNarrow = false;

function applySidebar() {
  const narrow = sidebarNarrow();
  const collapsed = sidebarCollapsed();
  $("#library-layout")?.classList.toggle("collapsed", !narrow && collapsed);
  $("#library-layout")?.classList.toggle("expanded", narrow && sidebarOpenNarrow);
  const shown = narrow ? sidebarOpenNarrow : !collapsed;
  $("#sidebar-toggle")?.setAttribute("aria-expanded", String(shown));
}

function toggleSidebar() {
  if (sidebarNarrow()) sidebarOpenNarrow = !sidebarOpenNarrow;
  else if (typeof localStorage !== "undefined")
    localStorage.setItem("hc-sidebar", sidebarCollapsed() ? "0" : "1");
  applySidebar();
}

function renderActiveFilters() {
  const box = $("#filter-chips");
  if (!box) return;
  // selectedOptions is absent in the test harness's element stub; the
  // raw value is a fine label there and never reaches a browser.
  const label = (el) => (el.selectedOptions && el.selectedOptions[0])
    ? el.selectedOptions[0].text : el.value;
  const out = [];
  const chip = (text, attrs) => out.push(
    `<span class="tag active-filter">${esc(text)}<button class="active-x" ${attrs}
       title="Clear this filter">&times;</button></span>`);

  for (const [id, name] of [["f-type", "Type"], ["f-rating", "Rating"],
                            ["f-flag", "Flag"]]) {
    const el = $(`#${id}`);
    if (el && el.value) chip(`${name}: ${label(el)}`,
                             `data-kind="select" data-target="${id}"`);
  }
  for (const s of statusFilter)
    chip(`Status: ${READ_STATUS_LABEL[s] || s}`,
         `data-kind="status" data-status="${esc(s)}"`);
  for (const [field, f] of Object.entries(chipFilters)) {
    f.chips.forEach((c, i) => chip(`${field}: ${c}`,
      `data-kind="chip" data-field="${field}" data-i="${i}"`));
    if (f.text) chip(`${field}: "${f.text}"`,
                     `data-kind="text" data-field="${field}"`);
  }
  const q = $("#search");
  if (q && q.value.trim()) chip(`Search: ${q.value.trim()}`,
                                'data-kind="search"');
  // Offered only while something is filtering: a permanent control with
  // nothing to clear is noise, and this strip is itself empty otherwise.
  // It sits after the chips because it is the summary of them -- clearing
  // one is the common act, clearing all is the escape hatch.
  if (out.length)
    out.push('<button class="clear-all">Clear all filters</button>');
  box.innerHTML = out.join("");
}

// Every filter at once. Four or more clicks before this existed, one per
// chip, with the strip re-rendering under the pointer between them.
//
// Each kind clears the CONTROL, not just the state, for the same reason
// the per-chip handler does: the sidebar has to agree whether it is
// folded away or not.
function clearAllFilters() {
  for (const id of ["f-type", "f-rating", "f-flag"]) {
    const el = $(`#${id}`);
    if (el) el.value = "";
  }
  statusFilter.clear();
  for (const el of document.querySelectorAll(".status-chip"))
    el.classList.remove("on");
  for (const f of Object.values(chipFilters)) {
    f.chips.length = 0;
    f.text = "";
  }
  for (const input of document.querySelectorAll(".chip-filter input"))
    input.value = "";
  const q = $("#search");
  if (q) q.value = "";
  // Relevance is a mode the search box turns on, so it goes with it;
  // leaving it set would order an unfiltered table by a query that is no
  // longer there.
  relevanceSort = false;
  renderFilterChips();
  // The button fires and then deletes itself -- the strip is rebuilt from
  // a filter set that is now empty -- so without this the keyboard is
  // dropped back to <body>, at the top of the page. The search box is
  // where clearing leaves you anyway: it is the next thing most sessions
  // type into.
  $("#search")?.focus();
}

// A bundle's name as the Library table shows it. The column is narrow and
// clamps at two lines (#46, #76), and nearly every bundle name opens with
// the same word and then its kind -- "Humble Book Bundle: ..." -- so the
// clamp spent both lines on what every row shares, first "Humble..." and
// then "Book Bu...". The cell starts after both; the kind is in the link's
// title with the rest of the full name. A colon not after "Bundle" is part
// of the name, and a name that is only prefix keeps it.
const BUNDLE_PREFIX = /^Humble\s+/i;
const BUNDLE_KIND = /^[^:]*?\bBundle:\s*/i;
const bundleLabel = (name) =>
  (name || "").replace(BUNDLE_PREFIX, "").replace(BUNDLE_KIND, "") || name;

// Everything after the title in the name cell. Read-only keeps only what
// navigates -- the source link and the edition jumps -- and drops the
// badges and buttons that exist to drive enrichment.
//
// The glyphs differ only by the shape of an arrow, so each carries an
// aria-label as well as its title (#50): the title is the mouse tooltip,
// and the label adds the row's name, since a reader listing the page's
// buttons hears them without the row around them.
function nameExtras(i) {
  const named = (label) =>
    `title="${label}" aria-label="${label}: ${esc(i.name)}"`;
  const glyph = (cls, label, char) =>
    ` <button class="${cls}" data-id="${i.id}" ${named(label)}>${char}</button>`;
  const src = i.source_url
    ? ` <a class="src-link" href="${esc(i.source_url)}" target="_blank"
             rel="noopener" ${named("Open source page")}>&#x2197;</a>` : "";
  // The key is absent on nearly every row, so the || [] is
  // load-bearing rather than defensive.
  const editions = (i.editions || []).map(o => ` <button class="badge edition edition-jump"
              data-name="${esc(o.name)}"
              title="The same work is in your library as ${esc(o.type)} -- click to go to it"
              >also as ${esc(o.type)}</button>`).join("");
  if (READ_ONLY) return src + editions;
  return src + `${
      i.status === "low_confidence" || i.status === "unmatched"
        ? ' <span class="badge">review</span>' : ""}${
      i.status === "matched" || i.status === "manually_fixed"
        ? glyph("redo", "Redo this match", "&#x27F3;") : ""}${
      glyph("edit", "Edit fields", "&#x270E;")}${
      i.edited
        ? ` <span class="badge edited">edited</span>${
            glyph("revert", "Revert to the enriched values", "&#x21A9;")}${
            glyph("override", i.override
              ? "Cancel the queued re-enrichment"
              : "Let the next enrich run update this row", "&#x21BB;")}` : ""}${
      i.re_enriched
        ? ` <span class="badge">re-enriched</span>${
            glyph("revert", "Revert to your edited values", "&#x21A9;")}` : ""}${
      i.override ? ' <span class="badge queued">re-enrich queued</span>' : ""}` + editions;
}

// Which of the blank tables this is. The reader's next action differs --
// clear a filter, go and fetch something, or go and see why the server
// stopped -- so one flat "nothing here" would send most of them to clear
// filters they never set.
// The LAN viewer gets the shorter line: it has no Tasks section to send
// anyone to, only Library and Keys.
function emptyStateText() {
  // First, because it outranks the other two: after a failed read the
  // rows are unknown rather than absent, and telling the reader to go and
  // fetch some would be wrong advice about a catalog that may be full.
  if (loadError)
    return "Could not read the catalog from the server — it may have"
         + " stopped. Check the terminal, then reload.";
  if (items.length === 0)
    return READ_ONLY
      ? "No items in the catalog yet."
      : "No items in the catalog yet — run Fetch new bundles in Tasks.";
  return "No items match these filters.";
}

// Below this width the 22-column table is unusable (measured at 375 px:
// 1,477 px wide, bundle links off-screen), so each row becomes a card.
const NARROW_QUERY = "(max-width: 600px)";
const isNarrow = () =>
  typeof matchMedia === "function" && matchMedia(NARROW_QUERY).matches;

// Display-only on every viewer: editing needs the table's width. Every
// field is guarded the way tagBadges and person are, so a partial payload
// renders a thinner card instead of throwing.
function renderCards(rows, mark = () => "") {
  return rows.map((i, idx) => {
    const status = READ_STATUS_LABEL[i.read_status || "unread"] || "";
    const series = i.series
      ? ` · ${esc(i.series)}${i.series_number ? " #" + i.series_number : ""}` : "";
    const rating = i.my_rating ? ` · ${"★".repeat(i.my_rating)}` : "";
    const tags = (i.user_tags || []).length ? ` · ${esc(i.user_tags.join(", "))}` : "";
    // The card itself is the control, rather than carrying two of its
    // own: status and stars on every card face cost about 90 px each and
    // roughly halve how much library fits on a screen, which is what the
    // phone is mostly for. Measured both ways before choosing (#45).
    const opens = READ_ONLY ? "" :
      ` role="button" tabindex="0" data-open="${i.id}"` +
      ` aria-label="Edit ${esc(i.name)}"`;
    // A tappable card is already a Tab stop, so it only needs the marker;
    // a read-only one takes tabindex="-1" with it, like a table row.
    const marked = mark(idx) && !READ_ONLY ? " data-revealed" : mark(idx);
    return `<article class="card${READ_ONLY ? "" : " tappable"}"${opens}${marked}>
    ${READ_ONLY ? "" : '<span class="card-chevron" aria-hidden="true">&rsaquo;</span>'}
    ${i.cover_path
      ? `<img class="card-cover" src="/${i.cover_path}" alt="" loading="lazy">`
      : ""}
    <div class="card-body">
      <strong class="card-title">${highlight(i.name, matchSpans.get(i.id))}</strong>
      <div class="card-meta">${esc((i.authors || []).join(", "))}${series}</div>
      <div class="card-meta"><span class="tag">${esc(i.type)}</span> ${esc((i.formats || []).join(", "))}</div>
      <div class="card-meta">${status}${rating}${tags}</div>
      <div class="card-links">${(i.bundles || []).map((b) =>
        `<a class="card-link" href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.name)}</a>`
      ).join("")}</div>
    </div>
  </article>`;
  }).join("");
}

// ---- The phone's edit sheet -------------------------------------------
// Below 600 px the table is gone and with it the status select and the
// stars, so the two fields a phone is actually used for were unreachable.
// The card opens this instead of carrying the controls itself: it costs
// two taps per item and keeps half again as much list on screen.

// Short labels, for the five-button row at 375 px. "Want to read" wraps
// it; "Want" does not. The stored keys and the table's own labels are
// unchanged -- this is a width problem, not a vocabulary one.
const READ_STATUS_SHORT = {want_to_read: "Want", unread: "Unread",
                           reading: "Reading", read: "Read", dnf: "DNF"};

let openSheetId = null;

function sheetFor(i) {
  const cur = i.read_status || "unread";
  const rating = i.my_rating || 0;
  return `<div class="sheet-grabber"></div>
    <h3 id="sheet-title">${esc(i.name)}</h3>
    <p class="sheet-sub">${esc((i.authors || []).join(", ")) || esc(i.type)}</p>
    <div class="sheet-label" id="sheet-status-label">Reading status</div>
    <div class="seg" role="group" aria-labelledby="sheet-status-label">${
      READ_STATUS.map(([k]) =>
        `<button type="button" class="sheet-status rs-${k}" data-id="${i.id}"
           data-s="${k}" aria-pressed="${k === cur}">${READ_STATUS_SHORT[k]}</button>`
      ).join("")}</div>
    <div class="sheet-label" id="sheet-rating-label">My rating</div>
    <div class="sheet-stars" role="group" aria-labelledby="sheet-rating-label">${
      [1, 2, 3, 4, 5].map((n) =>
        `<button type="button" class="sheet-star${rating >= n ? " on" : ""}"
           data-id="${i.id}" data-n="${n}"
           aria-label="${n} star${n === 1 ? "" : "s"}">&#9733;</button>`).join("")}${
      rating ? `<button type="button" class="sheet-star-clear" data-id="${i.id}"
                  data-n="0">Clear</button>` : ""}</div>
    <button type="button" class="sheet-done">Done</button>`;
}

function openSheet(id) {
  const item = items.find((i) => i.id === id);
  if (!item || READ_ONLY) return;
  openSheetId = id;
  const sheet = $("#edit-sheet"), scrim = $("#sheet-scrim");
  sheet.innerHTML = sheetFor(item);
  sheet.hidden = false;
  scrim.hidden = false;
  // Reading a layout property flushes the un-hidden, still-parked state to
  // the engine, so the class that follows transitions from it rather than
  // being collapsed into one paint. The obvious alternative -- deferring
  // the class to requestAnimationFrame -- looks equivalent and is not: a
  // hidden or throttled tab never delivers that frame, and the sheet then
  // sits below the viewport while focused and taking taps. The animation
  // is decoration; being visible is not.
  sheet.getBoundingClientRect();
  sheet.classList.add("open");
  scrim.classList.add("open");
  // preventScroll is load-bearing. At this instant the sheet is still
  // parked at translateY(100%), below the frame, so a plain focus() makes
  // the browser scroll to bring the button into view -- and what visibly
  // moves is the list behind it, which reads as a stray animation.
  sheet.querySelector(".sheet-done")?.focus({preventScroll: true});
}

function closeSheet() {
  const id = openSheetId;
  openSheetId = null;
  const sheet = $("#edit-sheet"), scrim = $("#sheet-scrim");
  sheet.classList.remove("open");
  scrim.classList.remove("open");
  // Hidden only once it has slid away; hiding immediately would cut the
  // transition. A sheet reopened in the meantime keeps itself.
  setTimeout(() => {
    if (openSheetId === null) { sheet.hidden = true; scrim.hidden = true; }
  }, 220);
  // Same reason as above: the card may have scrolled out of view while
  // the sheet was open, and returning focus must not drag the list back.
  document.querySelector(`.card[data-open="${id}"]`)?.focus({preventScroll: true});
}

// The two writes. Separate functions rather than inline in the click
// handler so they can be driven directly by a test -- the harness's
// document stub swallows listeners, so a delegated click is unreachable
// there. They post to the same routes the table's own controls use.
async function setSheetStatus(id, status) {
  await post(`/api/items/${id}/read-status`, {status});
  const item = items.find((i) => i.id === id);
  if (item) item.read_status = status;
  refreshSheet(id);
}

async function setSheetRating(id, n) {
  // 0 means clear, which the route spells as null -- the same value the
  // table's own star sends when the current rating is tapped again.
  const rating = n === 0 ? null : n;
  await post(`/api/items/${id}/rating`, {rating});
  const item = items.find((i) => i.id === id);
  if (item) item.my_rating = rating;
  refreshSheet(id);
}

// Redraw the list behind the sheet and the sheet itself, so the card's
// summary line and the sheet's controls cannot disagree.
function refreshSheet(id) {
  render();
  const item = items.find((i) => i.id === id);
  if (item && openSheetId === id) $("#edit-sheet").innerHTML = sheetFor(item);
  // render() redraws the panel, so there is nothing to refresh after it.
}

// How many rows render() draws. Every drawn row costs ~70us of innerHTML,
// and a table of thousands also makes any layout read cost tens of ms --
// the search box's autocomplete positions itself on every keystroke. So
// the list stops at ROW_CAP with a line saying what was left out (#52).
// Not virtualization: that would fight the sticky <thead> and the
// delegated click handler, and a cap needs neither to change.
//
// The cap applies to drawing only. #count, the bulk bar, the export and
// the stats panel all act on every matching row, via visible().
const ROW_CAP = 200;
let rowLimit = ROW_CAP;
// The view the current rowLimit was granted for. "Show all" expands one
// view; a different one starts capped again, so an expanded list cannot
// make every later keystroke pay for the whole catalog.
let rowLimitView = null;
// Set by showAllRows() for exactly one render: which row to mark as the
// first one the button revealed, so focus has somewhere to land.
let revealFrom = null;

// Identifies what the list is OF, as opposed to how it currently looks.
// render() collapses the list back to ROW_CAP whenever this changes.
//
// Filters only. Sort is left out on purpose: a header click reorders the
// same set, and snapping a list the user just asked to see whole back to
// ROW_CAP would answer a request they did not make. Item content is left
// out too, or rating a star would collapse the list under the pointer.
function viewKey() {
  return JSON.stringify([
    $("#search").value.trim(),
    $("#f-type").value, $("#f-flag").value, $("#f-rating").value,
    [...statusFilter].sort(),
    Object.values(chipFilters).map(f => [f.chips, f.mode, f.text]),
  ]);
}

function showAllRows() {
  revealFrom = Math.min(rowLimit, visible().length);
  rowLimit = Infinity;
  render();
  revealFrom = null;
  const target = isNarrow() ? "#card-list [data-revealed]"
                            : "#catalog tbody [data-revealed]";
  document.querySelector(target)?.focus({preventScroll: true});
}

// The line under a capped list. Empty when nothing was left out.
function moreLine(shown, total) {
  if (shown >= total) return "";
  return `Showing the first ${shown} of ${total}. `
    + `<button type="button" class="show-all">Show all ${total}</button>`;
}

function render() {
  renderActiveFilters();
  const rows = visible();
  const view = viewKey();
  if (view !== rowLimitView) { rowLimit = ROW_CAP; rowLimitView = view; }
  const drawn = rows.slice(0, rowLimit);
  const more = moreLine(drawn.length, rows.length);
  // The first row "Show all" revealed: focusable only so the keyboard can
  // be put there, never a Tab stop of its own.
  const revealed = (idx) => idx === revealFrom ? ' data-revealed tabindex="-1"' : "";
  $("#count").textContent = `${rows.length} / ${items.length} items`
    + (relevanceActive() ? " · by relevance" : "");
  const narrow = isNarrow();
  $("#table-wrap").hidden = narrow;
  $("#card-list").hidden = !narrow;
  // A blank table used to be indistinguishable from a failed load, from a
  // catalog nothing had been fetched into, and from a filter that matched
  // nothing. The line says which -- inside the scroller either way, so it
  // stands where the rows would be rather than above them.
  // Spoken as well as drawn. Written on every render, empty included, so
  // the region never holds a sentence that is no longer true.
  const status = $("#table-status");
  if (status) status.textContent = rows.length === 0 ? emptyStateText() : "";
  if (rows.length === 0) {
    const text = esc(emptyStateText());
    // colspan 99 rather than the column count: the count is declared in
    // index.html's <thead> and would have to be kept in step here, and a
    // colspan larger than the row is clamped, not an error.
    $("#catalog tbody").innerHTML = narrow
      ? "" : `<tr class="table-empty"><td colspan="99">${text}</td></tr>`;
    $("#card-list").innerHTML = narrow
      ? `<p class="list-empty">${text}</p>` : "";
  } else if (narrow) {
    $("#catalog tbody").innerHTML = "";
    $("#card-list").innerHTML = renderCards(drawn, revealed)
      + (more ? `<p class="list-more">${more}</p>` : "");
  } else {
    $("#card-list").innerHTML = "";
    $("#catalog tbody").innerHTML = drawn.map((i, idx) => i.id === editingId ? `<tr${revealed(idx)}>
    <td>${i.cover_path ? `<img src="/${i.cover_path}" alt="" loading="lazy">` : ""}</td>
    <td><strong>${esc(i.name)}</strong><br>
      <input class="edit-field edit-url" data-f="source_url" type="url"
             value="${esc(i.source_url)}" placeholder="Source URL"><br>
      <button class="edit-save" data-id="${i.id}">Save</button>
      <button class="edit-cancel">Cancel</button></td>
    <td>${i.type}</td>
    <td>${statusSelect(i)}</td>
    ${chipCell("genre")}
    <td><input class="edit-field" data-f="series" value="${esc(i.series)}">
      <input class="edit-field edit-num" data-f="series_number" type="number"
             step="any" value="${i.series_number ?? ""}" placeholder="#"></td>
    ${chipCell("authors")}
    ${chipCell(personField(i))}
    <td>${esc(i.publisher)}</td>
    <td>${i.bundles.map(b => `<a class="tag tag-link" href="${esc(b.url)}" target="_blank" rel="noopener" title="${esc(b.name)}">${esc(bundleLabel(b.name))}</a>`)
          .join("")}</td>
    <td>${i.external_rating ? `${i.external_rating.toFixed(1)} <small>(${
          i.rating_source})</small>` : ""}</td>
    <td class="stars">${stars(i)}</td>
    ${chipCell("user_tags")}
    <td><textarea class="edit-comment" rows="2"
                  placeholder="Notes...">${esc(i.user_comment)}</textarea></td>
  </tr>` : `<tr${revealed(idx)}>
    <td>${i.cover_path ? `<img src="/${i.cover_path}" alt="" loading="lazy">` : ""}</td>
    <td><strong>${highlight(i.name, matchSpans.get(i.id))}</strong>${nameExtras(i)}</td>
    <td>${i.type}</td>
    <td>${statusCell(i)}</td>
    <td>${tagBadges(i.genre)}</td>
    <td>${esc(i.series)}${i.series_number ? " #" + i.series_number : ""}</td>
    <td>${tagBadges(i.authors)}</td>
    <td>${tagBadges(person(i))}</td>
    <td>${esc(i.publisher)}</td>
    <td>${i.bundles.map(b => `<a class="tag tag-link" href="${esc(b.url)}" target="_blank" rel="noopener" title="${esc(b.name)}">${esc(bundleLabel(b.name))}</a>`)
          .join("")}</td>
    <td>${i.external_rating ? `${i.external_rating.toFixed(1)} <small>(${
          i.rating_source})</small>` : ""}</td>
    <td class="stars">${stars(i)}</td>
    <td>${tagBadges(i.user_tags)}</td>
    <td class="user-comment">${esc(i.user_comment)}</td>
  </tr>`).join("")
      + (more ? `<tr class="table-more"><td colspan="99">${more}</td></tr>` : "");
  }
  wireTagInputs();
  renderBulkBar();
  renderExportButton();
  renderSortIndicators();
  // The panel describes these rows, so it is part of drawing them rather
  // than something a mutation remembers to refresh afterwards.
  refreshStats(rows);
}

// Reflect the current sort onto the static header cells (the <thead> is not
// rebuilt by render()). querySelectorAll returns [] under the test harness,
// so this is a harmless no-op there.
function renderSortIndicators() {
  for (const th of document.querySelectorAll("#catalog th[data-sort]")) {
    const active = th.dataset.sort === sortKey;
    th.classList.toggle("sorted", active);
    th.setAttribute("aria-sort", ariaSortFor(th.dataset.sort));
    const ind = th.querySelector(".sort-ind");
    // Suppressed while relevance orders the rows: a lit arrow would
    // claim the table is sorted by a column it is not sorted by.
    if (ind) ind.textContent = active && !relevanceActive()
      ? (sortAsc ? " ▲" : " ▼") : "";
  }
}

// Escaped HTML with the matched ranges wrapped in <mark>.
//
// Escaping order is load-bearing. The tempting form -- esc(text) then
// replace() -- escapes first and matches second, so spans computed
// against the raw string land at the wrong offsets in the escaped one,
// and a title containing "&" corrupts. Splitting on raw indices and
// escaping each piece is the only correct order. <mark> is generated
// here, never interpolated from data.
function highlight(text, spans) {
  if (!spans || !spans.length) return esc(text);
  let out = "", at = 0;
  for (const [start, end] of spans) {
    if (start < at) continue;            // overlapping span: first one wins
    out += esc(text.slice(at, start))
        + `<mark>${esc(text.slice(start, end))}</mark>`;
    at = end;
  }
  return out + esc(text.slice(at));
}

// ---- Statistics panel -------------------------------------------------
// Six sections -- type, ratings, reading status, enrichment, gaps, genres
// -- counted in the browser by stats.js over the rows the table is
// showing. The counts were served by /api/stats and covered the whole
// catalog, which made a row's number a promise the jump could not keep:
// with a filter already active, clicking "E-books 6" kept that filter and
// could land on an empty table. SECTION_FILTERS sets one control and
// clears nothing, so only counts over the visible rows are answerable.
//
// That means stats.py is no longer the only implementation. The two are
// held together by a test rather than by the arrangement -- see
// test_the_browser_counts_agree_with_stats_py, which counts one fixture
// both ways. /api/stats still serves the whole-catalog report for the
// CLI parity tests and the probe battery; the viewer no longer reads it.

// Which filter a row of each section applies. This is the ONLY thing the
// viewer knows about the sections. Keys come from stats.py's SECTIONS.
const SECTION_FILTERS = {
  type:       (row) => { $("#f-type").value = TYPE_VALUES[row]; },
  rating:     (row) => { $("#f-rating").value = row.replace("★", ""); },
  enrichment: (row) => { $("#f-flag").value = ENRICHMENT_VALUES[row]; },
  gaps:       (row) => { $("#f-flag").value = GAP_VALUES[row]; },
  status:     (row) => { setOnlyStatus(STATUS_VALUES[row]); },
  genre:      (row) => { chipFilters.genre.chips = [row]; renderFilterChips(); },
};

// The panel sends back the row LABEL, so each section needs the label ->
// value mapping its control expects. Mirrors stats.py's vocabularies.
const TYPE_VALUES = {"E-books": "ebook", "Audiobooks": "audiobook",
                     "Comics": "comic", "Music/Soundtracks": "music",
                     "Android apps": "android"};
const ENRICHMENT_VALUES = {"Matched": "matched",
                           "Low confidence": "low_confidence",
                           "Unmatched": "unmatched", "Pending": "pending"};
const GAP_VALUES = {"Unrated": "unrated", "No cover": "nocover",
                    "No source URL": "nourl"};
const STATUS_VALUES = {"Want to read": "want_to_read", "Unread": "unread",
                       "Reading": "reading", "Read": "read", "DNF": "dnf"};

function setOnlyStatus(value) {
  statusFilter.clear();
  statusFilter.add(value);
  // The chips live in the header, which render() never rebuilds, so a jump
  // that changes the set has to re-sync their classes by hand -- including
  // lighting the one it selected, not just clearing the others.
  for (const chip of document.querySelectorAll(".status-chip"))
    chip.classList.toggle("on", chip.dataset.status === value);
}

const GENRE_PREVIEW = 15;
let statsData = null;
let statsOpen = false, genresShowAll = false, tagEditMode = false;

// `rows` is render()'s own visible() result, passed in so the filtering
// is not repeated; callers that only mutated an item omit it.
//
// The filtering can itself throw -- one item with a missing field is how
// the page once went blank -- and load() runs the renderers separately so
// that one failure cannot take out the rest. Counting the whole catalog
// is the degraded answer there: it is what the panel showed before #43,
// and a page that still comes up beats a correct panel nobody sees.
function refreshStats(rows) {
  let counted = rows;
  if (!counted) {
    try { counted = visible(); } catch (err) { counted = items; }
  }
  statsData = statsReport(counted);
  renderStats();
}

function renderStats() {
  const panel = $("#stats-panel");
  // Re-run on every toggle, so it has to cope with not having fetched yet
  // rather than throwing and blanking the panel.
  panel.hidden = !statsData || !statsData.total;
  if (panel.hidden) return;
  const blocks = statsData.sections.map((s) => {
    const genre = s.key === "genre";
    const shown = genre && !genresShowAll
      ? s.rows.slice(0, GENRE_PREVIEW) : s.rows;
    const rows = shown.map((r) => statRow(s.key, r, genre)).join("");
    const more = genre && !genresShowAll && s.rows.length > GENRE_PREVIEW
      ? `<button class="stat-show-all">Show all ${s.rows.length}</button>` : "";
    // The LAN viewer has no tag routes: its panel offers nothing to edit.
    const edit = genre && !READ_ONLY
      ? `<button class="stat-edit-tags">${tagEditMode ? "Done" : "Edit tags"}</button>`
      : "";
    return `<section class="stat-block stat-${s.key}">
      <h3>${esc(s.label)}${edit}</h3>
      <table><tbody>${rows}</tbody></table>${more}</section>`;
  }).join("");
  panel.innerHTML = `<details${statsOpen ? " open" : ""}>
    <summary>${statsData.total} item${statsData.total === 1 ? "" : "s"} — overview</summary>
    <div id="stats-grid">${blocks}</div></details>`;
  panel.querySelector("details").addEventListener("toggle",
    (ev) => { statsOpen = ev.target.open; });
}

function statRow(key, row, genre) {
  // A zero row renders greyed and unclickable, so the panel doubles as a
  // "this category is clean" confirmation rather than hiding the row.
  const cell = row.count
    ? `<button class="stat-jump" data-section="${esc(key)}"
        data-row="${esc(row.label)}">${row.count}</button>`
    : `<span class="stat-zero">0</span>`;
  const manage = genre && tagEditMode && !READ_ONLY
    ? `<td><input class="genre-rename-input" placeholder="rename to..." size="18">
        <button class="genre-rename" data-tag="${esc(row.label)}">Rename</button>
        <button class="genre-delete" data-tag="${esc(row.label)}">Delete</button></td>`
    : "";
  return `<tr><td>${esc(row.label)}</td>
    <td class="stat-count">${cell}</td>${manage}</tr>`;
}

document.addEventListener("click", async (ev) => {
  const el = ev.target;
  if (el.classList.contains("star")) {
    const id = +el.dataset.id, n = +el.dataset.n;
    const item = items.find(i => i.id === id);
    await applyRating(id, n, item.my_rating === n ? null : n);  // click current to clear
  } else if (el.classList.contains("edit")) {
    editingId = +el.dataset.id;
    const it = items.find(i => i.id === editingId);
    editingTags = {genre: [...it.genre], authors: [...it.authors],
                   user_tags: [...it.user_tags]};
    editingTags[personField(it)] = [...person(it)];
    render();
  } else if (el.classList.contains("show-all")) {
    showAllRows();
  } else if (el.classList.contains("edit-cancel")) {
    editingId = null;
    editingTags = null;
    render();
  } else if (el.id === "sidebar-toggle") {
    toggleSidebar();
  } else if (el.classList.contains("active-x")) {
    // Clearing from the summary strip. Each kind clears the control the
    // chip stands for, so the sidebar agrees whether it is open or not.
    const k = el.dataset.kind;
    if (k === "select") {
      $(`#${el.dataset.target}`).value = "";
    } else if (k === "status") {
      statusFilter.delete(el.dataset.status);
      document.querySelector(`.status-chip[data-status="${el.dataset.status}"]`)
        ?.classList.remove("on");
    } else if (k === "chip") {
      chipFilters[el.dataset.field].chips.splice(+el.dataset.i, 1);
      renderFilterChips();
    } else if (k === "text") {
      chipFilters[el.dataset.field].text = "";
      const input = document.querySelector(
        `.chip-filter[data-field="${el.dataset.field}"] input`);
      if (input) input.value = "";
    } else if (k === "search") {
      $("#search").value = "";
      relevanceSort = false;
    }
    render();
  } else if (el.closest && el.closest(".sheet-status")) {
    const b = el.closest(".sheet-status");
    await setSheetStatus(+b.dataset.id, b.dataset.s);
  } else if (el.closest && el.closest(".sheet-star, .sheet-star-clear")) {
    const b = el.closest(".sheet-star, .sheet-star-clear");
    await setSheetRating(+b.dataset.id, +b.dataset.n);
  } else if (el.closest && (el.closest(".sheet-done") || el.id === "sheet-scrim")) {
    closeSheet();
  } else if (el.closest && el.closest("[data-open]")
             && !el.closest(".card-link")) {
    // The bundle links inside a card stay links: tapping one should open
    // the bundle page, not the editor.
    openSheet(+el.closest("[data-open]").dataset.open);
  } else if (el.classList.contains("clear-all")) {
    clearAllFilters();
    render();
  } else if (el.classList.contains("chip-x")) {
    const f = chipFilters[el.dataset.field];
    f.chips.splice(+el.dataset.i, 1);
    renderFilterChips();
    render();
  } else if (el.classList.contains("stat-jump")) {
    // Setting .value does not fire the select's input listener, so
    // re-render by hand -- the overview-to-filter jump.
    SECTION_FILTERS[el.dataset.section](el.dataset.row);
    render();
  } else if (el.classList.contains("bundle-jump")) {
    // Jump to the owned row, so "you may own part of this" becomes one
    // click to WHICH part. Sets relevanceSort like the search box's own
    // input listener does, so the jumped-to row ranks first.
    //
    // The row is in Library and the click came from Bundles, so this
    // navigates as well as filters. Setting the hash rather than calling
    // showSection puts the jump in history, so Back returns to the bundle
    // the question was asked about.
    $("#search").value = el.textContent.trim();
    relevanceSort = true;
    location.hash = "#/library";
    render();
  } else if (el.classList.contains("edition-jump")) {
    // The sibling is by definition a DIFFERENT type, so an active type
    // filter would hide exactly the row being jumped to. Clearing it is
    // the whole reason this is more than filling the search box.
    $("#f-type").value = "";
    $("#search").value = el.dataset.name;
    relevanceSort = true;
    render();
  } else if (el.classList.contains("bundle-series-jump")) {
    // One control for the whole run, not one per volume: a 26-volume
    // series would otherwise emit 26 buttons. The type filter is cleared
    // for the same reason the edition jump clears it -- a series can span
    // comic and ebook, and an active filter would hide half the run.
    // Setting the hash puts the jump in history, like the bundle jump
    // above, so Back returns to the bundle the question was asked about.
    $("#f-type").value = "";
    $("#search").value = el.dataset.series;
    relevanceSort = true;
    location.hash = "#/library";
    render();
  } else if (el.classList.contains("stat-show-all")) {
    genresShowAll = true;
    renderStats();
  } else if (el.classList.contains("stat-edit-tags")) {
    tagEditMode = !tagEditMode;
    renderStats();
  } else if (el.id === "export") {
    // No armOrFire: exporting mutates nothing, so a confirmation click
    // would be pure friction.
    await downloadExport();
  } else if (el.classList.contains("col-check")) {
    toggleColumn(el.dataset.col, el.checked);
  } else if (el.id === "col-all" || el.id === "col-none") {
    exportColumns = new Set(el.id === "col-all" ? EXPORT_COLUMNS : []);
    saveColumnSelection();
    renderColumnPicker();
    renderExportButton();
  } else if (el.classList.contains("filter-mode")) {
    const f = chipFilters[el.dataset.field];
    f.mode = f.mode === "all" ? "any" : "all";
    renderFilterChips();
    render();
  } else if (el.classList.contains("status-chip")) {
    // The chips live in the header, which render() never rebuilds, so
    // toggling the class on the clicked button directly is safe.
    const s = el.dataset.status;
    if (statusFilter.has(s)) statusFilter.delete(s); else statusFilter.add(s);
    el.classList.toggle("on");
    render();
  } else if (el.classList.contains("tag-x")) {
    editingTags[el.dataset.f].splice(+el.dataset.i, 1);
    render();
  } else if (el.classList.contains("edit-save")) {
    const row = el.closest("tr"), id = el.dataset.id;
    const fields = {};
    for (const inp of row.querySelectorAll(".edit-field"))
      fields[inp.dataset.f] = inp.value.trim();
    // user_tags is deliberately held back from /edit: it is not in
    // EDITABLE_FIELDS, and /edit would snapshot the row and mark it
    // hand-edited. Same reason the note uses .edit-comment, not
    // .edit-field -- the selector above must not sweep it up.
    const {user_tags, ...enrichmentTags} = editingTags;
    Object.assign(fields, enrichmentTags);
    const comment = row.querySelector(".edit-comment").value.trim();

    if (shouldPostEnrichmentEdit(items.find(i => i.id === +id), fields)) {
      const resp = await post(`/api/items/${id}/edit`, {fields});
      if (!resp.ok) {
        alert((await resp.json()).error || "Could not save.");
        return;
      }
    }
    await post(`/api/items/${id}/user-tags`, {tags: user_tags});
    await post(`/api/items/${id}/comment`, {comment});
    editingId = null;
    editingTags = null;
    await load();
  } else if (el.classList.contains("revert")) {
    armOrFire(el, async () => {
      await post(`/api/items/${el.dataset.id}/revert`);
      await load();
    });
  } else if (el.classList.contains("redo")) {
    armOrFire(el, async () => {
      await post(`/api/items/${el.dataset.id}/reopen`);
      await load();
    });
  } else if (el.classList.contains("override")) {
    // No armOrFire here: queuing changes nothing until an enrich run, and
    // the badge plus the "Queued for re-enrich" filter make it reversible.
    const row = items.find(i => i.id === Number(el.dataset.id));
    await post(`/api/items/${el.dataset.id}/override`,
               {override: !(row && row.override)});
    await load();
  } else if (el.classList.contains("genre-rename")) {
    const input = el.closest("tr").querySelector(".genre-rename-input");
    const newName = input.value.trim();
    if (!newName || newName === el.dataset.tag) return;
    armOrFire(el, async () => {
      const resp = await post("/api/genres/rename",
                              {old: el.dataset.tag, new: newName});
      if (!resp.ok) alert((await resp.json()).error || "Could not rename.");
      await load();
    });
  } else if (el.classList.contains("genre-delete")) {
    armOrFire(el, async () => {
      const resp = await post("/api/genres/delete", {tag: el.dataset.tag});
      if (!resp.ok) alert((await resp.json()).error || "Could not delete.");
      await load();
    });
  } else if (el.id === "bulk-add") {
    await runBulk(el, "add");
  } else if (el.id === "bulk-remove") {
    await runBulk(el, "remove");
  } else if (el.id === "bulk-undo") {
    await undoBulk();
  } else if (el.closest("#catalog th[data-sort]")) {
    const th = el.closest("#catalog th[data-sort]");
    relevanceSort = false;              // an explicit sort beats relevance
    sortAsc = sortKey === th.dataset.sort ? !sortAsc : true;
    sortKey = th.dataset.sort;
    render();
  }
});
// Per-row status dropdowns fire `change`, not `click`, so they get their
// own delegated listener. read_status is a user-owned field: like rating,
// it posts to its own route and never touches /edit or the hand-edit flag.
document.addEventListener("change", async (e) => {
  const el = e.target;
  if (!el.classList || !el.classList.contains("read-status-select")) return;
  const id = +el.dataset.id, status = el.value;
  await post(`/api/items/${id}/read-status`, {status});
  const item = items.find(i => i.id === id);
  if (item) item.read_status = status;
  render();   // which redraws the panel too, in step with the table
});
// The card is a button, so it answers Enter and Space like one; Escape
// closes the sheet, which a dialog has to.
document.addEventListener("keydown", (ev) => {
  // Stars first: on a phone they sit inside the card, whose own Enter
  // would open the sheet rather than rate the row.
  const star = ev.target.closest?.(".star[data-n]");
  if (star) {
    const id = +star.dataset.id;
    const move = ratingForKey(ev.key, +star.dataset.n,
                              items.find(i => i.id === id)?.my_rating ?? null);
    if (!move) return;          // not ours -- Tab still leaves the group
    ev.preventDefault();
    applyRating(id, move.focus, move.rating);
    return;
  }
  if (ev.key === "Escape" && openSheetId !== null) { closeSheet(); return; }
  if (ev.key !== "Enter" && ev.key !== " ") return;
  const card = ev.target.closest?.("[data-open]");
  if (!card) return;
  ev.preventDefault();
  openSheet(+card.dataset.open);
});

// One render per frame, not one per keystroke. render() rebuilds the whole
// <tbody> through innerHTML -- measured at ~70us a row against an invented
// catalog, so a few thousand rows put a single keystroke at 100-200ms and a
// burst of six queues six full rebuilds. Coalescing costs the burst one.
// (The filtering itself is not the price: fuzzy scoring the whole catalog
// measured under 2ms. See #52.)
//
// The timer is not belt-and-braces. requestAnimationFrame does not fire in
// a hidden or throttled tab -- the same trap openSheet documents above --
// and a frame-only debounce would leave the table showing the result of a
// query the box no longer holds. Whichever arrives first renders and
// cancels the other.
let renderPending = null;
let renderToken = 0;
function scheduleRender() {
  if (renderPending) return;
  // The loser of the race checks its own token rather than trusting that
  // it was cancelled: cancelAnimationFrame may not exist, and a timer
  // already queued can still run after its clearTimeout. Without this a
  // stale callback renders a second time, once per keystroke.
  const token = ++renderToken;
  const fire = () => {
    if (!renderPending || renderPending.token !== token) return;
    const {frame, timer} = renderPending;
    renderPending = null;
    globalThis.cancelAnimationFrame?.(frame);
    clearTimeout(timer);
    render();
  };
  // A frame is ~16ms; 32 gives the frame two chances to win before the
  // timer steps in, so a visible tab renders on a frame and not on a timer.
  renderPending = {
    token,
    frame: globalThis.requestAnimationFrame?.(fire),
    timer: setTimeout(fire, 32),
  };
}

for (const id of ["#f-type", "#f-flag", "#f-rating"])
  $(id).addEventListener("input", scheduleRender);
// Typing a query re-asserts relevance ordering; a header click clears it.
$("#search").addEventListener("input", () => {
  relevanceSort = true;
  scheduleRender();
});

// The bulk bar lives outside the table, so the table's innerHTML rebuilds
// leave it alone; only its own input and re-renders refresh it.
$("#bulk-tag").addEventListener("input", renderBulkBar);
Autocomplete.attach(
  $("#bulk-tag"),
  () => vocab("user_tags"),
  (value, viaSuggestion) => {
    if (viaSuggestion) $("#bulk-tag").value = value;
    renderBulkBar();
  },
  () => tagCounts(i => i.user_tags));

// Filter-bar chips live outside the table, so the table's innerHTML
// rebuilds never disturb them; only chip/toggle/input events re-render.
function renderFilterChips() {
  for (const [field, f] of Object.entries(chipFilters)) {
    const wrap = document.querySelector(`.chip-filter[data-field="${field}"]`);
    for (const el of wrap.querySelectorAll(".tag, .filter-mode")) el.remove();
    const input = wrap.querySelector("input");
    input.insertAdjacentHTML("beforebegin", f.chips.map((c, idx) =>
      `<span class="tag">${esc(c)}<button class="tag-x chip-x"
             data-field="${field}" data-i="${idx}"
             title="Remove">&times;</button></span>`).join(""));
    // With 0-1 chips the all/any distinction cannot change the result;
    // for a scalar field (one value per item) "all" is unsatisfiable,
    // so the toggle could only ever empty the table.
    if (f.chips.length >= 2 && !f.scalar)
      input.insertAdjacentHTML("afterend",
        `<button class="filter-mode" data-field="${field}"
                 title="Item must match all chips, or any chip">${f.mode}</button>`);
  }
}

function wireChipFilter(field) {
  const f = chipFilters[field];
  const input = document.querySelector(`.chip-filter[data-field="${field}"] input`);
  if (!f.textOnly) Autocomplete.attach(
    input,
    () => [...new Set(items.flatMap(f.accessor))].sort()
            .filter(v => !f.chips.includes(v)),
    (value, viaSuggestion) => {
      if (viaSuggestion) {
        f.chips.push(value);
        f.text = "";
        input.value = "";
        renderFilterChips();
      } else {
        f.text = value.toLowerCase();
      }
      render();
    },
    () => tagCounts(f.accessor));
  input.addEventListener("input", () => {
    f.text = input.value.trim().toLowerCase();
    render();
  });
}
for (const field of Object.keys(chipFilters)) wireChipFilter(field);

// Title suggestions for the search box: no chips and no counts, since
// titles are one-per-item. Picking one just fills the box, and the
// name filter finds the row. The length guard keeps one stray keystroke
// from opening a list drawn from every title in the catalog.
Autocomplete.attach(
  $("#search"),
  () => $("#search").value.trim().length < 2 ? []
        : [...new Set(items.map(i => i.name))].sort(),
  (value, viaSuggestion) => {
    if (viaSuggestion) $("#search").value = value;
    render();
  });

// Before load(), so the first renderExportButton() already knows whether
// the stored selection leaves anything to download.
loadColumnSelection();
renderColumnPicker();

// Closing on an outside click is the one behaviour <details> does not give
// for free, and without it the panel stays open over the table.
document.addEventListener("click", (ev) => {
  const picker = $("#column-picker");
  if (picker?.open && !picker.contains(ev.target)) picker.open = false;
});

// The stored collapse state has to reach the DOM before the first paint,
// or the sidebar flashes open on every load for someone who keeps it shut.
applySidebar();
