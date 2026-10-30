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
  `${source}\n;globalThis.transformContact = (contact, values) => {
    editingContact = contact;
    const elements = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { value }]));
    return contactRecordFromForm({ elements });
  };`,
  context,
);

test("editing primary fields preserves extensions and secondary entries", () => {
  const original = {
    record: {
      "@type": "Card",
      version: "2.0",
      uid: "urn:uuid:synthetic-contact",
      kind: "individual",
      name: { full: "Alex Example", "example.invalid:phonetic": "ALEX" },
      emails: {
        primary: { "@type": "EmailAddress", address: "old@example.invalid", pref: 1 },
        secondary: { "@type": "EmailAddress", address: "other@example.invalid", pref: 2 },
      },
      phones: {
        primary: { "@type": "Phone", number: "+1-555-0100", pref: 1 },
        secondary: { "@type": "Phone", number: "+1-555-0102", pref: 2 },
      },
      "example.invalid:retained": { nested: true },
    },
  };

  const updated = context.transformContact(original, {
    kind: "individual",
    name: "Alex Updated",
    organization: "Synthetic Cooperative",
    email: "new@example.invalid",
    phone: "+1-555-0101",
    address: "",
  });

  assert.equal(updated.name.full, "Alex Updated");
  assert.equal(updated.name["example.invalid:phonetic"], "ALEX");
  assert.equal(updated.emails.primary.address, "new@example.invalid");
  assert.equal(updated.emails.secondary.address, "other@example.invalid");
  assert.equal(updated.phones.primary.number, "+1-555-0101");
  assert.equal(updated.phones.secondary.number, "+1-555-0102");
  assert.equal(JSON.stringify(updated["example.invalid:retained"]), '{"nested":true}');
});
