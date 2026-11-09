# UI/UX standards: Humble Catalog viewer

Decided standards. UI/UX passes review against these entries. Research
fills gaps but never overrides an entry here; if a source drifts, the
pass flags it and the owner decides. Ids are never reused.

Audience: one person cataloguing their own HumbleBundle purchases,
desktop browser first, plus the read-only LAN phone viewer (README.md:3,
README.md:8, README.md:37).

## Accessibility

### A11Y-1: Every control has an accessible name
Rule: Every user interface component has a name that can be programmatically determined (failure F68: a control without one).
Source: https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html
Status: decided 2026-11-09
Notes: A control repeated once per row or card names the item it acts on, with the visible word first: `aria-label="Run: Back up the catalog"`, `"Edit fields: <title>"`, `"Reading status: <title>"`. That keeps the visible label inside the name. (Owner decision P-1, 2026-11-09.)

### A11Y-2: Custom controls expose their state
Rule: States the user can set (pressed, selected, checked, expanded) can be programmatically determined, and changes to them are notified, using WAI-ARIA states.
Source: https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html
Status: decided 2026-11-09
Notes: Toggle chips and buttons use `aria-pressed`. Ratings are a `radiogroup` with roving tabindex, like the table's stars (catalog.js:192-260). Visual `.on` classes never stand alone.

### A11Y-3: Autocomplete fields follow the combobox pattern
Rule: The input has `role="combobox"`, `aria-expanded`, `aria-controls` and `aria-autocomplete="list"`; the popup is a `listbox` of `option`s; the highlighted option is tracked with `aria-activedescendant` and `aria-selected`.
Source: https://www.w3.org/WAI/ARIA/apg/patterns/combobox/
Status: decided 2026-11-09
Notes: There is one implementation, `static/autocomplete.js`. Every field uses it, and no field gets its own.

### A11Y-4: Non-text contrast 3:1
Rule: Graphics needed to understand content, and visual indicators of a component's state, have at least 3:1 contrast against adjacent colours.
Source: https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html
Status: decided 2026-11-09
Notes: Measured in both themes, against every background the element can sit on. Stars sit on two: the plain and the striped table row.

### A11Y-5: Text contrast 4.5:1
Rule: Text has at least 4.5:1 contrast (3:1 for large text: 18pt, or 14pt bold). Inactive components are exempt.
Source: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
Status: decided 2026-11-09
Notes: Includes small badges (0.7rem) in both themes.

### A11Y-6: Focus survives re-renders and returns to its trigger
Rule: Focus moves in an order that preserves meaning and operation. When a dialog, sheet or editor opened from a control is dismissed, focus returns to that control.
Source: https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html
Status: decided 2026-11-09
Notes: Any code that replaces `innerHTML` around the focused element puts focus back afterwards, using the same "re-render, then focus" approach as `setRating` (catalog.js:256-262). Focus never lands on `<body>`.

### A11Y-7: Status messages are programmatically exposed
Rule: A result or error that appears without moving focus is exposed through a role or property so assistive technology announces it.
Source: https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html
Status: decided 2026-11-09
Notes: `role="status"` for results and progress; `role="alert"` for errors. The region exists from first paint, not inserted along with its text (see the note at index.html:140-146).

### A11Y-8: Labels describe purpose
Rule: Headings and labels, where present, describe the topic or purpose of what they label.
Source: https://www.w3.org/WAI/WCAG22/Understanding/headings-and-labels.html
Status: decided 2026-11-09
Notes: No bare glyph ("×") and no bare count ("6") as a button's name. A `title` doesn't count, because text content outranks it.

### A11Y-9: No interactive content inside a button
Rule: An element with `role="button"` contains phrasing content only, "with no interactive content descendants".
Source: https://www.w3.org/TR/html-aria/ (§5, Allowed descendants of ARIA roles)
Status: decided 2026-11-09

## Feedback and content

### FEEDBACK-1: Visibility of system status
Rule: The design always keeps users informed about what is going on, through appropriate feedback.
Source: https://www.nngroup.com/articles/ten-usability-heuristics/ (#1)
Status: decided 2026-11-09
Notes: Every write either succeeds visibly, or undoes what it showed and says so. A network failure and an HTTP error are both failures. Every button that starts work shows that it is working ("Checking…"), and every submit gets a response, even an empty one.

### CONTENT-1: Errors in plain language, with a way out
Rule: Error messages say in plain language what went wrong, pinpoint the problem and suggest a fix.
Source: https://www.nngroup.com/articles/ten-usability-heuristics/ (#9)
Status: decided 2026-11-09
Notes: Say what to do next ("Paste a HumbleBundle URL first"), shown next to the control it concerns. An error is cleared when the action it describes is retried or replaced.

### CONTENT-2: The demo viewer only ever shows invented data
Rule: Any check that produces an image uses the demo catalog, and nothing the demo does can reach the real catalog, covers or backups.
Source: CLAUDE.md:16-33 (Privacy); scripts/demo_catalog.py:252-262
Status: decided 2026-11-09
Notes: Includes jobs started from the demo's Tasks tab (#143).

### CONTENT-3: Column labels match the table
Rule: Wherever the viewer names a catalog field, it uses the label the table header uses.
Source: https://www.nngroup.com/articles/ten-usability-heuristics/ (#2, #4); owner decision P-3, 2026-11-09
Status: decided 2026-11-09
Notes: Where the raw field name matters, as in the export column picker whose names become CSV headers, show the field name after the friendly label: "Mine (my_rating)".

## Layout and format

### LAYOUT-1: Table text is readable without a pointer
Rule: Text columns have a minimum width (about 9ch). Author, genre and similar chips wrap instead of being cut off with an ellipsis, so the full value is visible without a mouse tooltip, and words are not broken mid-word at desktop widths.
Source: owner decision P-2, 2026-11-09 (evidence: report 2026-11-09-whole-app P-2)
Status: decided 2026-11-09
Notes: More horizontal table scroll is accepted. Hiding columns by default stays open, as a separate view-column control, not the export picker.

### I18N-1: One date format, ISO 8601
Rule: Dates shown in the viewer use ISO 8601 (`2026-11-09`, and `2026-11-09 08:49` when a time is needed), never the browser locale.
Source: https://www.nngroup.com/articles/ten-usability-heuristics/ (#4); owner decision P-4, 2026-11-09
Status: decided 2026-11-09
Notes: Keys already does this. Bundles (end dates, "checked …") does not yet.
