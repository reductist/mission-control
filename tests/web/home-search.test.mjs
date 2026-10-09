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
  insertAdjacentHTML() {},
  setAttribute() {},
  textContent: "",
};
const context = {
  Date,
  Intl,
  JSON,
  Map,
  Promise,
  URL,
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
  `${source}\n;globalThis.homeSearchTest = {
    homeSearchEmptyState,
    providerInitiative,
    safeHttpUrl,
    renderHouse,
    setState(value, details) { dashboard = value; homeSearchDetails = new Map(details); },
    html() { return app.innerHTML; },
  };`,
  context,
);

const { homeSearchTest } = context;
const search = {
  id: "reading-ma-01867",
  kind: "initiative",
  title: "Reading home purchase search",
  detail: "No research snapshot has been imported.",
  revision: "1",
  source: {
    plugin_id: "home-search",
    entity_type: "search",
    entity_id: "reading-ma-01867",
  },
};

test("empty state never implies demo listings, a budget cap, or an active watcher", () => {
  const html = homeSearchTest.homeSearchEmptyState(
    "No verified search snapshot imported yet",
  );
  assert.match(html, /No verified research snapshot/);
  assert.match(html, /Budget is still unset/);
  assert.match(html, /daily watcher is not active/);
  assert.doesNotMatch(html, /demo|recommended home|affordability cap/i);
});

test("source links accept only http and https", () => {
  assert.equal(
    homeSearchTest.safeHttpUrl("https://example.test/listing"),
    "https://example.test/listing",
  );
  assert.equal(homeSearchTest.safeHttpUrl("javascript:alert(1)"), null);
  assert.equal(homeSearchTest.safeHttpUrl("not a url"), null);
});

test("house workflow renders contract details and review controls", () => {
  const candidate = {
    id: "reading-12-oak",
    kind: "action",
    title: "12 Oak Street <script>",
    detail: "Sourced candidate",
    revision: "3",
    source: {
      plugin_id: "home-search",
      entity_type: "candidate",
      entity_id: "reading-12-oak",
    },
  };
  const searchDetail = {
    attributes: [
      { key: "location", label: "Location", value: "Strictly Reading, MA 01867" },
      { key: "budget", label: "Purchase budget", value: "Provisional and unset" },
      { key: "freshness", label: "Freshness", value: "2026-10-09T11:30:00Z" },
    ],
  };
  const candidateDetail = {
    attributes: [
      { key: "verification", value: "verified" },
      { key: "review-status", value: "unreviewed" },
      { key: "listing-status", value: "active" },
      { key: "usable-indoor-space", value: "2,350 sq ft" },
      { key: "list-price", value: "$875,000" },
      { key: "why-fit", value: "Quiet side street" },
      { key: "tradeoffs", value: "AC needs inspection" },
      { key: "unknowns", value: "Confirm FiOS" },
      { key: "estimated-all-in", value: "$912,500 USD" },
      { key: "cost-confidence", value: "low" },
      { key: "cost-assumptions", value: "Closing costs • HVAC allowance" },
      { key: "source-url", value: "https://example.test/listing" },
      { key: "last-checked", value: "2026-10-09T11:30:00Z" },
    ],
  };
  const dashboard = {
    agenda: [search, candidate],
    providers: [{ id: "home-search", name: "Home Search" }],
  };
  homeSearchTest.setState(dashboard, [
    ["search:reading-ma-01867", searchDetail],
    ["candidate:reading-12-oak", candidateDetail],
  ]);

  homeSearchTest.renderHouse();
  const html = homeSearchTest.html();
  assert.match(html, /Strictly Reading, MA 01867/);
  assert.match(html, /Why it fits/);
  assert.match(html, /Tradeoffs/);
  assert.match(html, /Unknowns/);
  assert.match(html, /\$912,500 USD/);
  assert.match(html, /Closing costs • HVAC allowance/);
  assert.match(html, /data-review-status="shortlisted"/);
  assert.match(html, /Import research snapshot/);
  assert.match(html, /https:\/\/example.test\/listing/);
  assert.doesNotMatch(html, /<script>/);
});

test("overview initiative discovery uses the shared agenda contract", () => {
  homeSearchTest.setState({ agenda: [search], providers: [] }, []);
  assert.equal(
    homeSearchTest.providerInitiative("home-search").source.entity_id,
    "reading-ma-01867",
  );
});
