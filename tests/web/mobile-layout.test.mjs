import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync("mission_control/web/index.html", "utf8");
const css = readFileSync("mission_control/web/styles.css", "utf8");
const javascript = readFileSync("mission_control/web/app.js", "utf8");
const mobileCss = css.slice(
  css.indexOf("@media (max-width: 680px)"),
  css.indexOf("@media (max-width: 360px)"),
);

test("every workspace section remains represented by a touch button", () => {
  const sections = [...html.matchAll(/class="nav-item(?: is-active)?" data-view="([^"]+)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(sections, [
    "overview",
    "schedule",
    "contacts",
    "house",
    "maintenance",
    "yard",
    "history",
  ]);
  const mobileSections = [...html.matchAll(/class="mobile-section-tab(?: is-active)?" data-view="([^"]+)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(mobileSections, sections);
  assert.match(html, /class="mobile-section-tab is-active"[^>]+aria-current="page"/);
  assert.match(html, /id="navigator-toggle"[^>]+aria-controls="navigator-pane"/);
});

test("both sidebars have persistent controls and an outside-dismiss backdrop", () => {
  assert.match(html, /data-toggle-pane="navigator"/);
  assert.match(html, /data-toggle-pane="inspector"/);
  assert.match(html, /id="drawer-backdrop"/);
  assert.match(javascript, /drawerBackdrop\?\.addEventListener\("click", \(\) => closeDrawers\(\)\)/);
  assert.match(javascript, /if \(closeDrawers\(\)\) return;/);
});

test("narrow layouts use persistent tabs and only Inspector remains a drawer", () => {
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(mobileCss, /\.mobile-section-tabs \{/);
  assert.match(mobileCss, /overflow-x: auto/);
  assert.match(mobileCss, /\.workspace \.navigator-pane \{ display: none; \}/);
  assert.doesNotMatch(mobileCss, /is-navigator-drawer-open/);
  assert.match(css, /\.workspace\.is-inspector-drawer-open \.inspector-pane/);
  assert.match(css, /\.queue-pane \{ min-height: calc\(100dvh - 93px\)/);
  assert.match(css, /\.workspace\.is-navigator-hidden\.is-inspector-hidden \{ grid-template-columns: minmax\(0, 1fr\); \}/);
});

test("focused Inspector stays above its backdrop and legacy nav rules are scoped", () => {
  assert.doesNotMatch(css, /\.workspace-pane\.is-keyboard-active[^}]+z-index/);
  assert.match(mobileCss, /\.workspace \.inspector-pane \{[\s\S]*?z-index: 21/);
  assert.match(mobileCss, /\.drawer-backdrop:not\(\[hidden\]\) \{[\s\S]*?z-index: 20/);
  assert.match(css, /\.sidebar nav \{ grid-template-columns:/);
  assert.doesNotMatch(css, /\n\s*nav \{ grid-template-columns:/);
});

test("desktop keeps compact keyboard context and useful footer guidance", () => {
  assert.match(html, /class="keybar" aria-label="Keyboard shortcuts"/);
  assert.match(html, /<kbd>S<\/kbd> Sections/);
  assert.match(html, /<kbd>\[ \]<\/kbd> Sidebars/);
  assert.match(html, /Tab cycles visible panes · Esc goes back/);
  assert.match(css, /\.inline-key-hint \{ display: inline-block; \}/);
});

test("mobile hides shortcut chrome and inline hints but keeps optional help", () => {
  assert.match(html, /id="help-button"/);
  assert.match(mobileCss, /\.keybar, \.inline-key-hint \{ display: none; \}/);
  assert.match(mobileCss, /\.console-footer \{ display: none; \}/);
  assert.match(javascript, /\["\[ \/ \]", "Toggle the Sections or Inspector sidebar"\]/);
});

test("mobile readability raises tiny metadata, body copy, controls, and tabs", () => {
  assert.match(mobileCss, /\.mobile-section-tab \{[\s\S]*?font: 600 13px/);
  assert.match(mobileCss, /\.queue-header h1 \{ font-size: 20px; \}/);
  assert.match(mobileCss, /\.task-title \{ font-size: 14px; \}/);
  assert.match(mobileCss, /\.task-description[^}]+font-size: 12px/);
  assert.match(mobileCss, /\.quick-add input[^}]+font-size: 13px/);
  assert.match(mobileCss, /\.ops-summary span[^}]+font-size: 10px/);
});
