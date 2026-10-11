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
    "house",
    "maintenance",
    "yard",
    "history",
  ]);
  assert.match(html, /id="navigator-toggle"[^>]+aria-controls="navigator-pane"/);
});

test("both sidebars have persistent controls and an outside-dismiss backdrop", () => {
  assert.match(html, /data-toggle-pane="navigator"/);
  assert.match(html, /data-toggle-pane="inspector"/);
  assert.match(html, /id="drawer-backdrop"/);
  assert.match(javascript, /drawerBackdrop\?\.addEventListener\("click", \(\) => closeDrawers\(\)\)/);
  assert.match(javascript, /if \(closeDrawers\(\)\) return;/);
});

test("narrow and standalone-compatible layouts use drawers without hiding the queue", () => {
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /\.workspace\.is-navigator-drawer-open \.navigator-pane/);
  assert.match(css, /\.workspace\.is-inspector-drawer-open \.inspector-pane/);
  assert.match(css, /\.queue-pane \{ min-height: calc\(100dvh - 48px\)/);
  assert.match(css, /\.workspace\.is-navigator-hidden\.is-inspector-hidden \{ grid-template-columns: minmax\(0, 1fr\); \}/);
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
