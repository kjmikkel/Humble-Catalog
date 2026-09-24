// The Keys section: Humble store keys whose game is in no imported
// library. Everything here reads /api/keys and nothing else -- the report
// is computed server-side by keys.py so this panel and the CLI cannot
// disagree, which is the same arrangement the statistics panel uses.
//
// Deliberately does NOT reuse catalog.js's chip-filter registry, sort or
// fuzzy search. All three are bound to the shared `items` array, and two
// views needing different column sets is the whole reason sections exist.

// The chips, in display order. The first three are the states the server
// reports; `matched` is absent on purpose, since the server never sends
// it. `hidden` is a display-only fourth, derived from a row's hidden_at:
// on the server hidden stays an annotation and `counts` keeps
// partitioning every key, so this bucket does not travel back across the
// route.
const KEY_STATES = [
  {state: "unredeemed",  label: "Not in a library"},
  {state: "uncertain",   label: "Near match"},
  {state: "uncheckable", label: "No importer"},
  {state: "hidden",      label: "Hidden"},
];

let keyRows = [], keyCounts = {}, keyLibraries = {}, keyTotal = 0;
// uncheckable is off by default: for those stores "not in any library" is
// unfalsifiable, so leaving them in would make the list mostly caveat.
// hidden is off because being off is the entire point of hiding.
let keyStates = new Set(["unredeemed", "uncertain"]);

// A row's chip: its server state unless the owner has hidden it. One
// function reconciles the server's three states with the viewer's four
// chips. An earlier design made hidden a second filter axis, with its own
// boolean and a pool indirection between the two; it bought "hidden near
// matches only", which nothing needs across a handful of rows, and cost a
// chip whose count did not match what clicking it delivered.
const displayState = (r) => (r.hidden_at ? "hidden" : r.state);

const keysExpiring = () =>
  keyRows.filter((r) => r.expires && !r.expired && !r.hidden_at).length;

const searchedKeys = () => {
  const query = $("#keys-search").value.trim().toLocaleLowerCase();
  return keyRows.filter((r) =>
    [r.product, r.store, r.key_type_label].some(
      (value) => (value || "").toLocaleLowerCase().includes(query)));
};

const shownKeys = () => searchedKeys().filter((r) => keyStates.has(displayState(r)));

// Counted here, not read from keyCounts: keyCounts partitions every key,
// matched and hidden included, so a chip reading "Not in a library 624"
// would deliver fewer than 624 once hidden rows move to their own bucket.
// That is the statistics panel's "Unmatched 4 jumped and returned 8" bug.
// Counting by displayState makes the four chips partition the reported
// rows, so a count equals what clicking it shows, by construction.
function keyChipCounts() {
  const counts = {};
  for (const s of KEY_STATES) counts[s.state] = 0;
  for (const r of searchedKeys()) counts[displayState(r)] += 1;
  return counts;
}

function setKeyStates(states) {
  keyStates = new Set(states);
}

async function loadKeys() {
  const data = await (await fetch("/api/keys")).json();
  keyRows = data.rows || [];
  keyCounts = data.counts || {};
  keyLibraries = data.libraries || {};
  keyTotal = data.total || 0;
  renderKeys();
}

// Whole days from an ISO timestamp, so a row's urgency is computed in the
// browser rather than frozen at whatever moment the page was loaded.
// "today" rather than "in 0 days", matching what keys.py prints.
function keyWhen(row) {
  if (!row.expires) return "";
  if (row.expired) return "expired";
  const days = Math.floor((new Date(row.expires) - Date.now()) / 86400000);
  return days <= 0 ? "today" : `in ${days} days`;
}

function renderKeys() {
  const rows = shownKeys();
  const counts = keyChipCounts();
  const chips = KEY_STATES.map((s) => `<button class="key-chip${
    keyStates.has(s.state) ? " on" : ""}" data-state="${s.state}">${
    esc(s.label)} ${counts[s.state] || 0}</button>`).join("");
  const libraries = Object.entries(keyLibraries).map(
    ([store, info]) => `${esc(store)} ${info.count} (imported ${
      esc((info.imported_at || "").slice(0, 10))})`).join(", ");
  let emptyMessage = "No keys match these filters. Try another state above.";
  if (!keyTotal) {
    emptyMessage = "No Humble keys have been fetched yet.";
  } else if (!keyRows.length) {
    emptyMessage = "All reported keys match an imported game library.";
  }
  const importHint = libraries ? "" : READ_ONLY
    ? " Ask the catalog owner to import game libraries to compare ownership."
    : ' Import game libraries from <a href="#/tasks">Tasks</a> to compare ownership.';
  const fetchHint = !keyTotal && !READ_ONLY
    ? ' Fetch new bundles from <a href="#/tasks">Tasks</a> to load your keys.' : "";
  $("#keys-panel").innerHTML = `
    <p class="keys-summary">${keyTotal} keys - ${keyCounts.matched || 0} in a
      library, ${rows.length} shown.
      Matching is by title and <strong>approximate</strong>; a revealed key
      was only displayed, which is not the same as activated.</p>
    <div id="key-chips">${chips}</div>
    ${libraries ? `<p class="keys-libraries">Libraries: ${libraries}</p>` : ""}
    ${!rows.length ? `<p class="section-empty">${emptyMessage}${fetchHint}${importHint}</p>` : ""}
    <div id="key-table-wrap"${rows.length ? "" : " hidden"}>
    <table id="key-table"><thead><tr>
      <th>Product</th><th>Store</th><th>Bundle</th><th>Purchased</th>
      <th>Expires</th><th>Revealed</th><th>State</th><th>Hidden</th>
    </tr></thead><tbody>${rows.map((r) => `<tr class="key-${r.state}${
      r.hidden_at ? " key-is-hidden" : ""}">
      <td>${esc(r.product || "")}${r.near_match
        ? ` <span class="key-near">~ ${esc(r.near_match.owned_title)} (${
            r.near_match.score.toFixed(2)})?</span>` : ""}</td>
      <td>${esc(r.key_type_label || "")}</td>
      <td>${r.bundle_url
        ? `<a class="tag tag-link" href="${esc(r.bundle_url)}" target="_blank"
             rel="noopener">${esc(r.bundle || "")}</a>`
        : esc(r.bundle || "")}</td>
      <td>${esc((r.purchased_at || "").slice(0, 10))}</td>
      <td>${esc(keyWhen(r))}</td>
      <td>${r.revealed ? "yes" : "no"}</td>
      <td>${esc((KEY_STATES.find((s) => s.state === r.state) || {}).label
                || r.state)}</td>
      <td class="key-actions-cell">${
        r.hidden_at ? esc(r.hidden_at.slice(0, 10)) + " " : ""}${READ_ONLY ? "" : `<button
        class="key-hide" data-gamekey="${esc(r.gamekey)}"
        data-machine="${esc(r.machine_name)}">${
        r.hidden_at ? "unhide" : "hide"}</button>`}</td>
    </tr>`).join("")}</tbody></table>
    </div>`;
}

// Posts, then patches the row in place. Deliberately NOT a loadKeys()
// refetch: hiding changes one field on one row, so refetching and
// reclassifying every key to learn that is wasteful at the ~0.33s the
// report now costs, as it was at the ~2.5s it used to. Same trade the
// statistics panel made -- touch the mutation call site rather than
// reload everything.
async function toggleKeyHidden(gamekey, machine) {
  const row = keyRows.find(
    (r) => r.gamekey === gamekey && r.machine_name === machine);
  if (!row) return;
  const path = row.hidden_at ? "/api/keys/unhide" : "/api/keys/hide";
  const resp = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({gamekey, machine_name: machine}),
  });
  if (!resp.ok) return;
  row.hidden_at = row.hidden_at ? null : new Date().toISOString();
  renderKeys();
  // Badges are computed by load() in app.js, which does not run again
  // here, so the one section that changed refreshes its own count. A hide
  // that silences the row but leaves the badge lit has not stopped the
  // row reappearing.
  pending.keys = keysExpiring();
  renderBadges();
}

// One delegated listener rather than one per chip, because renderKeys()
// rebuilds the whole panel through innerHTML and per-chip listeners would
// be detached on every redraw.
$("#keys-panel").addEventListener("click", (ev) => {
  const hide = ev.target.closest?.(".key-hide");
  if (hide) {
    toggleKeyHidden(hide.dataset.gamekey, hide.dataset.machine);
    return;
  }
  const chip = ev.target.closest?.(".key-chip");
  if (!chip) return;
  const state = chip.dataset.state;
  if (keyStates.has(state)) keyStates.delete(state); else keyStates.add(state);
  renderKeys();
});

$("#keys-search").addEventListener("input", renderKeys);
