import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("mission_control/web/app.js", "utf8");
const css = readFileSync("mission_control/web/styles.css", "utf8");
const element = {
  addEventListener() {},
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  content: "live",
  innerHTML: "",
  setAttribute() {},
  textContent: "",
};
const context = {
  CSS: { escape: (value) => value },
  Date,
  Intl,
  Map,
  Promise,
  Set,
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
  `${source}\n;globalThis.hierarchyTest = {
    renderTaskHierarchy, taskTextPreview, normalizeTag, parentTaskForEntry,
    sectionTaskHierarchy, scheduleRow, calendarEntryChip, closedItemRow,
    expand(id) { expandedParents.add(id); },
    setState(value) { dashboard = value; },
  };`,
  context,
);

const { hierarchyTest } = context;
const parent = {
  id: "parent", title: "Prepare the synthetic workshop", description: "Coordinate the plan",
  state: "in-progress", children_count: 2, sibling_order: 0, updated_at: "r1", tags: [],
};
const first = {
  id: "first", parent_id: "parent", title: "Book room", description: "Confirm access",
  state: "done", sibling_order: 0, updated_at: "r2", tags: [],
};
const second = {
  id: "second", parent_id: "parent", title: "Invite participants", description: "Use a synthetic list",
  state: "canceled", sibling_order: 1, updated_at: "r3", tags: [],
};

test("parent rows are dense disclosures with derived progress and collapsed children", () => {
  hierarchyTest.setState({ tasks: [parent, second, first], task_tag_catalog: [] });
  const collapsed = hierarchyTest.renderTaskHierarchy([parent, second, first]);
  assert.match(collapsed, /class="task-row [^"]*is-parent/);
  assert.match(collapsed, /aria-expanded="false"/);
  assert.match(collapsed, /1\/2 done · 1 canceled/);
  assert.match(collapsed, /data-add-child="parent"/);
  assert.doesNotMatch(collapsed, /class="task-children"/);

  hierarchyTest.expand("parent");
  const expanded = hierarchyTest.renderTaskHierarchy([parent, second, first]);
  assert.match(expanded, /aria-expanded="true"/);
  assert.match(expanded, /class="task-children"/);
  assert.ok(expanded.indexOf("Book room") < expanded.indexOf("Invite participants"));
  assert.match(expanded, /data-move-task="up"/);
  assert.match(expanded, /data-move-task="down"/);
});

test("unfinished children replace parent completion with an explicit explanation", () => {
  const waiting = { ...second, id: "waiting", state: "ready", title: "Waiting child" };
  const activeParent = { ...parent, children_count: 1, progress: { total: 1, done: 0, canceled: 0, unfinished: 1, ready_to_close: false } };
  const html = hierarchyTest.renderTaskHierarchy([activeParent, waiting]);
  assert.match(html, /data-show-unfinished="parent"/);
  assert.match(html, /1 unfinished child tasks/);
  assert.doesNotMatch(html, /data-entity-id="parent"[^>]+data-command="set-state"/);
});

test("the last closed child surfaces ready-to-close without completing its parent", () => {
  const readyParent = { ...parent, progress: { total: 1, done: 1, canceled: 0, unfinished: 0, ready_to_close: true } };
  const html = hierarchyTest.renderTaskHierarchy([readyParent, first]);
  assert.match(html, /Ready to close/);
  assert.match(html, /data-entity-id="parent"[^>]+data-command="set-state"/);
});

test("long text uses a literal ellipsis preview and retains escaped full text", () => {
  const value = `${"A".repeat(85)} <private>`;
  const html = hierarchyTest.taskTextPreview(value, "task:title", 72, "task-title-text");
  assert.match(html, /A{72}\.\.\./);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /A{85} &lt;private&gt;/);
  assert.doesNotMatch(html, /<private>/);
});

test("custom tag normalization combines capitalization and repeated spacing", () => {
  assert.equal(hierarchyTest.normalizeTag("  Weekend   Projects "), "weekend projects");
  assert.equal(hierarchyTest.normalizeTag("WEEKEND PROJECTS"), "weekend projects");
});

test("compatibility-equivalent custom tag text normalizes to one identity", () => {
  assert.equal(hierarchyTest.normalizeTag("ＭＯＬＤ"), "mold");
});

test("tag filters retain a closed parent as context for its matching open child", () => {
  const closedParent = { ...parent, state: "done", tags: [] };
  const taggedChild = { ...first, state: "ready", tags: ["yard"] };
  const result = hierarchyTest.sectionTaskHierarchy(["yard"], [closedParent, taggedChild]);
  assert.equal(result.matches.length, 1);
  assert.equal(result.roots.length, 1);
  assert.equal(result.roots[0].id, "parent");
  assert.equal(result.roots[0].filter_context, true);
  const html = hierarchyTest.renderTaskHierarchy(result.tasks, result.roots, true);
  assert.match(html, /Parent context/);
  assert.match(html, /Book room/);
});

test("schedule, calendar, and history bound core task text without nesting edit controls", () => {
  const longTitle = "Long synthetic task ".repeat(8);
  const longDetail = "Detailed synthetic context ".repeat(10);
  const task = { ...first, title: longTitle, description: longDetail, deadline: null };
  hierarchyTest.setState({ tasks: [parent, task], task_tag_catalog: [] });
  const entry = {
    id: task.id,
    kind: "action",
    title: longTitle,
    detail: longDetail,
    timing: { kind: "due-on", due_on: "2026-10-20" },
    source: { plugin_id: "core", entity_type: "task", entity_id: task.id },
  };
  assert.match(hierarchyTest.scheduleRow(entry), /expandable-text/);
  const calendar = hierarchyTest.calendarEntryChip(entry, "2026-10-20", "UTC");
  assert.match(calendar, /expandable-text/);
  assert.match(calendar, /data-edit-task="first"/);
  assert.doesNotMatch(calendar, /<button class="calendar-item/);
  const history = hierarchyTest.closedItemRow({
    ...entry,
    item_id: task.id,
    state: "done",
    closed_at: "2026-10-20T00:00:00+00:00",
    affordances: [],
  });
  assert.match(history, /expandable-text/);
});

test("dated child entries retain parent context", () => {
  hierarchyTest.setState({ tasks: [parent, first], task_tag_catalog: [] });
  const resolved = hierarchyTest.parentTaskForEntry({
    source: { plugin_id: "core", entity_type: "task", entity_id: "first" },
  });
  assert.equal(resolved.id, "parent");
});

test("mobile hierarchy keeps readable state and touch-sized ordering controls", () => {
  const mobile = css.slice(css.indexOf("@media (max-width: 680px)"));
  assert.match(mobile, /\.task-row\.is-parent \{ grid-template-columns: 44px minmax\(0, 1fr\); \}/);
  assert.match(mobile, /\.task-state \{ grid-column: 2; justify-items: start; \}/);
  assert.match(mobile, /\.reorder-controls button \{ min-width: 40px; min-height: 40px/);
  assert.match(mobile, /\.task-editor-dialog \{ width: calc\(100vw - 16px\)/);
});

test("child rows advertise keyboard reordering without stealing ordinary arrows", () => {
  assert.match(source, /event\.altKey/);
  assert.match(source, /\["ArrowUp", "ArrowDown"\]/);
  assert.match(source, /aria-label="Move \$\{escapeHtml\(task\.title\)\} up"/);
});
