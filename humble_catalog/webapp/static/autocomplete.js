// Shared autocomplete dropdown for tag editors and filter inputs.
// Autocomplete.attach(input, optionsFn, onPick, countsFn):
//   optionsFn(): full suggestion list, recomputed on every keystroke
//   onPick(value, viaSuggestion): commit; viaSuggestion distinguishes a
//     picked suggestion (exact tag) from free-form typed text.
//   countsFn (optional): Map(tag -> item count); shown next to each
//     suggestion when provided.
// The input must sit inside a position:relative wrapper (.ac-wrap).
//
// Exposed as the WAI-ARIA combobox pattern (#150): the input is a
// combobox, the list a listbox of options, and the highlighted option is
// named by aria-activedescendant while focus stays in the field. Without
// it a screen reader heard neither the list nor the arrow keys' choice.
const Autocomplete = (() => {
  // At most one list is open at a time, so it lives here rather than per
  // input - but every handler must then check the open list is its own.
  let openList = null, openOwner = null, openClip = null;
  // Fields with no id still need a unique id for their list.
  let unnamed = 0;

  function close() {
    if (openOwner) {
      // Collapsed state on the field that owned the list. aria-controls
      // goes with the list, so it never points at an element that is gone.
      openOwner.setAttribute("aria-expanded", "false");
      openOwner.removeAttribute("aria-activedescendant");
      openOwner.removeAttribute("aria-controls");
    }
    if (openList) { openList.remove(); openList = null; openOwner = null; }
    openClip = null;
  }

  // Nearest clipping ancestor, or null for a field that nothing clips.
  // Resolved once per open rather than per scroll event: the anchor cannot
  // move between elements while its list is up.
  function scrollParent(el) {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (getComputedStyle(p).overflow !== "visible") return p;
    }
    return null;
  }

  // The list is position:fixed on <body>, not a sibling of the input, so
  // that <main>'s overflow cannot clip it. That buys freedom from the
  // scroll container at the cost of viewport coordinates: nothing moves
  // the list with its anchor any more, so re-anchor it by hand.
  function reposition() {
    if (!openList || !openOwner) return;
    // A table row rebuild used to take an in-cell list down with it. A
    // body-level list outlives its anchor, so it has to notice itself -
    // a detached input measures as 0x0 and would strand the list at the
    // top-left corner.
    if (!openOwner.isConnected) { close(); return; }
    const r = openOwner.getBoundingClientRect();
    // Flip above the field when the space below cannot hold the list and
    // the space above is roomier; the table pane can be short.
    const below = window.innerHeight - r.bottom;
    const flip = below < openList.offsetHeight && r.top > below;
    openList.style.top = (flip ? r.top - openList.offsetHeight : r.bottom) + "px";
    // width: max-content lets the list outgrow its field, so a field near
    // the right edge needs clamping back into the viewport.
    openList.style.left = Math.max(0, Math.min(
      r.left, document.documentElement.clientWidth - openList.offsetWidth)) + "px";
    // Escaping the clipping also means an anchor scrolled out of its pane
    // no longer takes its list with it - it would float over whatever the
    // pane sits under. Reinstate that one clip rect by hand.
    if (openClip) {
      const c = openClip.getBoundingClientRect();
      openList.style.visibility =
        (r.bottom <= c.top || r.top >= c.bottom) ? "hidden" : "";
    }
  }

  // Scroll events from a nested container do not bubble, and the list's
  // anchor now lives inside one - hence the capture phase.
  window.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);

  function attach(input, optionsFn, onPick, countsFn) {
    let sel = -1;
    const owned = () => openList && openOwner === input;
    const listId = `${input.id || "ac-field-" + (++unnamed)}-suggestions`;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");

    const commit = (value, viaSuggestion) => {
      if (owned()) close();
      onPick(value, viaSuggestion);
    };

    const show = () => {
      close();
      sel = -1;
      const q = input.value.trim().toLowerCase();
      const matches = optionsFn()
        .filter(o => o.toLowerCase().includes(q)).slice(0, 12);
      if (!matches.length) return;
      const counts = countsFn ? countsFn() : null;
      openList = document.createElement("div");
      openOwner = input;
      openList.className = "ac-list";
      openList.id = listId;
      openList.setAttribute("role", "listbox");
      openList.setAttribute("aria-label", "Suggestions");
      // The list scrolls and holds no focusable children, which makes
      // Chrome treat it as a "focusable scroller" and give it a tab stop
      // of its own - swallowing the Tab that should reach the next
      // field. An explicit -1 keeps it out of sequential navigation.
      openList.tabIndex = -1;
      matches.forEach((m, n) => {
        const d = document.createElement("div");
        d.className = "ac-item";
        d.id = `${listId}-${n}`;
        d.setAttribute("role", "option");
        d.setAttribute("aria-selected", "false");
        d.textContent = m;
        // the count span makes textContent unusable as the commit
        // value, so every row carries it in dataset.value instead
        d.dataset.value = m;
        if (counts && counts.has(m)) {
          const c = document.createElement("span");
          c.className = "ac-count";
          c.textContent = counts.get(m);
          d.appendChild(c);
          // Said as "Fantasy, 3", not run together as "Fantasy3".
          d.setAttribute("aria-label", `${m}, ${counts.get(m)}`);
        }
        // mousedown, not click: fires before blur tears the list down
        d.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          commit(m, true);
        });
        openList.appendChild(d);
      });
      // Anchor the popup to the input, not to wherever it lands in the
      // flow: .ac-wrap also holds chips, which wrap onto extra lines and
      // would otherwise drag the list sideways and up. It must be in the
      // document before reposition() can measure it.
      document.body.appendChild(openList);
      input.setAttribute("aria-controls", listId);
      input.setAttribute("aria-expanded", "true");
      openClip = scrollParent(input);
      reposition();
    };

    // Deliberately not bound to focus: opening on focus meant the list
    // flashed up every time a field was clicked. Typing opens it, and
    // the arrow keys summon it on demand.
    input.addEventListener("input", show);
    // Only ever close our own list: by the time this fires another input
    // may have opened one, and closing that is what made a freshly opened
    // list vanish when moving quickly between fields.
    input.addEventListener("blur", () => setTimeout(() => {
      if (owned()) close();
    }, 100));
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        // summon the list if ours is not showing, starting just outside
        // the end the arrow moves away from so the first press lands on
        // an edge. show() replaces any other input's list with our own.
        if (!owned()) show();
        if (!owned()) return;
        if (sel === -1 && ev.key === "ArrowUp") sel = 0;
        const opts = [...openList.children];
        if (!opts.length) return;
        sel = (sel + (ev.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
        opts.forEach((el, i) => {
          el.classList.toggle("sel", i === sel);
          el.setAttribute("aria-selected", String(i === sel));
        });
        input.setAttribute("aria-activedescendant", opts[sel].id);
        opts[sel].scrollIntoView?.({block: "nearest"});
        return;
      }
      // never read values out of a list belonging to another input
      const opts = owned() ? [...openList.children] : [];
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (sel >= 0 && opts[sel]) commit(opts[sel].dataset.value, true);
        else if (input.value.trim()) commit(input.value.trim(), false);
      } else if (ev.key === "Escape") {
        if (owned()) close();
      }
    });
  }

  return { attach, close };
})();
