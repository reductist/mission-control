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
  `${source}\n;globalThis.scheduleTest = { calendarEntryIntersectsDay, calendarRange, civilDateValue, compareScheduleEntries, dateKeyInTimeZone, entryAccentToken, entryProvenance, escapeHtml, setDashboard(value) { dashboard = value; }, shiftCivilDate };`,
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

test("typed attribution resolves people and source without relying on color", () => {
  scheduleTest.setDashboard({
    attribution_catalog: {
      principals: [
        { id: "patrik", label: "Patrik", kind: "person" },
        { id: "elizabeth", label: "Elizabeth", kind: "person" },
      ],
      accents: [
        { token: "accent-2", target: { kind: "principal", principal_id: "elizabeth" } },
      ],
    },
    providers: [{ id: "google-calendar", name: "Google Calendar" }],
  });
  const entry = {
    source: { plugin_id: "google-calendar" },
    attribution: {
      principal_ids: ["patrik", "elizabeth"],
      integration: {
        connection: { id: "family", label: "Family Google" },
        collection: { id: "shared", kind: "calendar", label: "Family calendar" },
      },
    },
  };

  assert.equal(
    scheduleTest.entryProvenance(entry),
    "Patrik & Elizabeth — Family calendar · Family Google",
  );
  assert.equal(scheduleTest.entryAccentToken(entry), "accent-2");
});

test("conflicting shared-owner accents are order-independent", () => {
  scheduleTest.setDashboard({
    attribution_catalog: {
      principals: [
        { id: "a", label: "Alex", kind: "person" },
        { id: "b", label: "Alex", kind: "person" },
      ],
      accents: [
        { token: "accent-1", target: { kind: "principal", principal_id: "a" } },
        { token: "accent-2", target: { kind: "principal", principal_id: "b" } },
        { token: "accent-5", target: { kind: "plugin", plugin_id: "google-calendar" } },
      ],
    },
    providers: [{ id: "google-calendar", name: "Google Calendar" }],
  });
  const entry = (principalIds) => ({
    source: { plugin_id: "google-calendar" },
    attribution: { principal_ids: principalIds },
  });

  assert.equal(scheduleTest.entryAccentToken(entry(["a", "b"])), "accent-5");
  assert.equal(scheduleTest.entryAccentToken(entry(["b", "a"])), "accent-5");
  assert.equal(
    scheduleTest.entryProvenance(entry(["a", "b"])),
    "Alex & Alex — Google Calendar",
  );
});

test("collection accents are scoped by plugin and connection", () => {
  scheduleTest.setDashboard({
    attribution_catalog: {
      principals: [],
      accents: [
        {
          token: "accent-5",
          target: {
            kind: "collection",
            plugin_id: "google-calendar",
            connection_id: "home",
            collection_id: "shared",
          },
        },
      ],
    },
    providers: [{ id: "google-calendar", name: "Google Calendar" }],
  });
  const entry = (connection) => ({
    source: { plugin_id: "google-calendar" },
    attribution: {
      principal_ids: [],
      integration: {
        connection: { id: connection, label: `${connection} Google` },
        collection: { id: "shared", kind: "calendar", label: "Shared" },
      },
    },
  });

  assert.equal(scheduleTest.entryAccentToken(entry("home")), "accent-5");
  assert.equal(scheduleTest.entryAccentToken(entry("work")), "");
});

test("calendar ranges use civil dates across leap years and DST", () => {
  assert.deepEqual(
    [...scheduleTest.calendarRange("three-day", "2026-03-07").days],
    ["2026-03-07", "2026-03-08", "2026-03-09"],
  );
  assert.equal(scheduleTest.shiftCivilDate("2026-03-08", 1), "2026-03-09");

  const month = scheduleTest.calendarRange("month", "2024-02-15");
  assert.equal(month.days[0], "2024-01-28");
  assert.equal(month.days.at(-1), "2024-03-02");
  assert.ok(month.days.includes("2024-02-29"));
});

test("workweek and week ranges contain their anchor", () => {
  assert.deepEqual(
    [...scheduleTest.calendarRange("weekdays", "2026-08-12").days],
    ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"],
  );
  assert.deepEqual(
    [...scheduleTest.calendarRange("week", "2026-08-12").days],
    [
      "2026-08-09",
      "2026-08-10",
      "2026-08-11",
      "2026-08-12",
      "2026-08-13",
      "2026-08-14",
      "2026-08-15",
    ],
  );
});

test("multi-day all-day events honor their exclusive end", () => {
  const trip = {
    kind: "event",
    timing: { kind: "all-day", occurs_on: "2026-08-14", ends_before: "2026-08-17" },
  };

  assert.equal(scheduleTest.calendarEntryIntersectsDay(trip, "2026-08-14", "America/New_York"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(trip, "2026-08-16", "America/New_York"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(trip, "2026-08-17", "America/New_York"), false);
});

test("timed events use half-open local-day intersections", () => {
  const endingAtMidnight = {
    kind: "event",
    timing: {
      kind: "timed",
      starts_at: "2026-08-15T22:00:00-04:00",
      ends_at: "2026-08-16T00:00:00-04:00",
    },
  };
  const crossingMidnight = {
    kind: "event",
    timing: {
      kind: "timed",
      starts_at: "2026-08-15T22:00:00-04:00",
      ends_at: "2026-08-16T01:00:00-04:00",
    },
  };

  assert.equal(scheduleTest.calendarEntryIntersectsDay(endingAtMidnight, "2026-08-15", "America/New_York"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(endingAtMidnight, "2026-08-16", "America/New_York"), false);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(crossingMidnight, "2026-08-16", "America/New_York"), true);
});

test("due dates remain civil while due instants use the viewer timezone", () => {
  const dueOn = { kind: "action", timing: { kind: "due-on", due_on: "2026-08-15" } };
  const dueAt = { kind: "action", timing: { kind: "due-at", due_at: "2026-08-16T01:00:00Z" } };
  const anytime = { kind: "action", timing: { kind: "anytime" } };

  assert.equal(scheduleTest.calendarEntryIntersectsDay(dueOn, "2026-08-15", "Pacific/Honolulu"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(dueAt, "2026-08-15", "America/New_York"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(dueAt, "2026-08-16", "Europe/Zurich"), true);
  assert.equal(scheduleTest.calendarEntryIntersectsDay(anytime, "2026-08-15", "America/New_York"), false);
});
