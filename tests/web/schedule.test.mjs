import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync("mission_control/web/app.js", "utf8");
const classList = { add() {}, remove() {}, toggle() {} };
const element = {
  addEventListener() {},
  classList,
  content: "demo",
  insertAdjacentHTML() {},
  setAttribute() {},
  textContent: "",
};
const context = {
  Date,
  Intl,
  Promise,
  console,
  document: {
    addEventListener() {},
    body: { contains: () => true },
    querySelector: () => element,
    querySelectorAll: () => [],
    visibilityState: "hidden",
  },
  fetch: () => new Promise(() => {}),
  setInterval() {},
  window: { confirm: () => true },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(
  `${source}\n;globalThis.scheduleTest = { civilDateValue, compareScheduleEntries, dateKeyInTimeZone, escapeHtml };`,
  context,
);

const { scheduleTest } = context;

test("civil dates remain stable west of UTC", () => {
  assert.equal(
    new Date(scheduleTest.civilDateValue("2026-08-14")).toISOString(),
    "2026-08-14T00:00:00.000Z",
  );
});

test("timed entries sort by instant across New York and Zurich offsets", () => {
  const zurich = {
    id: "zurich",
    kind: "event",
    title: "Zurich",
    timing: {
      kind: "timed",
      starts_at: "2026-08-16T09:00:00+02:00",
      ends_at: "2026-08-16T09:30:00+02:00",
    },
  };
  const newYork = {
    id: "new-york",
    kind: "event",
    title: "New York",
    timing: {
      kind: "timed",
      starts_at: "2026-08-16T08:00:00-04:00",
      ends_at: "2026-08-16T08:30:00-04:00",
    },
  };

  assert.ok(scheduleTest.compareScheduleEntries(zurich, newYork, "Europe/Zurich") < 0);
  assert.equal(
    scheduleTest.dateKeyInTimeZone(zurich.timing.starts_at, "Europe/Zurich"),
    "2026-08-16",
  );
});

test("all-day rows precede timed rows on the same civil date", () => {
  const allDay = {
    id: "all-day",
    kind: "event",
    title: "All day",
    timing: { kind: "all-day", occurs_on: "2026-08-14" },
  };
  const timed = {
    id: "timed",
    kind: "event",
    title: "Early",
    timing: {
      kind: "timed",
      starts_at: "2026-08-14T00:30:00+02:00",
      ends_at: "2026-08-14T01:00:00+02:00",
    },
  };

  assert.ok(scheduleTest.compareScheduleEntries(allDay, timed, "Europe/Zurich") < 0);
});

test("provider text remains literal when rendered", () => {
  assert.equal(
    scheduleTest.escapeHtml('<img src=x onerror="alert(1)">'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
  );
});
