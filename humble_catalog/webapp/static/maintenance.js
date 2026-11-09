// The Maintenance section: the review queue and the duplicates panel.
// Both are catalog *upkeep* rather than catalog *browsing*, which is the
// line the sections are drawn on. Everything here reads the shared
// `items` array from app.js and posts through its `post()`.
let reviewOpen = false, dupesOpen = false;
// How many items the review queue is holding. Kept as its own binding
// because the panel's own HTML is the only other record of the count,
// and load() needs it after loadReview() has run to feed the tab badge.
let reviewCount = 0;

async function loadReview() {
  const review = (await (await fetch("/api/review")).json()).items;
  reviewCount = review.length;
  const panel = $("#review-panel");
  panel.hidden = false;
  panel.innerHTML = review.length === 0
    ? '<p class="section-empty">All clear: no items need review.</p>' :
    `<details${reviewOpen ? " open" : ""}>
      <summary>&#9888; ${review.length} ${review.length === 1 ? "item needs" : "items need"} review</summary>
      ${review.map(r => `<div class="review-item">
      ${r.cover_path ? `<img class="review-cover" src="/${esc(r.cover_path)}" alt="">` : ""}
      <div class="review-body">
        <strong>${esc(r.name)}</strong> (${r.status}, ${r.type})
        ${r.candidates.map((c, idx) => `<div class="cand">
          <button class="cand-btn" data-id="${r.id}" data-idx="${idx}">
            ${esc(c.title)} - ${esc((c.authors || []).join(", "))}
            (${c.source}, ${Math.round((c.confidence || 0) * 100)}%)</button>
          ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">inspect</a>` : ""}
        </div>`).join("")}
        <div class="url-import">
          <input type="url" class="url-box" data-id="${r.id}"
                 placeholder="...or paste a source URL (any product page; APIs for Comic Vine, Hardcover, Open Library, Audible, Google Books, O'Reilly)">
          <button class="url-fetch" data-id="${r.id}">Fetch</button>
          <span class="url-result" data-id="${r.id}"></span>
        </div>
      </div>
    </div>`).join("")}</details>`;
  if (review.length)
    panel.querySelector("details").addEventListener("toggle",
      (ev) => { reviewOpen = ev.target.open; });
}

// ---- Duplicates panel -------------------------------------------------
// Manual pair picker state: item ids chosen via autocomplete, or null.
let manualPair = {a: null, b: null};

// Autocomplete options carry the id so identical names stay selectable.
const itemOption = (i) => `${i.name} — ${i.type} #${i.id}`;
const optionId = (s) => {
  const m = /#(\d+)$/.exec(s);
  return m ? +m[1] : null;
};

function dupeMember(i) {
  // Normalize a catalog item (from the global `items`) to the same shape
  // /api/duplicates returns, so one render path serves both.
  return {id: i.id, name: i.name, type: i.type, cover_path: i.cover_path,
          publisher: i.publisher, my_rating: i.my_rating, edited: i.edited,
          genre: i.genre, series: i.series,
          bundles: i.bundles.map(b => b.name)};
}

function dupeCard(m, other) {
  return `<div class="dupe-card">
    ${m.cover_path ? `<img src="/${esc(m.cover_path)}" alt="" loading="lazy">` : ""}
    <div>
      <strong>${esc(m.name)}</strong> (${m.type})
      ${m.edited ? ' <span class="badge edited">edited</span>' : ""}
      <div>${tagBadges(m.genre)}</div>
      ${m.series ? `<div>${esc(m.series)}</div>` : ""}
      ${m.publisher ? `<div>${esc(m.publisher)}</div>` : ""}
      <div><small>${m.bundles.map(esc).join("<br>")}</small></div>
      ${m.my_rating ? `<div>${"★".repeat(m.my_rating)}</div>` : ""}
      <button class="dupe-keep" data-keep="${m.id}" data-drop="${other.id}"
              aria-label="Keep this one: ${esc(m.name)}">
        Keep this one</button>
    </div></div>`;
}

function dupeGroupHtml(members, manual) {
  // Pairwise actions: each card merges the FIRST other member into itself.
  const cards = members.map(m =>
    dupeCard(m, members.find(o => o.id !== m.id))).join("");
  const dismiss = !manual && members.length === 2
    ? `<button class="dupe-dismiss" data-a="${members[0].id}"
               data-b="${members[1].id}">Not duplicates</button>` : "";
  return `<div class="dupe-group">${cards}${dismiss}</div>`;
}

let dupeGroups = [];

async function loadDupes() {
  // `|| []` as loadKeys does, and not merely for tidiness: dupeGroups is
  // read again by load()'s badge arithmetic, which runs OUTSIDE the
  // try/catch that contains a loader's failure. Assigning undefined here
  // survives the contained throw and takes load() down from there, so the
  // error surfaces at whatever called load() rather than at the payload
  // that caused it. The `= []` initialiser does not cover this: it guards
  // "never loaded", not "loaded badly".
  dupeGroups = (await (await fetch("/api/duplicates")).json()).groups || [];
  renderDupes();
}

// The panel's <summary> line, shown even when it is collapsed. With
// groups it counts them; with none it has to say so AND tell the owner
// the manual picker is inside, or a collapsed panel with nothing
// suggested gives no reason to open it.
function dupesSummary(groupCount) {
  return groupCount === 0
    ? "&#9187; No suggested duplicate groups, but you can still merge two items by hand"
    : `&#9187; ${groupCount} possible duplicate group${groupCount === 1 ? "" : "s"}`;
}

function renderDupes() {
  const panel = $("#dupes-panel");
  const a = items.find(i => i.id === manualPair.a);
  const b = items.find(i => i.id === manualPair.b);
  const manualGroup = a && b && a.id !== b.id
    ? dupeGroupHtml([dupeMember(a), dupeMember(b)], true) : "";
  // Always shown, even with no suggested groups: the manual picker below
  // is the only way to merge a pair the detector missed, and hiding the
  // panel with nothing suggested hid the picker in exactly that case (#71).
  panel.hidden = false;
  // The amber is for suggestions awaiting a decision. With none, the
  // panel is only the picker, and a warning colour would read as trouble.
  panel.classList.toggle("dupes-none", dupeGroups.length === 0);
  panel.innerHTML = `<details${dupesOpen ? " open" : ""}>
    <summary>${dupesSummary(dupeGroups.length)}</summary>
    <div class="dupe-pick ac-wrap">
      <input id="dupe-a" placeholder="Merge: first item..." size="30">
      <input id="dupe-b" placeholder="...second item" size="30">
      <button id="dupe-clear">Clear</button>
    </div>
    ${manualGroup}
    ${dupeGroups.map(g => dupeGroupHtml(g, false)).join("")}</details>`;
  panel.querySelector("details").addEventListener("toggle",
    (ev) => { dupesOpen = ev.target.open; });
  for (const [sel, key] of [["#dupe-a", "a"], ["#dupe-b", "b"]]) {
    const input = panel.querySelector(sel);
    Autocomplete.attach(input, () => items.map(itemOption), (value) => {
      const id = optionId(value);
      if (id) {
        manualPair[key] = id;
        input.value = value;
        renderDupes();
      }
    });
  }
}

// Its own delegated listener rather than a branch of app.js's. The
// classes below are disjoint from every other section's, so an
// independent listener cannot change which branch wins -- unlike the
// catalog's chip-x/tag-x pair, whose order is load-bearing.
document.addEventListener("click", async (ev) => {
  const el = ev.target;
  if (el.classList.contains("cand-btn")) {
    armOrFire(el, async () => {
      await post(`/api/items/${el.dataset.id}/choose`, {candidate: +el.dataset.idx});
      await load();
    });
  } else if (el.classList.contains("url-fetch")) {
    const id = el.dataset.id;
    const box = document.querySelector(`.url-box[data-id="${id}"]`);
    const result = document.querySelector(`.url-result[data-id="${id}"]`);
    result.textContent = "Fetching...";
    const resp = await post(`/api/items/${id}/fetch_url`, {url: box.value.trim()});
    const data = await resp.json();
    if (!resp.ok) {
      result.textContent = data.error || "Could not fetch that URL.";
      return;
    }
    const c = data.candidate;
    result.innerHTML = c.link_only
      ? `<button class="apply-fetched" data-id="${id}">
          Couldn't read metadata (${esc(c.reason)}). Apply link only: ${esc(c.title)}</button>`
      : `<button class="apply-fetched" data-id="${id}">
          Apply: ${esc(c.title)} - ${esc((c.authors || []).join(", "))} (${esc(c.source)})</button>`;
    result.querySelector(".apply-fetched").dataset.candidate = JSON.stringify(c);
  } else if (el.classList.contains("apply-fetched")) {
    armOrFire(el, async () => {
      await post(`/api/items/${el.dataset.id}/apply`,
                 {candidate: JSON.parse(el.dataset.candidate)});
      await load();
    });
  } else if (el.classList.contains("dupe-keep")) {
    armOrFire(el, async () => {
      const resp = await post("/api/merge",
        {keep_id: +el.dataset.keep, drop_id: +el.dataset.drop});
      if (!resp.ok) {
        alert((await resp.json()).error || "Could not merge.");
        return;
      }
      manualPair = {a: null, b: null};
      await load();
    });
  } else if (el.classList.contains("dupe-dismiss")) {
    armOrFire(el, async () => {
      await post("/api/dismiss_pair",
        {id_a: +el.dataset.a, id_b: +el.dataset.b});
      await load();
    });
  } else if (el.id === "dupe-clear") {
    manualPair = {a: null, b: null};
    renderDupes();
  }
});
