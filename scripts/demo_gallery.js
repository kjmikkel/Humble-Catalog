// The component gallery (#153): every viewer component in its states, on
// one page, drawn by the viewer's own render functions.
//
// Served only by scripts/demo_catalog.py, at /dev/gallery/frame, appended
// to the real index.html: the real viewer boots first, on the demo
// catalog's invented items, and this then captures what its renderers
// draw in each state before replacing <main> with the captures. Nothing
// here builds a component's markup by hand, so the gallery cannot drift
// from what the sections draw. It never ships: not in the wheel, not in
// the real viewer, not in the LAN viewer.
//
// A page to look at, not to use. Clicks and keys inside it are stopped
// before the viewer's document-level listeners see them: a star pressed
// here would otherwise post a rating and redraw the gallery's table as
// the whole catalog.
(async () => {
  // The table and its editor exist only above the phone breakpoint, so a
  // narrow frame says so rather than waiting for rows that never come.
  const fail = (why) => document.body.insertAdjacentText("afterbegin", `Gallery: ${why}`);
  if (isNarrow()) return fail("widen this frame past 600 px; the table is not drawn below it.");
  // Done means load() finished, not just the table: its later steps (keys,
  // stats, the Maintenance panels) write into <main>, which would be gone.
  // load() assigns a fresh `pending` as its last act, and this script runs
  // before boot's first await resolves, so a new object is the signal.
  const before = pending;
  const booted = () => pending !== before && items.length
    && document.querySelector("#catalog tbody tr:not(.table-empty)");
  for (let n = 0; n < 150 && !booted(); n++)
    await new Promise((r) => setTimeout(r, 100));
  if (!booted()) return fail("the viewer never drew its table.");

  const outer = (sel) => document.querySelector(sel)?.outerHTML || "";
  const rated = items.find((i) => i.my_rating) || items[0];
  const unrated = items.find((i) => !i.my_rating) || items[1] || items[0];

  // ---- Captures, in the states the issue lists ---------------------------
  const tableHead = outer("#catalog thead");
  const rows = [...document.querySelectorAll("#catalog tbody tr")]
    .slice(0, 2).map((tr) => tr.outerHTML).join("");
  openEditor(rated.id);
  const editingRow = outer("#catalog tbody tr:has(.edit-field)");
  editingId = null;
  editingTags = null;

  // One capture shows both states: its styles hang off the #status-filter
  // id, which a second copy could not repeat.
  statusFilter.add("reading");
  syncStatusChips();
  const statusChips = outer("#status-filter");
  statusFilter.clear();
  syncStatusChips();

  renderKeys();
  const keyChips = outer("#key-chips");

  liveBundles = [{name: "Test Bundle", url: "https://www.humblebundle.com/books/test-bundle"}];
  renderBrowse();
  const kinds = outer(".browse-kinds");
  liveBundles = null;
  renderBrowse();

  chipFilters.genre.chips = ["Fantasy", "Science Fiction"];
  renderFilterChips();
  const filterChips = outer('.chip-filter[data-field="genre"]');
  chipFilters.genre.chips = [];
  renderFilterChips();

  $("#f-type").value = "ebook";
  renderActiveFilters();
  const activeFilter = $("#filter-chips").innerHTML;
  $("#f-type").value = "";
  renderActiveFilters();

  // The real tab stays in the header; the copy loses its id.
  const tabBadge = outer("#tab-maintenance").replace(/ id="[^"]*"/, "");
  reportWriteError(new Error("the viewer isn't reachable"));
  const badges = nameExtras({...rated, status: "low_confidence", edited: 0})
    + nameExtras({...rated, status: "matched", edited: 1, override: 1,
                  editions: [{name: rated.name, type: "audiobook"}]});

  // ---- The page ------------------------------------------------------------
  const state = (label, html) =>
    `<figure class="gallery-state"><figcaption>${esc(label)}</figcaption>${html}</figure>`;
  const group = (title, ...states) =>
    `<section class="gallery-group"><h2>${esc(title)}</h2>${states.join("")}</section>`;
  const starsFor = (n) => `<span class="stars">${stars({...rated, my_rating: n})}</span>`;

  const main = document.querySelector("main");
  main.innerHTML = `<div class="gallery">
    <p class="gallery-note">Focus rings are not drawn here: Tab to any
      control to see the shared :focus-visible ring.</p>
    ${group("Star rating, table (radiogroup)",
      state("unrated", starsFor(0)), state("3", starsFor(3)), state("5", starsFor(5)))}
    ${group("Toggle chips",
      state("status filter: Reading on, the rest off", statusChips),
      state("key states (default)", keyChips), state("Books / Games", kinds))}
    ${group("Removable chips",
      state("filter field", filterChips), state("active filter", activeFilter),
      state("tags", tagBadges(["Fantasy", "Science Fiction"])))}
    ${group("Badges", state("tab count", tabBadge), state("review, edited, queued, edition", badges))}
    ${group("Status select",
      ...READ_STATUS.map(([s, label]) => state(label, statusSelect({...rated, read_status: s}))))}
    ${group("Autocomplete field",
      state("type to open the list; arrows to highlight",
        `<span class="ac-wrap"><input id="gallery-ac" aria-label="Genre (gallery)"
           placeholder="Genre..."></span>`))}
    ${group("Status and error lines",
      state("field message", `<p class="field-msg">Paste a HumbleBundle URL first.</p>`),
      state("report error", `<p class="bundle-error">not a HumbleBundle URL: example.test</p>`),
      state("failed write", `<p class="gallery-note">In the header above, where
        reportWriteError always puts it: one live region for the whole page.</p>`))}
    ${group("Two-step confirm",
      state("idle", `<button type="button">Dismiss</button>`),
      state("armed", `<button type="button" class="armed">Click again to confirm</button>`))}
    ${group("Phone cards", state("rated, unrated",
      `<div id="card-list">${renderCards([rated, unrated])}</div>`))}
    ${group("Edit sheet",
      state("open", `<button type="button" id="gallery-sheet-swap">Show the unrated item</button>
        <div id="edit-sheet" class="open gallery-sheet">${sheetFor(rated)}</div>`))}
    ${group("Table rows", state("normal, striped, editing",
      `<div class="gallery-table"><table id="catalog">${tableHead}<tbody>${rows}${editingRow}</tbody></table></div>`))}
  </div>`;

  // Look, don't touch: see the header comment.
  const own = (el) => el.closest && (el.closest("#gallery-sheet-swap") || el.closest(".ac-wrap"));
  for (const type of ["click", "keydown", "change"])
    main.addEventListener(type, (ev) => { if (!own(ev.target)) ev.stopPropagation(); }, true);

  let showingRated = true;
  $("#gallery-sheet-swap").addEventListener("click", (ev) => {
    showingRated = !showingRated;
    $("#edit-sheet").innerHTML = sheetFor(showingRated ? rated : unrated);
    ev.target.textContent = `Show the ${showingRated ? "unrated" : "rated"} item`;
  });

  const genres = [...new Set(items.flatMap((i) => i.genre || []))].sort();
  Autocomplete.attach($("#gallery-ac"), () => genres, () => {});
})();
