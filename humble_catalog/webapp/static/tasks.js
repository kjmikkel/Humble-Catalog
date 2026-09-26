// The Tasks section: start a catalog command and watch it run.
//
// Every card posts to /api/jobs/start, whose whitelist (jobs.COMMANDS) is
// the authority on what may run -- except the cards marked `handoff`,
// which post to /api/jobs/handoff and are a menu of handoff.COMMANDS.
// login, reset and restore need a terminal: the viewer steps down, runs
// them in the console `serve` was started from, and comes back. The cards
// here are a menu of those two whitelists, never a second definition of
// either -- a test pins each set equal.
const TASK_CARDS = [
  // The one card a routine update needs (#101). update runs the Update
  // and Enrich cards below in order, in one job.
  {group: "Update everything", command: "update", label: "Update everything",
   note: "Fetches new bundles, harvests their metadata, then matches and fills. "
       + "Stops at the first failure, but a spent daily quota does not stop it: "
       + "running it again later continues the harvest. Minutes for a few new "
       + "bundles, hours on a first run."},
  {group: "Update everything", command: "update",
   label: "Update everything, and game libraries", options: {games: true},
   note: "The same, then imports your game libraries so bundle and key "
       + "checks see new games too."},
  {group: "Update", command: "extract", label: "Fetch new bundles",
   note: "Asks HumbleBundle for purchases you have not catalogued yet. Minutes."},
  {group: "Update", command: "login", label: "Log in to HumbleBundle",
   handoff: true,
   note: "Opens a browser window to sign in. Needed when a fetch says the session expired."},
  {group: "Update", command: "reparse", label: "Rebuild from the cache",
   note: "Re-reads bundles already downloaded. No network. Seconds."},
  {group: "Enrich", command: "harvest", label: "Harvest metadata",
   note: "Fetches every source for every title. Hours, and resumable."},
  {group: "Enrich", command: "harvest", label: "Harvest, ignoring quota",
   options: {ignore_quota: true},
   note: "Retries sources recorded as out of quota. Use after adding a key."},
  {group: "Enrich", command: "enrich", label: "Match and fill",
   note: "Matches the harvested cache to your items. Seconds."},
  {group: "Enrich", command: "enrich", label: "Match, retrying misses",
   options: {retry: true},
   note: "Also re-scores items that previously found no match."},
  {group: "Enrich", command: "enrich", label: "Fill comic credits",
   options: {credits: true},
   note: "Writer and illustrator for matched comics. Slower; resumable."},
  {group: "Enrich", command: "enrich", label: "Fill series from titles",
   options: {series: true},
   note: "Reads \"Vol. 2\" out of a title where no source supplied it."},
  {group: "Import", command: "import_sheets", label: "Import a spreadsheet",
   note: "Ratings and metadata from an .xlsx. Choosing a file below starts the import."},
  {group: "Import", command: "import_games", label: "Import game libraries",
   note: "Reads Heroic's caches and Steam's Web API. No login."},
  {group: "Backup", command: "backup", label: "Back up the catalog",
   note: "A timestamped snapshot in backups/. Nothing is ever deleted."},
  {group: "Backup", command: "backup", label: "Back up with covers",
   options: {covers: true},
   note: "The snapshot plus a zip of covers/. Larger and slower."},
  {group: "Backup", command: "restore", label: "Restore a snapshot",
   handoff: true, picker: "snapshot",
   note: "Puts a backup back over the catalog, after snapshotting the current one."},
  {group: "Diagnose", command: "check", label: "Test every source",
   note: "One live search per metadata API, to see which keys work."},
  {group: "Danger", command: "reset", label: "Reset the catalog",
   handoff: true,
   note: "Wipes the derived catalog for a clean rebuild. Keeps downloads, covers and your ratings, tags and notes."},
];

// Danger is last and set apart: reset is the one card whose worst case
// is losing hand edits, merges and overrides.
const TASK_GROUPS = ["Update everything", "Update", "Enrich", "Import",
                     "Backup", "Diagnose", "Danger"];
// Set apart from the rest, which are its steps and the occasional extras.
const PRIMARY_GROUP = "Update everything";

function taskCard(c) {
  const picker = c.picker === "snapshot" ? `
    <div class="task-picker">
      <select id="restore-snapshot" aria-label="Snapshot to restore"></select>
      <label><input type="checkbox" id="restore-covers"> with covers</label>
    </div>` : "";
  return `
    <div class="task-card">
      <div class="task-label">${esc(c.label)}${c.handoff
        ? ` <span class="task-terminal">uses the terminal</span>` : ""}</div>
      <div class="task-note">${esc(c.note)}</div>
      ${picker}
      ${c.command === "import_sheets" ? `
      <div id="task-upload">
        <label class="sheet-choose" for="sheet-file">Choose spreadsheet
          <input id="sheet-file" type="file" accept=".xlsx" aria-describedby="sheet-filename">
        </label>
        <span id="sheet-filename" role="status">No file selected</span>
      </div>` : ""}
      <button class="task-go"${c.picker === "snapshot" ? ' id="restore-go"' : ""}
              data-command="${esc(c.command)}"${c.handoff ? ' data-handoff="1"' : ""}
              data-options='${esc(JSON.stringify(c.options || {}))}'
              >Run</button>
    </div>`;
}

function renderTasks() {
  const el = $("#task-cards");
  if (!el) return;
  el.innerHTML = TASK_GROUPS.map((group) => `
    <div class="task-group${group === "Danger" ? " task-danger" : ""}${
        group === PRIMARY_GROUP ? " task-primary" : ""}">
      <h3>${esc(group)}</h3>
      ${TASK_CARDS.filter((c) => c.group === group).map(taskCard).join("")}
    </div>${group === PRIMARY_GROUP
      ? `<h2 class="task-steps-heading">Individual steps</h2>` : ""}`).join("");
  return el.innerHTML;
}

// Reported through the panel rather than alert(): a refusal here is
// usually "something is already running", which is information about the
// page's own state and belongs on the page.
function taskMessage(text) {
  const el = $("#task-message");
  if (el) el.textContent = text || "";
}

async function startTask(command, options) {
  taskMessage("");
  const resp = await post("/api/jobs/start", {command, options});
  if (resp.status === 409) {
    // The one refusal with a second answer available: a run recorded as
    // active may simply be stale, so offer force rather than dead-ending.
    const {error} = await resp.json();
    taskMessage(`${error} Click Run again within 3 seconds to start anyway.`);
    return "busy";
  }
  if (!resp.ok) {
    taskMessage((await resp.json()).error || "Could not start that.");
    return "error";
  }
  await pollJobs();
  return "started";
}

if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest && ev.target.closest(".task-go");
    if (!btn) return;
    const command = btn.dataset.command;
    const options = JSON.parse(btn.dataset.options || "{}");
    if (btn.dataset.handoff) {
      // Two clicks only ARM the handoff. reset and restore still ask for
      // a word typed at the console; that, not this, is the real guard.
      armOrFire(btn, () => startHandoff(command, options));
      return;
    }
    if (command === "import_sheets") {
      // Nothing to start without a file; the picker IS this card's action.
      $("#sheet-file").click();
      return;
    }
    // Two clicks for every card, not just the risky ones: these all cost
    // real time or real network, and the arm text is the only place the
    // page can say so before it happens.
    armOrFire(btn, async () => {
      if (await startTask(command, options) === "busy")
        armOrFire(btn, () => post("/api/jobs/start",
                                  {command, options, force: true}));
    });
  });
}

// The one child failure the page translates rather than shows raw. The
// fix is a command in a terminal, and a user who is here precisely to
// avoid terminals needs to be told plainly which one.
const EXPIRED = /session (expired|missing)/i;

// --- The job log -------------------------------------------------------
// The panel used to be rebuilt from innerHTML on every poll, which threw
// away the <pre>'s scroll position (it came back at the top), the focus
// on Cancel and any selected text. Now a poll patches the parts that
// change, and the panel is only rebuilt when its SHAPE changes -- a job
// starting or ending, a hint appearing -- because then the elements
// themselves differ.

// How close to the bottom still counts as "at the bottom". A wheel notch
// or a rounded-up line height should not read as the user scrolling away.
const FOLLOW_SLACK = 24;
// Ticked on every page load, deliberately not remembered: a job you have
// just started is one you are watching.
let followLog = true;
// What is on screen now: the shape signature, and the lines the <pre>
// already holds.
let jobShape = null;
let shownLog = [];

function atBottom(pre, slack = FOLLOW_SLACK) {
  return pre.scrollHeight - pre.scrollTop - pre.clientHeight <= slack;
}

function logShift(prev, next) {
  // How many lines fell off the top of `prev` to make `next`.
  if (!prev.length) return 0;
  for (let k = 0; k < prev.length; k++) {
    const n = prev.length - k;
    if (n > next.length) continue;
    let same = true;
    for (let i = 0; i < n; i++)
      if (prev[k + i] !== next[i]) { same = false; break; }
    if (same) return k;
  }
  return prev.length;   // nothing in common: a different run's log
}

function applyLog(pre, next, {follow = followLog, prev = shownLog} = {}) {
  // Put `next` in the <pre>, keeping the reader where they were.
  //
  // Following means pinning to the bottom. Not following means the lines in
  // view must not move, and keeping scrollTop is not enough for that: the
  // page shows the last 200 lines, so lines leaving the top shift everything
  // up by their height. That height cannot be measured from a single write
  // (a write both trims the head and appends a tail), so the head is removed
  // first, measured, and the tail added after.
  //
  if (!pre) return shownLog;
  if (follow) {
    pre.textContent = next.join("\n");
    pre.scrollTop = pre.scrollHeight;
  } else {
    const top = pre.scrollTop, before = pre.scrollHeight;
    const dropped = logShift(prev, next);
    if (dropped) pre.textContent = prev.slice(dropped).join("\n");
    const removed = dropped ? before - pre.scrollHeight : 0;
    pre.textContent = next.join("\n");
    pre.scrollTop = Math.max(0, top - removed);
  }
  shownLog = next.slice();
  return shownLog;
}

function jobLogHtml(log) {
  // esc() is not optional here: these lines are the child's stdout, which
  // names owned titles verbatim and is nobody's idea of trusted markup.
  return `<div class="job-log-head">
      <label><input type="checkbox" id="job-follow"${followLog ? " checked" : ""}>
        Follow output</label>
    </div>
    <pre class="job-log" id="job-log">${esc(log.slice(-200).join("\n"))}</pre>`;
}

function renderJobPanel(state) {
  const el = $("#job-panel");
  if (!el) return;
  const running = state.running;
  // run_status is written by the CHILD, so there is a window after the
  // spawn where a job is running and no row exists yet. `|| null` keeps
  // that window a bar-less "starting" rather than a thrown renderer.
  const row = (state.progress || []).find(
    (p) => running && p.command === running.command) || null;
  const parts = [];
  if (running) {
    const bar = row
      ? `<progress id="job-bar" value="${row.done}" max="${row.total || 1}"></progress>
         <span class="job-count" id="job-count">${esc(row.phase)} ${row.done}/${row.total}</span>
         <span class="job-current" id="job-current">${esc(row.current || "starting")}</span>`
      : `<span class="job-count" id="job-count">starting</span>`;
    parts.push(`<div class="job-head"><strong>${esc(running.command)}</strong>
                  ${bar}
                  <button id="job-cancel">Cancel</button></div>`);
  } else if (state.last) {
    const {command, state: how, exit_code: code} = state.last;
    // "cancelled" is its own word, never folded into failure: an
    // interrupted child exits non-zero by definition, and calling the
    // user's own deliberate stop a failure sends them hunting a fault
    // that is not there.
    const verdict = how === "done" ? "finished"
                  : how === "cancelled" ? "cancelled"
                  : `failed (exit ${esc(code)})`;
    parts.push(`<div class="job-head"><strong>${esc(command)}</strong>
                  <span class="job-verdict job-${esc(how)}">${verdict}</span></div>`);
  }
  // The terminal is where a handed-over command reports what it did (reset
  // exits 0 on an abort too), so the page only says that it ran.
  const handed = state.handoff && state.handoff.last;
  if (handed)
    parts.push(`<div class="job-handoff"><strong>${esc(handed.command)}</strong>
      ran in the terminal${handed.exit_code === null ? " and was interrupted"
        : ` (exit ${esc(handed.exit_code)})`}; the terminal shows what it did.</div>`);
  const log = state.log || [];
  const hint = log.some((line) => EXPIRED.test(line));
  if (hint)
    parts.push(`<div class="job-hint">Your HumbleBundle session has expired.
      <button class="task-go" data-command="login" data-handoff="1"
              data-options='{}'>Log in</button>
      (or run <code>python -m humble_catalog login</code> in the terminal
      running this viewer), then try again.</div>`);
  if (log.length) parts.push(jobLogHtml(log));
  // Rebuild only when the panel's SHAPE changes; a poll during a run
  // patches instead, so the log keeps its scroll position and Cancel
  // keeps the focus. The signature holds what decides which elements
  // exist, never the numbers that merely change.
  const shape = JSON.stringify([running && running.command, Boolean(row),
                                state.last && state.last.state, Boolean(handed),
                                hint, log.length > 0]);
  if (shape !== jobShape) {
    jobShape = shape;
    el.innerHTML = parts.join("");
    el.hidden = parts.length === 0;
    // The rebuild wrote the log as markup, so the <pre> already holds
    // these lines; record them, then honour the follow state.
    shownLog = log.slice(-200);
    const fresh = $("#job-log");
    if (fresh && followLog) fresh.scrollTop = fresh.scrollHeight;
    return el.innerHTML;
  }
  patchJobPanel(row, log);
  return el.innerHTML;
}

function patchJobPanel(row, log) {
  // The in-place path: only what a poll actually changes.
  const bar = $("#job-bar"), count = $("#job-count"), current = $("#job-current");
  if (row) {
    if (bar) { bar.value = row.done; bar.max = row.total || 1; }
    if (count) count.textContent = `${row.phase} ${row.done}/${row.total}`;
    if (current) current.textContent = row.current || "starting";
  }
  if (log.length) applyLog($("#job-log"), log.slice(-200));
}

// Jobs that change nothing the page draws from the catalog: a backup only
// adds a snapshot, which the list reload below covers, and check only
// prints. Every other job can change items, enrichment or keys.
const LEAVES_CATALOG_ALONE = ["backup", "check"];

// undefined, not null: a catalog with no job history reports last: null,
// and the first poll must still differ so it loads the list.
let lastFinished;
async function pollJobs() {
  const state = await (await fetch("/api/jobs")).json();
  renderJobPanel(state);
  const finished = state.last ? state.last.finished_at : null;
  if (finished !== lastFinished) {
    // The first poll only learns the history: a job that ended before the
    // page loaded is already in what boot()'s load() fetched.
    const firstPoll = lastFinished === undefined;
    lastFinished = finished;
    // A job that finished while the page watched may have changed the
    // catalog, which used to stay stale until a manual reload (#100).
    // Before loadBackups(): load() re-renders the task cards, and with
    // them the snapshot picker, which would come back empty.
    if (!firstPoll && finished
        && !LEAVES_CATALOG_ALONE.includes(state.last.command))
      await load().catch((err) => console.error("load() failed:", err));
    // Awaited so a test can count the request; still never fatal.
    await loadBackups().catch((err) =>
      console.error("loadBackups() failed:", err));
  }
}

function renderBackups(list) {
  const sel = $("#restore-snapshot");
  const go = $("#restore-go");
  if (!sel) return "";
  sel.innerHTML = list.length
    ? list.map((b) => `<option value="${esc(b.name)}">${esc(b.modified)}
        (${esc((b.size / 1e6).toFixed(1))} MB${b.covers ? ", covers" : ""})
        </option>`).join("")
    : `<option value="">No snapshots in backups/ yet</option>`;
  sel.disabled = list.length === 0;
  if (go) go.disabled = list.length === 0;
  return sel.innerHTML;
}

async function loadBackups() {
  const {backups} = await (await fetch("/api/backups")).json();
  renderBackups(backups || []);
}

// What to look at while the viewer is away. Shown only AFTER the second
// click -- the arm text on the button is the warning; this is the
// instruction.
const TAKEOVER_TEXT = {
  login: "A browser window is opening. Sign in to HumbleBundle, wait "
       + "for your library page, then close that window.",
  reset: "Switch to the terminal window you started the viewer from. "
       + "It asks you to type RESET; anything else cancels and changes "
       + "nothing.",
  restore: "Switch to the terminal window you started the viewer from. "
         + "It shows both catalogs and asks you to type RESTORE; anything "
         + "else cancels. The current catalog is snapshotted first.",
};

function renderTakeover(command) {
  const el = $("#handoff-screen");
  el.innerHTML = `<div class="handoff-box">
      <h2>${esc(command)} is running in the terminal</h2>
      <p>${esc(TAKEOVER_TEXT[command] || "")}</p>
      <p>The viewer is closed until it finishes. This page will reconnect
         by itself.</p>
    </div>`;
  el.hidden = false;
  return el.innerHTML;
}

function handoffBody(command, options) {
  if (command !== "restore") return {command, options};
  return {command,
          options: {covers: Boolean($("#restore-covers").checked)},
          snapshot: $("#restore-snapshot").value};
}

// Reload once the server answers with a generation past the one the
// request was answered with. Polling "/" alone cannot tell "back" from
// "not gone down yet": the first poll can land before the server steps
// down, and a reload then meets a refused connection mid-handoff. There is
// no timeout: a user reading the reset prompt may take minutes.
async function reconnect(generation,
                         sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
  for (;;) {
    await sleep(1000);
    try {
      const state = await (await fetch("/api/jobs")).json();
      if (state.handoff && state.handoff.generation > generation) {
        location.reload();
        return;
      }
    } catch (err) {
      // Refused while the command runs. That is the expected state.
    }
  }
}

async function startHandoff(command, options, sleep) {
  taskMessage("");
  const resp = await post("/api/jobs/handoff", handoffBody(command, options));
  if (!resp.ok) {
    taskMessage((await resp.json()).error || "Could not hand that over.");
    return "error";
  }
  const {generation} = await resp.json();
  renderTakeover(command);
  await reconnect(generation, sleep);
  return "handed";
}

async function uploadSheet(file) {
  // FileReader gives base64 via a data: URL, whose payload sits after the
  // comma. The endpoint takes JSON only -- see its docstring for why a
  // multipart form is not an option here.
  const b64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const resp = await post("/api/jobs/import-sheets",
                          {filename: file.name, content_b64: b64});
  if (!resp.ok) {
    taskMessage((await resp.json()).error || "Could not import that file.");
    return;
  }
  taskMessage(`Importing ${file.name}.`);
  await pollJobs();
}

if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("click", async (ev) => {
    if (ev.target && ev.target.id === "job-cancel") {
      await post("/api/jobs/cancel");
      await pollJobs();
    }
  });
  document.addEventListener("change", (ev) => {
    if (ev.target && ev.target.id === "sheet-file") {
      const file = ev.target.files[0];
      $("#sheet-filename").textContent = file ? file.name : "No file selected";
      if (file) uploadSheet(file);
    }
    if (ev.target && ev.target.id === "job-follow") {
      followLog = Boolean(ev.target.checked);
      const pre = $("#job-log");
      if (pre && followLog) pre.scrollTop = pre.scrollHeight;
    }
  });
  // Capture, because a scroll event does not bubble. Scrolling away from
  // the bottom unticks the box and scrolling back ticks it, so the box
  // always says what the view is doing. The page's own scrollTop writes
  // land where they should -- pinned to the bottom while following, away
  // from it while not -- so neither flips the state by accident.
  document.addEventListener("scroll", (ev) => {
    const pre = ev.target;
    if (!pre || pre.id !== "job-log") return;
    followLog = atBottom(pre);
    const box = $("#job-follow");
    if (box) box.checked = followLog;
  }, true);
}
