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
  });
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
  const rows = bundlePreview.tiers.map((t) => `<tr>
    <td class="bundle-price">${esc(money(t.price, bundlePreview.currency))}</td>
    <td>${t.total} ${t.total === 1 ? "item" : "items"}</td>
    <td>owned <b>${t.owned}</b></td>
    <td>new <b>${t.new}</b></td></tr>`).join("");
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
        <span class="bundle-score">(${o.score.toFixed(2)})</span></li>`)
        .join("")}</ul></section>` : "";
  panel.innerHTML = `<details${bundlePreviewOpen ? " open" : ""}>
    <summary>${esc(bundlePreview.name)}</summary>
    <table class="bundle-tiers"><tbody>${rows}</tbody></table>
    ${lists}${keyed}${series}${overlaps}</details>`;
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
      <span class="bundle-score">(${p.score.toFixed(2)})</span>`));
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
