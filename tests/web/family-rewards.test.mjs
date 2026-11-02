import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("mission_control/web/app.js", "utf8");
const classList = { add() {}, remove() {}, toggle() {} };
const element = { addEventListener() {}, classList, content: "live", innerHTML: "", setAttribute() {}, textContent: "" };
const context = {
  Date, Intl, JSON, Map, Promise, Set, URL, console,
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
vm.runInContext(`${source}\n;globalThis.rewardsTest = {
  renderRewards,
  rewardTaskState,
  setDetail(value) { familyRewardsDetail = value; rewardsDate = null; rewardsTaskDetails = new Map(); },
  setTaskDetails(value) { rewardsTaskDetails = new Map(value); },
  html() { return app.innerHTML; },
};`, context);

const settings = {
  timezone: "America/New_York",
  school_day_cap_minutes: 40,
  non_school_day_cap_minutes: 60,
  tasks: [
    { id: "one", label: "Safe <task>", minutes: 10 },
    { id: "two", label: "Two", minutes: 10 },
    { id: "three", label: "Three", minutes: 10 },
    { id: "four", label: "Four", minutes: 10 },
  ],
  windows: [],
};
const snapshot = {
  revision: "r1",
  local_date: "2026-11-02",
  balance_minutes: 0,
  tasks: settings.tasks.map((task) => ({ ...task, completed: false, award_entry_id: null })),
  effective_day: { windows: [] },
};

test("parent rewards view escapes task labels and explains non-enforcement", () => {
  context.rewardsTest.setDetail({
    source: { plugin_id: "family-rewards", entity_type: "account", entity_id: "family-credit" },
    revision: "r1",
    attributes: [
      { key: "rewards-snapshot", value: JSON.stringify(snapshot) },
      { key: "rewards-settings", value: JSON.stringify(settings) },
      { key: "rewards-overrides", value: "[]" },
    ],
    activity: [],
  });
  context.rewardsTest.renderRewards();
  const html = context.rewardsTest.html();
  assert.match(html, /Safe &lt;task&gt;/);
  assert.doesNotMatch(html, /Safe <task>/);
  assert.match(html, /No timer or device enforcement/);
  assert.match(html, /independently/);
  assert.equal((html.match(/data-reward-task=/g) || []).length, 4);
});

test("historical task state uses the date-specific entity detail", () => {
  const task = settings.tasks[0];
  const detail = {
    state: "checked",
    attributes: [{ key: "award-entry-id", value: "entry-synthetic" }],
  };
  context.rewardsTest.setTaskDetails([[task.id, detail]]);
  const result = context.rewardsTest.rewardTaskState.call(
    null,
    task,
    "2026-10-30",
    snapshot,
  );
  assert.equal(result.completed, true);
  assert.equal(result.award_entry_id, "entry-synthetic");
});
