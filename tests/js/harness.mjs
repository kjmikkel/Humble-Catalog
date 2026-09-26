// Loads the viewer's app.js in a stubbed DOM so its functions can be
// tested for real behaviour, not just grepped for.
//
// app.js is a plain script, not a module: it has no exports and it calls
// load()/pollStatus() at the bottom. So the stubs make those calls
// harmless (fetch never resolves, timers are no-ops) and an appended line
// publishes the top-level bindings, which `const` would otherwise keep
// off the global object.
//
// Usage: node harness.mjs <path-to-app.js> <expression>
// The expression runs with `app` (the bindings) and `dom` (the recorder)
// in scope, and its result is printed as JSON.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

// A comma-separated list of the viewer's scripts, in <script> order.
// They are concatenated into ONE context because that is what the browser
// does: classic scripts share the global lexical environment, which is why
// none of them import anything.
const [appPaths, expr] = process.argv.slice(2);
const paths = appPaths.split(",");
const src = paths.map((p) => fs.readFileSync(p, "utf8")).join("\n;\n");
// fuzzy.js is a sibling script the viewer depends on. It has to run in
// the same context and be published by hand: a top-level `const` inside
// runInContext never reaches globalThis.
const fuzzySrc = fs.readFileSync(
  path.join(path.dirname(paths[0]), "fuzzy.js"), "utf8");

// Records innerHTML writes per selector, so a test can ask which
// renderers actually ran.
const writes = {};
// Selectors that have been focus()ed, in order.
const focused = [];
// The same calls with their options, for assertions about preventScroll.
const focusCalls = [];

function makeEl(selector) {
  const el = {
    _selector: selector,
    value: "",
    hidden: false,
    dataset: {},
    // Classes are RECORDED, like attributes below. A stub that dropped them
    // left the sidebar toggle untestable: on a phone it flipped a class the
    // CSS did not look at, and no test could see that nothing opened.
    classList: (() => {
      const set = new Set();
      return {
        contains: (c) => set.has(c),
        add: (...cs) => { for (const c of cs) set.add(c); },
        remove: (...cs) => { for (const c of cs) set.delete(c); },
        toggle(c, force) {
          const on = force === undefined ? !set.has(c) : Boolean(force);
          if (on) set.add(c); else set.delete(c);
          return on;
        },
      };
    })(),
    addEventListener() {},
    removeEventListener() {},
    insertAdjacentHTML() {},
    remove() {},
    // Focus moves are RECORDED, for the same reason classes and
    // attributes are: where the keyboard lands after a control removes
    // itself is behaviour, and a no-op stub left it unobservable.
    focus(opts) {
      focused.push(selector);
      // The options too: a sheet that animates up from off-screen must be
      // focused with preventScroll, or the browser scrolls to chase the
      // control and the list appears to lurch. Recorded separately so the
      // older `focused` assertions keep working.
      focusCalls.push({selector, preventScroll: Boolean(opts && opts.preventScroll)});
    },
    click() {},
    closest: () => makeEl(selector),
    querySelector: () => makeEl(selector),
    querySelectorAll: () => [],
    // Attributes are RECORDED, not discarded. shell.js marks the active
    // tab with aria-current, which is the only signal a screen reader
    // gets about which section is showing, and a stub that swallowed the
    // write left that half of showSection unobservable. Additive: no
    // viewer script reads getAttribute, so nothing depended on the old
    // null.
    attrs: {},
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attrs, name)
        ? this.attrs[name] : null;
    },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    appendChild() {},
    // There is no layout here, but code that deliberately forces one --
    // flushing a style change before the class that transitions from it --
    // still has to be able to call this.
    getBoundingClientRect() {
      return {top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0};
    },
    get innerHTML() { return writes[selector] ?? ""; },
    set innerHTML(v) { writes[selector] = String(v); },
    get textContent() { return ""; },
    set textContent(v) { writes[selector + ":text"] = String(v); },
  };
  return el;
}

const elCache = new Map();
const query = (sel) => {
  if (!elCache.has(sel)) elCache.set(sel, makeEl(sel));
  return elCache.get(sel);
};

const document = {
  querySelector: query,
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => makeEl("created"),
};

const sandbox = {
  document,
  console,
  // Never resolves: the load()/pollStatus() calls at the bottom of app.js
  // stay pending instead of running during import.
  fetch: () => new Promise(() => {}),
  setInterval: () => 0,
  setTimeout: () => 0,
  clearTimeout() {},
  alert() {},
  // The CSV download materializes a Blob and clicks a synthetic <a>;
  // neither API exists in the sandbox, and neither needs to do anything
  // real for the test to see which ids were posted.
  URL: { createObjectURL: () => "blob:stub", revokeObjectURL() {} },
  // app.js persists the theme and the export column selection. The real
  // sandbox has no localStorage, and app.js guards for that -- but the
  // guard would then make persistence itself untestable, so it gets a
  // working in-memory stand-in.
  localStorage: (() => {
    const store = {};
    return {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    };
  })(),
  Autocomplete: { attach() {} },
  // The shell routes off location.hash and listens for hashchange. A
  // plain mutable object is enough: nothing here navigates, and a test
  // that sets .hash is expressing exactly what a bookmark would.
  location: { hash: "" },
  addEventListener() {},
};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;

vm.createContext(sandbox);

// Publish the bindings a `const` would keep off globalThis, plus hooks the
// tests need to drive state.
const publish = `
;globalThis.__app = {
  tagBadges, bundleLabel, person, personField, esc, highlight, chipFilters, passesChipFilters,
  visible, render, scheduleRender, ROW_CAP, showAllRows, viewKey,
  restoreFilters, startFresh, keepRestored, getStatusFilter: () => statusFilter, stars, ratingForKey, applyRating, ariaSortFor, tagCounts, shouldPostEnrichmentEdit, load, loadReview, shownRows,
  renderBulkBar, runBulk, undoBulk,
  getLastTagOp: () => lastTagOp,
  setLastTagOp: (v) => { lastTagOp = v; },
  refreshStats, renderStats, statsReport, SECTION_FILTERS,
  setStatsData: (v) => { statsData = v; },
  getStatsData: () => statsData,
  SECTIONS, currentSection, showSection,
  renderBadges, badgeCount,
  toggleSidebar, sidebarCollapsed, applySidebar, renderActiveFilters,
  clearAllFilters, emptyStateText,
  setPending: (v) => { pending = {...pending, ...v}; },
  getPending: () => pending,
  loadKeys, renderKeys, shownKeys, KEY_STATES, setKeyStates,
  displayState, keyChipCounts, toggleKeyHidden,
  keysExpiring: () => keysExpiring(),
  setKeyRows: (v) => { keyRows = v; },
  previewBundle, renderBundlePreview, money,
  setBundlePreview: (v) => { bundlePreview = v; },
  TASK_CARDS, TASK_GROUPS, TAKEOVER_TEXT, renderTasks, startTask, taskMessage,
  setHandoffAvailable: (v) => { handoffAvailable = v; },
  setSetupState: (v) => { setupState = v; },
  previewChoice, renderChoicePreview,
  setChoicePreview: (v) => { choicePreview = v; },
  setGenresShowAll: (v) => { genresShowAll = v; },
  setTagEditMode: (v) => { tagEditMode = v; },
  sortValue, renderExportButton, downloadExport,
  statusSelect, READ_STATUS_ORDER,
  statusCell, nameExtras, applyMode, sectionAllowed, READ_ONLY_SECTIONS,
  start,
  renderCards, isNarrow, NARROW_QUERY,
  sheetFor, openSheet, closeSheet, setSheetStatus, setSheetRating,
  READ_STATUS_SHORT, getOpenSheetId: () => openSheetId,
  setReadOnly: (v) => { READ_ONLY = v; },
  getReadOnly: () => READ_ONLY,
  setStatusFilter: (arr) => { statusFilter.clear(); for (const s of arr) statusFilter.add(s); },
  EXPORT_COLUMNS, toggleColumn, loadColumnSelection, renderColumnPicker,
  getExportColumns: () => [...exportColumns],
  setExportColumns: (v) => { exportColumns = new Set(v); },
  setStored: (k, v) => globalThis.localStorage.setItem(k, v),
  setSort: (k, asc) => { sortKey = k; sortAsc = asc; },
  setItems: (v) => { items = v; },
  setSearch: (v) => { document.querySelector("#search").value = v; },
  setExportFormat: (v) => { document.querySelector("#export-format").value = v; },
  setFlag: (v) => { document.querySelector("#f-flag").value = v; },
  setRating: (v) => { document.querySelector("#f-rating").value = v; },
  setRelevance: (v) => { relevanceSort = v; },
  // a Map, which JSON.stringify renders as {}: assert on .size or on
  // [...entries()], never on the Map itself
  getMatchSpans: () => matchSpans,
  getItems: () => items,
  setFetch: (fn) => { globalThis.fetch = fn; },
};
`;

vm.runInContext(fuzzySrc + ";globalThis.Fuzzy = Fuzzy;", sandbox);
vm.runInContext(src + publish, sandbox);

const runner = `
(async () => {
  const app = globalThis.__app;
  const dom = globalThis.__dom;
  const Fuzzy = globalThis.Fuzzy;
  return (${expr});
})()
`;

sandbox.__dom = { writes, focused, focusCalls,
  reset: () => { for (const k of Object.keys(writes)) delete writes[k];
                 focused.length = 0; focusCalls.length = 0; } };

const result = await vm.runInContext(runner, sandbox);
process.stdout.write(JSON.stringify(result === undefined ? null : result));
