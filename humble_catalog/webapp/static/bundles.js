// The Bundles section: paste a HumbleBundle URL, get per-tier owned/new
// counts. Read-only and unpersisted -- it answers "should I buy this",
// so it holds no state worth surviving a reload.

// ---- Bundle preview panel ---------------------------------------------
// Paste a live bundle URL, get a per-tier count of owned versus new. The
// counting lives only in bundle_preview.py, so the numbers all arrive
// with the data and there is nothing here to drift from the CLI.
//
// Unlike the statistics panel this is fetch-on-demand rather than
// rendered at page load, so it needs no refresh-after-mutation wiring: it
// holds no state that can go stale.

let bundlePreview = null, bundlePreviewError = null;
let bundlePreviewOpen = true;

const CURRENCY_SYMBOLS = {EUR: "€", USD: "$", GBP: "£",
                          CAD: "CA$", AUD: "A$"};

function money(amount, currency) {
  const symbol = CURRENCY_SYMBOLS[currency];
  return symbol ? symbol + amount.toFixed(2)
                : `${currency} ${amount.toFixed(2)}`;
}

// ---- Shared by both checks --------------------------------------------

// A report or an error, never a throw. Parsing used to happen before any
// drawing, so a reply that was not JSON (a 500 page) or a request that
// never arrived (a stopped server) threw past the renderer, and the panel
// kept the PREVIOUS result under the newly pasted URL (#88). A wrong
// answer that looks right is worse than any error message.
async function fetchReport(url, body, fallback) {
  let resp;
  try {
    resp = await post(url, body);
  } catch (err) {
    return {error: "could not reach the viewer -- is it still running?"};
  }
  let payload = null;
  try {
    payload = await resp.json();
  } catch (err) {
    // Not JSON: an HTML error page. Its status is all it can tell us.
  }
  if (resp.ok && payload) return {report: payload};
  return {error: (payload && payload.error)
                 || `${fallback} (the viewer answered ${resp.status})`};
}

// Runs `work` with its button disabled and saying so (#89). A Choice
// check drives a logged-in fetch and takes seconds, and with no sign of
// it the page looked dead -- and a second click sent a second request.
// The disabled button is the lock: a click on it is not delivered, and a
// call that arrives anyway (Enter in the URL box) is dropped here.
async function whileChecking(selector, label, work) {
  const btn = $(selector);
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    await work();
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function previewBundle(url) {
  // POST, never GET: a bundle URL in a query string reaches access logs
  // and browser history.
  await whileChecking("#bundle-go", "Check bundle", async () => {
    const {report, error} = await fetchReport(
      "/api/bundle-preview", {url}, "could not read that bundle");
    bundlePreview = report || null;
    bundlePreviewError = error || null;
    renderBundlePreview();
    // Only a check that worked is worth one click to repeat.
    if (report) {
      rememberBundle(url, report.name);
      renderRecentBundles();
    }
  });
}

// ---- Recently checked bundles (#94) -----------------------------------
// Comparing several live bundles meant re-pasting each URL. The last few
// successful checks are kept as one-click re-checks. Bundle URLs and names
// are public, and localStorage keeps them out of the address bar and the
// browser history -- the reason the preview is a POST.
//
// Not on the LAN viewer, for #44's reason: storage on a paired phone is
// not local to the machine that holds the library. Every access is
// guarded, because a private window or blocked site data throws, and the
// answer to that is no list, never an error.
const RECENT_BUNDLES_KEY = "hc-recent-bundles";
const RECENT_BUNDLES_MAX = 5;

function loadRecentBundles() {
  if (READ_ONLY) return [];
  let raw;
  try {
    raw = JSON.parse(localStorage.getItem(RECENT_BUNDLES_KEY));
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  // Kept entry by entry: whatever else is stored, only an http(s) URL is
  // ever put into a button that re-checks it.
  return raw.filter((r) => r && typeof r === "object"
    && typeof r.url === "string" && /^https?:\/\//i.test(r.url)
    && typeof r.name === "string" && typeof r.checked === "string")
    .slice(0, RECENT_BUNDLES_MAX);
}

function saveRecentBundles(list) {
  try {
    if (list.length) localStorage.setItem(RECENT_BUNDLES_KEY, JSON.stringify(list));
    else localStorage.removeItem(RECENT_BUNDLES_KEY);
  } catch {
    // Blocked storage: the list simply is not kept.
  }
}

function rememberBundle(url, name, now = new Date()) {
  if (READ_ONLY) return;
  const entry = {url, name: name || url, checked: now.toISOString()};
  saveRecentBundles([entry, ...loadRecentBundles().filter((r) => r.url !== url)]
    .slice(0, RECENT_BUNDLES_MAX));
}

function clearRecentBundles() {
  if (READ_ONLY) return;
  saveRecentBundles([]);
}

function renderRecentBundles() {
  const el = $("#bundle-recent");
  if (!el) return;
  const list = loadRecentBundles();
  el.hidden = list.length === 0;
  const when = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString(undefined,
      {dateStyle: "medium", timeStyle: "short"});
  };
  el.innerHTML = list.length ? `<span class="bundle-recent-label">Recent:</span>
    <ul>${list.map((r) => `<li><button class="bundle-recent-go"
      data-recent-url="${esc(r.url)}" title="${esc(r.url)}">${esc(r.name)}</button>
      <span class="bundle-score">checked ${esc(when(r.checked))}</span></li>`).join("")}</ul>
    <button id="bundle-recent-clear" aria-label="Clear recent bundles">Clear</button>` : "";
}

// How sure a fuzzy title match is, as a word (#93). "(0.91)" named no
// scale and no direction. The server picks the word (bundle_preview.CLOSE)
// so both panels mean the same score by it; the number stays in the
// tooltip. A payload from an older server has no word, so it keeps the
// number it always showed.
function matchStrength(hit) {
  const score = hit.score.toFixed(2);
  if (!hit.strength) return `<span class="bundle-score">(${score})</span>`;
  return `<span class="bundle-score" title="Title similarity ${score}, where 1.00 is identical">${esc(hit.strength)}</span>`;
}

function renderBundleGuidance() {
  $("#bundle-empty").hidden = !!(bundlePreview || bundlePreviewError
    || choicePreview || choicePreviewError);
}

function renderBundlePreview() {
  renderBundleGuidance();
  const panel = $("#bundle-panel");
  panel.hidden = !bundlePreview && !bundlePreviewError;
  if (panel.hidden) return;
  if (bundlePreviewError) {
    panel.innerHTML = `<p class="bundle-error">${esc(bundlePreviewError)}</p>`;
    return;
  }
  // A header row and bare numbers, so the three counts line up in labelled
  // columns (#91). The bar's viewBox is the tier's item count, so its two
  // rects ARE the counts: no percentage is computed and nothing is styled
  // inline. Counts only -- never a price per item (#13).
  const bar = (t) => t.total > 0 ? `<svg class="bundle-bar" role="img"
      aria-label="${t.owned} owned, ${t.new} new, of ${t.total} ${
        t.total === 1 ? "item" : "items"}"
      viewBox="0 0 ${t.total} 1" preserveAspectRatio="none"
      ><rect class="bundle-bar-rest" x="0" width="${t.total}" height="1"
      /><rect class="bundle-bar-owned" x="0" width="${t.owned}" height="1"
      /><rect class="bundle-bar-new" x="${t.owned}" width="${t.new}" height="1"
      /></svg>` : "";
  const rows = bundlePreview.tiers.map((t) => `<tr>
    <td class="bundle-price">${esc(money(t.price, bundlePreview.currency))}</td>
    <td class="bundle-num">${t.total}</td>
    <td class="bundle-num">${t.owned}</td>
    <td class="bundle-num">${t.new}</td>
    <td>${bar(t)}</td></tr>`).join("");
  const head = `<thead><tr><th scope="col">Price</th><th scope="col">Items</th>
    <th scope="col">Owned</th><th scope="col">New</th>
    <th scope="col" class="bundle-key"><svg viewBox="0 0 1 1" aria-hidden="true"
      ><rect class="bundle-bar-owned" width="1" height="1"/></svg> owned
      <svg viewBox="0 0 1 1" aria-hidden="true"
      ><rect class="bundle-bar-new" width="1" height="1"/></svg> new</th>
    </tr></thead>`;
  // Every tier row first, then the lists. Interleaving them read fine in
  // the spec and badly in a browser: eight titles sat between the first
  // two prices and pushed the cheapest tier ~500px down, so the three
  // numbers the panel exists to compare were never on screen together.
  // The comparison is what must not scroll; the detail may.
  //
  // Each heading carries its own price, because a list is now further
  // from its row, and repeats the count: the tier's `new` is cumulative
  // while `adds` is incremental, so the two legitimately disagree.
  // Omitted entirely for a tier that adds nothing.
  const lists = bundlePreview.tiers.filter((t) => t.adds.length).map((t) => `
    <section class="bundle-adds">
      <h4>${esc(money(t.price, bundlePreview.currency))} adds ${t.adds.length} new</h4>
      <ul>${t.adds.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    </section>`).join("");
  // Inside the owned count on the row above, not beside it -- so this
  // explains a number rather than adding a fourth one. A game reached only
  // by a key is paid for but not yet in any library, which can fail in ways
  // an owned row cannot (expired, region-locked), so the panel says which
  // games the count is trusting a key for. `|| []` because a tier from an
  // older server carries no keyed_items at all.
  // Never "unredeemed": Humble marks a key redeemed the moment its value is
  // revealed, which says nothing about whether the game ever reached a store
  // account -- the bug that started this counted a revealed-but-unactivated
  // key's game as new. Absence from every imported library is what is
  // actually known, so it is what is said. One line, not a wrapped template:
  // the heading is asserted as a substring, and indentation would split it.
  const keyedNoun = (n) =>
    `${n} owned via ${n === 1 ? "a Humble key" : "Humble keys"}`
    + " (not in any imported library)";
  const keyed = bundlePreview.tiers
    .filter((t) => (t.keyed_items || []).length).map((t) => `
    <section class="bundle-keyed">
      <h4>${esc(money(t.price, bundlePreview.currency))} — ${keyedNoun(t.keyed_items.length)}</h4>
      <ul>${t.keyed_items.map((k) => `<li>${esc(k.offered)}
        <span class="bundle-score">(${esc([
          k.key_type ? k.key_type + " key" : null, k.bundle,
        ].filter(Boolean).join(", "))})</span></li>`).join("")}</ul>
    </section>`).join("");
  // Mirrors the CLI's _series_note. These are facts about which volumes
  // are held, so the block sits ABOVE the overlap list, which is a list
  // of suspicions. The two are never summed.
  const seriesNote = (s) => {
    if (s.already_owned) return `ALREADY OWNED — you hold Vol. ${s.offered_volume}`;
    if (s.kind === "collection") {
      if (s.span) {
        // A range states its own size; an omnibus word does not, so only
        // this branch has a denominator to print. Counted over the
        // volumes INSIDE the range: owning Vol. 9 says nothing about a
        // collection selling Vol. 1-6.
        const inside = s.owned.filter((v) => v >= s.span[0] && v <= s.span[1]).length;
        return `you own ${inside} of ${s.span[1] - s.span[0] + 1} (${s.owned_display})`;
      }
      return `you own ${s.owned.length} ${s.owned.length === 1 ? "volume" : "volumes"}`
        + ` (${s.owned_display})`;
    }
    return `you own ${s.owned_display}`;
  };
  // `|| []` because a payload from an older server carries no series field.
  const seriesHits = bundlePreview.series || [];
  const series = seriesHits.length ? `
    <section class="bundle-series">
      <h4>Series you already hold (${seriesHits.length})</h4>
      <ul>${seriesHits.map((s) => `<li>
        ${esc(s.offered)} —
        <button class="bundle-series-jump" data-series="${esc(s.series_name)}"
          >${esc(seriesNote(s))}</button></li>`).join("")}</ul>
    </section>` : "";
  // Kept visually separate from the counts above, and labelled a
  // suspicion: owned/new are exact-id facts, these are guesses. If the
  // two ever merge into one number, that number stops being a fact.
  const overlaps = bundlePreview.overlaps.length ? `
    <section class="bundle-overlaps">
      <h4>Possibly already owned in part (${bundlePreview.overlaps.length})</h4>
      <ul>${bundlePreview.overlaps.map((o) => `<li>
        ${esc(o.offered)} ~
        <button class="bundle-jump" data-item="${o.item_id}"
          >${esc(o.item_name)}</button>
        ${matchStrength(o)}</li>`)
        .join("")}</ul></section>` : "";
  // Which titles the owned counts are (#92), once for the whole bundle
  // since the tiers are cumulative. Collapsed: the new titles are what a
  // purchase is decided on, and this list is usually the longer one. A
  // book leads to its Library row, like an overlap; a game has no row,
  // so it names what it matched instead. `|| []` for an older server.
  const ownedHits = bundlePreview.owned_items || [];
  // The jump searches Library for the button's text, so the button is the
  // row's own name; the bundle's spelling leads it when the two differ.
  const ownedBook = (o) => {
    const row = o.item_name || o.offered;
    const button = `<button class="bundle-jump" data-item="${esc(o.item_id)}"
            >${esc(row)}</button>`;
    return row === o.offered ? button : `${esc(o.offered)} ~ ${button}`;
  };
  const owned = ownedHits.length ? `
    <details class="bundle-owned">
      <summary>Already owned (${ownedHits.length})</summary>
      <ul>${ownedHits.map((o) => `<li>${o.item_id != null
        ? ownedBook(o)
        : esc(o.offered)}${o.owned_title && o.owned_title !== o.offered
        ? ` ~ ${esc(o.owned_title)}` : ""}${o.keyed
        ? ' <span class="bundle-score">(Humble key)</span>' : ""}</li>`)
        .join("")}</ul>
    </details>` : "";
  // The name links to the page that was checked, so a result always says
  // which URL it belongs to. Only a Humble https URL is ever linked: the
  // server already refused anything else, and this is the second guard.
  const pageUrl = bundlePreview.url || "";
  const name = /^https:\/\/(www\.)?humblebundle\.com\//i.test(pageUrl)
    ? `<a href="${esc(pageUrl)}" target="_blank" rel="noopener noreferrer"
        >${esc(bundlePreview.name)}</a>`
    : esc(bundlePreview.name);
  panel.innerHTML = `<details${bundlePreviewOpen ? " open" : ""}>
    <summary>${name}</summary>
    <table class="bundle-tiers">${head}<tbody>${rows}</tbody></table>
    ${lists}${owned}${keyed}${series}${overlaps}</details>`;
  panel.querySelector("details").addEventListener("toggle",
    (ev) => { bundlePreviewOpen = ev.target.open; });
}

$("#bundle-go").addEventListener("click", () => {
  const url = $("#bundle-url").value.trim();
  if (url) previewBundle(url);
});
$("#bundle-url").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") $("#bundle-go").click();
});
$("#bundle-recent").addEventListener("click", (ev) => {
  const t = ev.target;
  if (t.id === "bundle-recent-clear") {
    clearRecentBundles();
    renderRecentBundles();
    return;
  }
  const url = t.closest && t.closest(".bundle-recent-go")?.dataset.recentUrl;
  if (url) {
    $("#bundle-url").value = url;
    previewBundle(url);
  }
});
renderRecentBundles();

// ---- Humble Choice panel ----------------------------------------------
// One button, no URL: Choice is always "this month". The counting lives
// only in choice_preview.py, so every number arrives with the data and
// there is nothing here to drift from the CLI.
//
// Unlike the bundle panel this needs the owner's Humble login, which the
// server will NOT perform: a stale session comes back as 409 with the
// command to run, and the message is shown as-is.

let choicePreview = null, choicePreviewError = null;
let choicePreviewOpen = true;

async function previewChoice() {
  await whileChecking("#choice-go", "Check this month's Choice", async () => {
    const {report, error} = await fetchReport(
      "/api/choice-preview", {}, "could not read this month's Choice");
    choicePreview = report || null;
    choicePreviewError = error || null;
    renderChoicePreview();
  });
}

function renderChoicePreview() {
  renderBundleGuidance();
  const panel = $("#choice-panel");
  panel.hidden = !choicePreview && !choicePreviewError;
  if (panel.hidden) return;
  if (choicePreviewError) {
    panel.innerHTML = `<p class="bundle-error">${esc(choicePreviewError)}</p>`;
    return;
  }
  const c = choicePreview;
  // The three counts on one row, so the comparison the panel exists for
  // never scrolls. Detail lists follow.
  const counts = `<table class="bundle-tiers"><tbody><tr>
    <td class="bundle-price">${esc(money(c.price, c.currency))}</td>
    <td>${c.total} ${c.total === 1 ? "game" : "games"}</td>
    <td>owned <b>${c.owned}</b></td>
    <td>possible <b>${c.possible}</b></td>
    <td>new <b>${c.new}</b></td></tr></tbody></table>`;
  // Omitted entirely when empty, so a month owned outright renders as
  // clean counts rather than a stack of empty headings.
  const list = (cls, heading, items) => items.length ? `
    <section class="${cls}">
      <h4>${esc(heading)}</h4>
      <ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul>
    </section>` : "";
  const plain = (items) => items.map((n) => esc(n));
  // Never "unredeemed": Humble marks a key redeemed the moment its value
  // is revealed, which says nothing about whether the game reached a store
  // account. Absence from every imported library is what is known.
  const keyedNoun = (n) =>
    `${n} owned via ${n === 1 ? "a Humble key" : "Humble keys"}`
    + " (not in any imported library)";
  const keyed = list("bundle-keyed", keyedNoun(c.keyed),
    (c.keyed_items || []).map((k) => `${esc(k.offered)}
      <span class="bundle-score">(${esc([
        k.key_type ? k.key_type + " key" : null, k.bundle,
      ].filter(Boolean).join(", "))})</span>`));
  // Listed, never folded into owned or new: the point of the middle band
  // is that the tool declines to decide, so a bare count would hide which
  // game it could not decide about.
  const possible = list("bundle-overlaps",
    `${c.possible} possible (counted as neither owned nor new)`,
    (c.possible_items || []).map((p) => `${esc(p.offered)} ~
      ${esc(p.owned_title)}
      ${matchStrength(p)}`));
  const warnings = (c.unimported_stores || []).map((s) => `
    <p class="bundle-error">WARNING: this month delivers on ${esc(s)}, which
    has never been imported — its unmatched games are counted as new by
    default.</p>`).join("");
  panel.innerHTML = `<details${choicePreviewOpen ? " open" : ""}>
    <summary>${esc(c.name)}</summary>
    ${counts}
    ${c.claimed ? "<p>You have already made your picks for this month.</p>" : ""}
    ${list("bundle-adds", `new (${c.new})`, plain(c.new_items || []))}
    ${list("bundle-adds", `owned (${c.owned})`, plain(c.owned_items || []))}
    ${keyed}${possible}
    ${list("bundle-adds", `Extras (not counted, ${(c.extras || []).length})`,
           plain(c.extras || []))}
    <p class="bundle-approximate">Game ownership is matched by title and is
      APPROXIMATE — verify anything you would buy on.</p>
    ${warnings}</details>`;
  panel.querySelector("details").addEventListener("toggle",
    (ev) => { choicePreviewOpen = ev.target.open; });
}

$("#choice-go").addEventListener("click", () => { previewChoice(); });
