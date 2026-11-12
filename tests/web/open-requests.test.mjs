import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("mission_control/web/app.js", "utf8");
function harness() {
  const classList = { add() {}, remove() {}, toggle() {} };
  const element = { addEventListener() {}, classList, content: "live", innerHTML: "", setAttribute() {}, textContent: "", focus() {} };
  const context = {
    Date, Intl, JSON, Map, Promise, Set, URL, console,
    document: { activeElement: null, addEventListener() {}, body: { contains: () => true }, querySelector: () => element, querySelectorAll: () => [], visibilityState: "hidden" },
    fetch: () => new Promise(() => {}), setInterval() {}, window: { innerWidth: 1024 },
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(`${source}\n;globalThis.testing = {
    requestRecords, requestTaskOptions, filteredRequests, requestCard, requestWebLinks, requestFromForm, renderOpenRequests, saveRequest, closeRequestEditor,
    setData(records, tasks = []) { openRequestsDetail = { revision: 'r1', attributes: records.map(item => ({ key: 'request:' + item.id, value: JSON.stringify(item) })) }; dashboard = { tasks }; },
    setFilter(status, tag, query) { requestStatus = status; requestTag = tag; requestQuery = query; },
    html() { return app.innerHTML; },
    setupSave(send, refreshFn, editor = { id: null, revision: 'r1', pending: false }) { requestEditor = editor; request = send; refresh = refreshFn; showNotice = () => {}; dialogClose = () => {}; return editor; },
    editor() { return requestEditor; },
  };`, context);
  return context.testing;
}
const record = (id, overrides = {}) => ({ id, title: "Repair portals", description: "Investigate <script>", status: "open", next_step: "Review the result", tags: ["gaming"], task_links: [], work_links: [], result_links: [], created_at: "2026-11-12T12:00:00Z", updated_at: "2026-11-12T12:00:00Z", ...overrides });
const serial = (value) => JSON.parse(JSON.stringify(value));

test("request filters default to unfinished and combine tag, query, and explicit status", () => {
  const t = harness();
  t.setData([record("a"), record("b", { status: "closed" }), record("c", { status: "ready", tags: ["home"], title: "Inspect house" })]);
  assert.deepEqual(serial(t.filteredRequests()).map(item => item.id), ["a", "c"]);
  t.setFilter("all", "gaming", "portal");
  assert.deepEqual(serial(t.filteredRequests()).map(item => item.id), ["a", "b"]);
  t.setFilter("ready", "", "house");
  assert.equal(t.filteredRequests()[0].id, "c");
});

test("many task links resolve current titles and preserve unavailable targets", () => {
  const t = harness();
  t.setData([], [{ id: "one", title: "Task one", state: "done" }, { id: "two", title: "Task two", state: "ready" }]);
  const selected = [{ plugin_id: "core", entity_type: "task", entity_id: "one" }, { plugin_id: "custom", entity_type: "action", entity_id: "lost" }];
  const options = serial(t.requestTaskOptions(selected));
  assert.equal(options.length, 3);
  assert.equal(options[0].title, "Task one");
  assert.equal(options[2].source.entity_id, "lost");
  assert.equal(options[2].state, "Not in current view");
  // A completed linked task must not close or mutate the request.
  const item = record("r", { task_links: selected });
  const html = t.requestCard(item);
  assert.match(html, /Task one/);
  assert.match(html, /custom \/ lost/);
  assert.equal(item.status, "open");
});

test("request text and links render safely, and missing solutions are explicit", () => {
  const t = harness(); t.setData([]);
  const html = t.requestCard(record("a", { title: '<img src=x onerror="bad()">', result_links: [{ label: "Bad link", url: "javascript:alert(1)" }], work_links: [{ label: "Work <1>", url: "https://example.com/?a=1&b=2" }] }));
  assert.doesNotMatch(html, /<img|<script|href="javascript:/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /Work &lt;1&gt;/);
  assert.match(t.requestCard(record("b")), /No result link yet/);
});

function form(values = {}) {
  const error = { textContent: "" };
  const buttons = [{ disabled: false }, { disabled: false }];
  return {
    error, buttons,
    elements: Object.fromEntries(Object.entries({ title: "Example", description: "", status: "open", next_step: "", request_tags: "one, two, one", ...values }).map(([name, value]) => [name, { value }])),
    querySelector: () => error,
    querySelectorAll: (selector) => selector === "button" ? buttons : [],
  };
}

test("form supports multiple tags and task references and rejects unsafe URLs", () => {
  const t = harness(); const f = form();
  const refs = [{ plugin_id: "core", entity_type: "task", entity_id: "one" }, { plugin_id: "core", entity_type: "task", entity_id: "two" }];
  f.querySelectorAll = (selector) => selector === '[name="request_tasks"]:checked' ? refs.map(value => ({ value: JSON.stringify(value) })) : [];
  const result = serial(t.requestFromForm(f));
  assert.deepEqual(result.tags, ["one", "two"]);
  assert.deepEqual(result.task_links, refs);
  f.querySelectorAll = (selector) => selector.includes("work_links") ? [{ querySelector: (key) => ({ value: key.includes("label") ? "Bad" : "file:///private" }) }] : [];
  assert.throws(() => t.requestFromForm(f), /valid HTTP\(S\)/);
});

test("saving captures editor revision, blocks duplicate submit and cancellation until outcome", async () => {
  const t = harness(); const f = form(); let release; const calls = [];
  const pending = new Promise(resolve => { release = resolve; });
  t.setupSave(async (path, options) => { calls.push(JSON.parse(options.body)); await pending; }, async () => {});
  const event = { preventDefault() {}, currentTarget: f };
  const first = t.saveRequest(event);
  await t.saveRequest(event);
  t.closeRequestEditor();
  assert.equal(calls.length, 1);
  assert.equal(t.editor().pending, true);
  assert.equal(calls[0].expected_revision, "r1");
  assert.equal(calls[0].command, "create-request");
  release(); await first;
  assert.equal(t.editor(), null);
});

test("stale save retains draft and old revision rather than overwriting new work", async () => {
  const t = harness(); const f = form({ title: "Unsaved draft" });
  t.setupSave(async () => { throw Object.assign(new Error("stale"), { status: 409 }); }, async () => {}, { id: "a", revision: "r1", pending: false });
  await t.saveRequest({ preventDefault() {}, currentTarget: f });
  assert.equal(f.elements.title.value, "Unsaved draft");
  assert.equal(t.editor().revision, "r1");
  assert.match(f.error.textContent, /draft is still here/);
  assert.equal(f.buttons[0].disabled, false);
  t.closeRequestEditor();
  assert.equal(t.editor(), null);
});

test("retry after an uncertain response reuses the identical command id", async () => {
  const t = harness(); const f = form(); const calls = [];
  t.setupSave(async (_path, options) => { calls.push(JSON.parse(options.body)); if (calls.length === 1) throw new Error("Connection lost"); }, async () => {});
  const event = { preventDefault() {}, currentTarget: f };
  await t.saveRequest(event);
  await t.saveRequest(event);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(t.editor(), null);
});
