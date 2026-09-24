// The shell: everything that belongs to the page rather than to any one
// section -- the run banner, the theme toggle, and the boot call.
//
// This file loads LAST. The boot call has to sit after every renderer it
// invokes has been defined; in app.js, where the spec first put it,
// load() would have called a render() that did not exist yet.

async function pollStatus() {
  const runs = (await (await fetch("/api/status")).json()).runs;
  const banner = $("#run-banner");
  banner.hidden = runs.length === 0;
  banner.textContent = runs.map(r =>
    `${r.command}: ${r.done}/${r.total} - ${r.current || "starting"}`).join(" | ");
}

// ---- Sections ---------------------------------------------------------
// The sections. Order here is tab order. `keys` ships empty on
// purpose: the unredeemed key report is separate work, and a section
// that is not the table exercises the shell before the feature that
// needed it is built on top of it.
const SECTIONS = [
  {id: "library",     label: "Library"},
  {id: "maintenance", label: "Maintenance"},
  {id: "keys",        label: "Keys"},
  {id: "bundles",     label: "Bundles"},
  {id: "tasks",       label: "Tasks"},
];

// What the LAN viewer shows. Maintenance and Tasks are writes; Bundles is
// hidden too, because both previews are credentialed POSTs the LAN app
// does not have.
const READ_ONLY_SECTIONS = ["library", "keys"];
const sectionAllowed = (id) => !READ_ONLY || READ_ONLY_SECTIONS.includes(id);

function applyMode(readOnly) {
  READ_ONLY = readOnly === true;
  if (document.body) document.body.dataset.mode = READ_ONLY ? "read-only" : "full";
  for (const s of SECTIONS) {
    const tab = $(`#tab-${s.id}`);
    if (tab) tab.hidden = !sectionAllowed(s.id);
  }
}

const currentSection = () => {
  const name = (location.hash || "").replace(/^#\//, "");
  return SECTIONS.some((s) => s.id === name && sectionAllowed(s.id)) ? name : "library";
};

// An unknown hash falls back to Library WITHOUT rewriting the URL: a
// silent rewrite would erase the evidence that a bookmark went stale.
function showSection(name) {
  const active = SECTIONS.some((s) => s.id === name && sectionAllowed(s.id)) ? name : "library";
  $("#search-row").hidden = active !== "library";
  for (const s of SECTIONS) {
    const el = $(`#section-${s.id}`);
    if (el) el.hidden = s.id !== active;
    const tab = $(`#tab-${s.id}`);
    if (tab) tab.setAttribute("aria-current", s.id === active ? "page" : "false");
  }
}

if (typeof addEventListener === "function")
  addEventListener("hashchange", () => showSection(currentSection()));

// ---- Badges -----------------------------------------------------------
// What each section is waiting on. Written by load(), read by
// renderBadges(). One object rather than a call into each section, so a
// section whose loader has not run yet counts as zero instead of
// throwing during the first paint.
let pending = {library: 0, maintenance: 0, keys: 0, bundles: 0, tasks: 0};

// Which pending counts are worth a badge.
//
// A badge here means "there is work waiting", not "here is a number".
// That distinction decides Library: its natural count is unrated items,
// which never reaches zero because rating is optional and the catalog
// keeps growing. A badge that is always lit is one the eye stops
// reading -- and it would take the Maintenance badge beside it down
// with it, which is the badge that has something to say.
//
// So Library stays silent, and the sections that badge are the ones
// whose count is a queue that can be emptied. To change the policy,
// change this function; nothing else reads `pending`.
//
// Tasks is silent for the same reason: its only candidate count is "jobs
// you could run", which is an optional backlog by definition and would
// light the badge forever.
function badgeCount(section) {
  return (section === "library" || section === "tasks")
    ? 0 : (pending[section] || 0);
}

function renderBadges() {
  for (const s of SECTIONS) {
    const el = $(`#tab-${s.id} .badge-count`);
    if (!el) continue;
    const n = badgeCount(s.id);
    el.textContent = n > 0 ? String(n) : "";
  }
}

// Theme toggle. currentTheme() reads the explicit choice, falling back to
// the OS preference. Every DOM/global here is guarded so app.js still loads
// under the test harness, whose sandbox has no matchMedia/localStorage/
// documentElement.
function currentTheme() {
  const explicit = document.documentElement?.dataset?.theme;
  if (explicit) return explicit;
  return (typeof matchMedia === "function"
          && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
}
function syncThemeButton() {
  const dark = currentTheme() === "dark";
  const btn = $("#theme-toggle");
  btn.textContent = dark ? "☀" : "☾";
  btn.title = dark ? "Switch to light theme" : "Switch to dark theme";
}
$("#theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  if (document.documentElement) document.documentElement.dataset.theme = next;
  if (typeof localStorage !== "undefined") localStorage.setItem("hc-theme", next);
  syncThemeButton();
});

// Boot. The mode is read before the catalog is drawn, so no row, card or
// panel ever renders with editing controls the LAN viewer cannot use. The
// static tab bar in index.html is visible until /api/status answers,
// though, so the write tabs can show briefly on a slow connection.
async function boot() {
  let status = {};
  try {
    status = await (await fetch("/api/status")).json();
  } catch (err) {
    console.error("could not read /api/status:", err);
  }
  applyMode(status.read_only);
  showSection(currentSection());
  await load();
}
// One interval for both. pollStatus draws the header banner (which must
// keep working for a run started in a terminal); pollJobs draws the Tasks
// panel, which knows only about jobs this viewer started -- and which the
// LAN viewer does not have.
async function pollAll() {
  await pollStatus();
  if (READ_ONLY) return;
  try {
    await pollJobs();
  } catch (err) {
    console.error("pollJobs() failed:", err);
  }
}
// Re-render when the width crosses the card breakpoint, e.g. a phone
// rotated to landscape.
if (typeof matchMedia === "function")
  matchMedia(NARROW_QUERY).addEventListener("change", () => render());
// And re-apply the sidebar when crossing its breakpoint, whose two sides
// use different classes (see applySidebar).
if (typeof matchMedia === "function")
  matchMedia(SIDEBAR_NARROW_QUERY).addEventListener("change", () => applySidebar());
// Polling waits for boot(): until /api/status has answered, READ_ONLY is
// still false, and a first poll would ask the LAN app for /api/jobs.
async function start() {
  try {
    await boot();
  } catch (err) {
    // Polling still starts: the header banner must keep working.
    console.error("boot() failed:", err);
  }
  pollAll();
  setInterval(pollAll, 5000);
}
start();
syncThemeButton();
