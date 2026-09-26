// Shared ground for the viewer's sections. What lives here is exactly
// what more than one of them needs: the catalog itself, the vocabularies
// the table and the statistics must agree on, and the four helpers every
// section calls. Everything else belongs to a section.
//
// This file loads FIRST. Classic scripts run in <script> order and share
// one global scope, so a helper called by catalog.js has to be defined by
// a script that ran earlier.
let items = [];

// True on the LAN viewer (serve --lan), set by shell.js from /api/status
// before load() runs. Every write route is ABSENT there, not merely
// refused, so this only decides what is worth drawing.
let READ_ONLY = false;

// The gap flags, defined once so the #f-flag filter (visible) cannot
// disagree with what the Gaps section of the stats panel reports.
// A gap is "a column is falsy". flag values match index.html's #f-flag
// options and stats.py's GAPS; keep the three in step.
const GAPS = [
  {label: "Unrated",       flag: "unrated", empty: (i) => !i.my_rating},
  {label: "No cover",      flag: "nocover", empty: (i) => !i.cover_path},
  {label: "No source URL", flag: "nourl",   empty: (i) => !i.source_url},
];
const gapEmpty = Object.fromEntries(GAPS.map((g) => [g.flag, g.empty]));

// The enrichment.status vocabulary, each doubling as its own #f-flag
// value. Mirrors stats.py's ENRICHMENT keys.
const ENRICHMENT_STATES = ["matched", "low_confidence", "unmatched", "pending"];

const $ = (sel) => document.querySelector(sel);

// True when /api/items could not be read at all. Distinct from an empty
// catalog: the rows are unknown, not absent, so the table must not offer
// the advice an empty catalog would.
let loadError = false;

// What a first run on an empty catalog has already done, from /api/setup
// (#99). Asked only while the catalog is empty, and null otherwise or
// when the answer could not be had: the empty line then stands alone.
let setupState = null;

async function load() {
  // Outside the guarded loop below, this line was the one unprotected
  // fetch in load(): a server that had stopped threw here, boot() logged
  // it to the console, and the page stayed on the loading row for ever
  // with nothing on screen to say why.
  try {
    items = (await (await fetch("/api/items")).json()).items;
    loadError = false;
  } catch (err) {
    console.error("could not read /api/items:", err);
    loadError = true;
  }
  foldCache.clear();
  setupState = null;
  if (!READ_ONLY && !loadError && items.length === 0) {
    try {
      setupState = await (await fetch("/api/setup")).json();
    } catch (err) {
      console.error("could not read /api/setup:", err);
    }
  }
  // The four renderers are independent, so one failing must not take out
  // the rest. render() used to run first and unguarded: a single item
  // with a missing field threw here and left the table AND all three
  // panels empty, with nothing on screen to say why. Failures are now
  // contained and reported, so the rest of the page still comes up.
  // The LAN viewer has no /api/review, /api/duplicates or /api/jobs, so
  // their loaders would only log 404s.
  const steps = READ_ONLY
    ? [render, refreshStats, loadKeys]
    : [render, loadReview, loadDupes, refreshStats, loadKeys, renderTasks];
  for (const step of steps) {
    try {
      await step();
    } catch (err) {
      console.error(`${step.name}() failed:`, err);
    }
  }
  // Badges are computed here rather than by each section, because this
  // loop is the one place that has just run every loader. A section the
  // owner has never opened still reports its count.
  pending = {
    library: items.filter((i) => !i.my_rating).length,
    maintenance: reviewCount + dupeGroups.length,
    // Expiring keys, NOT the unredeemed count: see badgeCount in shell.js.
    // Unredeemed keys number in the hundreds and never reach zero, which
    // is exactly the always-lit badge that policy rules out.
    keys: keysExpiring(),
    bundles: 0,
    // Never badged -- see badgeCount in shell.js. Carried so the shape
    // of `pending` matches SECTIONS rather than quietly omitting one.
    tasks: 0,
  };
  renderBadges();
}

// Tolerates a missing array: render() runs before the review/dupes/genre
// loaders, so throwing here blanks the entire page rather than one cell --
// which is what a payload lacking a newer field (an older server, a
// partial response) would otherwise do.
const tagBadges = (arr) =>
  (arr || []).map(t => `<span class="tag" title="${esc(t)}">${esc(t)}</span>`).join("");

function esc(v) {
  return v == null ? "" : String(v).replace(/[&<>"]/g,
    (ch) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[ch]));
}

// Two-click confirmation: first click arms the button, second click (within
// 3 s) fires. Prevents one stray click from mis-attributing an item.
//
// The label is restored on BOTH exits. Restoring it only when the window
// lapsed left a button that fired reading "Click again to confirm" for
// good -- harmless where the fire re-renders the button, wrong wherever it
// does not (a Tasks card whose start was refused, for one).
function armOrFire(el, fire) {
  // An aria-label outranks the text, so a glyph button (#50) would go on
  // announcing its action while it asks for a second click. The prompt
  // goes into the label too, and the label comes back with the text.
  const disarm = () => {
    delete el.dataset.armed;
    el.classList.remove("armed");
    el.textContent = el.dataset.label;
    delete el.dataset.label;
    if (el.dataset.ariaLabel !== undefined) {
      el.setAttribute("aria-label", el.dataset.ariaLabel);
      delete el.dataset.ariaLabel;
    }
  };
  if (el.dataset.armed) {
    disarm();
    // Returned, not dropped: callers are async, and a test (or any future
    // caller that needs to know the write finished) has nothing else to
    // await. Every current caller ignores it.
    return fire();
  }
  el.dataset.armed = "1";
  el.dataset.label = el.textContent;
  el.classList.add("armed");
  el.textContent = "Click again to confirm";
  const ariaLabel = el.getAttribute("aria-label");
  if (ariaLabel !== null) {
    el.dataset.ariaLabel = ariaLabel;
    el.setAttribute("aria-label", "Click again to confirm");
  }
  setTimeout(() => {
    if (el.isConnected && el.dataset.armed) disarm();
  }, 3000);
}

async function post(url, body) {
  return fetch(url, {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {})});
}
