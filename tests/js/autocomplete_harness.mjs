// Runs autocomplete.js for real in a small DOM of its own (#150).
//
// The viewer harness (harness.mjs) stubs Autocomplete out entirely, and
// its element stub has no children, events or attribute removal -- all of
// which the combobox wiring is made of. This one is just big enough for
// one module: elements keep their children and attributes, listeners are
// recorded so a test can fire them, and layout answers zero.
//
// Usage: node autocomplete_harness.mjs <path-to-autocomplete.js> <expression>
// The expression runs with `Autocomplete`, `field(id)` (a connected input),
// `type(input, text)`, `key(input, name)` and `attrs(el)` in scope; its
// result is printed as JSON.
import fs from "node:fs";
import vm from "node:vm";

const [modulePath, expr] = process.argv.slice(2);

function makeEl(tag) {
  const listeners = {};
  const classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), id: "", value: "", dataset: {}, style: {},
    children: [], parentElement: null, attributes: {}, tabIndex: 0,
    offsetHeight: 0, offsetWidth: 0, _text: "",
    get className() { return [...classes].join(" "); },
    set className(v) { classes.clear(); for (const c of String(v).split(/\s+/)) if (c) classes.add(c); },
    classList: {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle(c, force) {
        const on = force === undefined ? !classes.has(c) : Boolean(force);
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
    },
    get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); },
    set textContent(v) { this._text = String(v); this.children = []; },
    get isConnected() {
      for (let p = this; p; p = p.parentElement) if (p === body) return true;
      return false;
    },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; },
    removeAttribute(name) { delete this.attributes[name]; },
    appendChild(child) { child.parentElement = this; this.children.push(child); return child; },
    remove() {
      const p = this.parentElement;
      if (p) p.children = p.children.filter((c) => c !== this);
      this.parentElement = null;
    },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    fire(type, ev = {}) {
      const event = {preventDefault() { event.defaultPrevented = true; }, ...ev};
      for (const fn of listeners[type] || []) fn(event);
      return event;
    },
    getBoundingClientRect: () => ({top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0}),
  };
  return el;
}

const body = makeEl("body");
const document = {
  body,
  documentElement: {clientWidth: 1280},
  createElement: (tag) => makeEl(tag),
};
const sandbox = {
  document, console,
  window: {innerHeight: 800, addEventListener() {}},
  getComputedStyle: () => ({overflow: "visible"}),
  setTimeout: (fn) => fn(),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(modulePath, "utf8")
  + "\n;globalThis.Autocomplete = Autocomplete;", sandbox);

sandbox.field = (id) => {
  const wrap = body.appendChild(makeEl("div"));
  const input = wrap.appendChild(makeEl("input"));
  input.id = id;
  return input;
};
sandbox.type = (input, text) => { input.value = text; input.fire("input"); };
sandbox.key = (input, name) => input.fire("keydown", {key: name});
sandbox.attrs = (el) => ({...el.attributes});
sandbox.openList = () => body.children.find((c) => c.className === "ac-list") || null;

const result = await vm.runInContext(`(async () => (${expr}))()`, sandbox);
process.stdout.write(JSON.stringify(result === undefined ? null : result));
