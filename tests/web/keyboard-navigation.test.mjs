import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("mission_control/web/app.js", "utf8");
const classList = { add() {}, remove() {}, toggle() {} };
const element = {
  addEventListener() {},
  classList,
  content: "live",
  innerHTML: "",
  setAttribute() {},
  textContent: "",
};
const context = {
  Date,
  Intl,
  Map,
  Promise,
  URL,
  console,
  document: {
    activeElement: null,
    addEventListener() {},
    body: { contains: () => true },
    querySelector: () => element,
    querySelectorAll: () => [],
    visibilityState: "hidden",
  },
  fetch: () => new Promise(() => {}),
  setInterval() {},
  window: { confirm: () => true, innerWidth: 1024 },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  `${source}\n;globalThis.keyboardTest = { cycledPaneName, drawerStateAfterResize, fallbackPaneName, isNarrowViewport, isTypingTarget, movementForKey, nextDrawerState, paneForKey, paneToggleForKey, toggledPaneVisibility };`,
  context,
);

const { keyboardTest } = context;

test("S, D, and F select the three top-level panes", () => {
  assert.equal(keyboardTest.paneForKey("s"), "navigator");
  assert.equal(keyboardTest.paneForKey("D"), "queue");
  assert.equal(keyboardTest.paneForKey("f"), "inspector");
  assert.equal(keyboardTest.paneForKey("x"), null);
});

test("arrow keys and HJKL resolve to exactly the same movements", () => {
  assert.equal(keyboardTest.movementForKey("ArrowLeft"), keyboardTest.movementForKey("h"));
  assert.equal(keyboardTest.movementForKey("ArrowDown"), keyboardTest.movementForKey("j"));
  assert.equal(keyboardTest.movementForKey("ArrowUp"), keyboardTest.movementForKey("k"));
  assert.equal(keyboardTest.movementForKey("ArrowRight"), keyboardTest.movementForKey("l"));
});

test("Tab pane cycling wraps in both directions", () => {
  assert.equal(keyboardTest.cycledPaneName("navigator", 1), "queue");
  assert.equal(keyboardTest.cycledPaneName("queue", 1), "inspector");
  assert.equal(keyboardTest.cycledPaneName("inspector", 1), "navigator");
  assert.equal(keyboardTest.cycledPaneName("navigator", -1), "inspector");
});

test("typing guards cover native fields and editable content", () => {
  const target = (selector) => ({ matches: (query) => query.includes(selector) });
  assert.equal(keyboardTest.isTypingTarget(target("input")), true);
  assert.equal(keyboardTest.isTypingTarget(target("textarea")), true);
  assert.equal(keyboardTest.isTypingTarget(target("select")), true);
  assert.equal(keyboardTest.isTypingTarget(target("[contenteditable='true']")), true);
  assert.equal(keyboardTest.isTypingTarget(target("button")), false);
});

test("bracket shortcuts toggle sidebars without conflicting with pane focus keys", () => {
  assert.equal(keyboardTest.paneToggleForKey("["), "navigator");
  assert.equal(keyboardTest.paneToggleForKey("]"), "inspector");
  assert.equal(keyboardTest.paneToggleForKey("s"), null);
  assert.equal(keyboardTest.paneForKey("S"), "navigator");
  assert.equal(keyboardTest.paneForKey("F"), "inspector");
});

test("sidebar toggles are reversible and independent", () => {
  const initial = { navigator: true, inspector: true };
  const withoutNavigator = keyboardTest.toggledPaneVisibility(initial, "navigator");
  assert.equal(JSON.stringify(withoutNavigator), '{"navigator":false,"inspector":true}');
  assert.equal(
    JSON.stringify(keyboardTest.toggledPaneVisibility(withoutNavigator, "navigator")),
    JSON.stringify(initial),
  );
  assert.equal(
    JSON.stringify(keyboardTest.toggledPaneVisibility(initial, "inspector")),
    '{"navigator":true,"inspector":false}',
  );
});

test("drawers switch sides, close on repeat, and reset across layout changes", () => {
  assert.equal(keyboardTest.nextDrawerState(null, "navigator"), "navigator");
  assert.equal(keyboardTest.nextDrawerState("navigator", "inspector"), "inspector");
  assert.equal(keyboardTest.nextDrawerState("inspector", "inspector"), null);
  assert.equal(keyboardTest.drawerStateAfterResize("navigator", true, false), null);
  assert.equal(keyboardTest.drawerStateAfterResize("navigator", true, true), "navigator");
});

test("Pixel 7a and narrower widths use drawers and hidden panes fall back to queue", () => {
  assert.equal(keyboardTest.isNarrowViewport(412), true);
  assert.equal(keyboardTest.isNarrowViewport(320), true);
  assert.equal(keyboardTest.isNarrowViewport(681), false);
  assert.equal(keyboardTest.fallbackPaneName("navigator", ["queue"]), "queue");
  assert.equal(keyboardTest.fallbackPaneName("inspector", ["queue", "inspector"]), "inspector");
});
