const app = document.querySelector("#app");
const token = document.querySelector('meta[name="mission-control-write-token"]').content;
const configuredMode = document.querySelector('meta[name="mission-control-mode"]').content;
const pageTitle = document.querySelector("#page-title");
const pageEyebrow = document.querySelector("#page-eyebrow");
const pageDescription = document.querySelector("#page-description");
const connectionLabel = document.querySelector("#connection-label");
const modeLabel = document.querySelector("#mode-label");
const versionLabel = document.querySelector("#version-label");
const statusDot = document.querySelector(".status-dot");

const viewCopy = {
  overview: {
    eyebrow: "Household overview",
    title: "The next right things",
    description: "A shared view of active work, decisions, and longer-term plans.",
  },
  house: {
    eyebrow: "House and finances",
    title: "Move only for a clear upgrade",
    description: "Keep the life goal, financial assumptions, and decision record in the same place.",
  },
  yard: {
    eyebrow: "Landscape and yard",
    title: "Maintain now, design deliberately",
    description: "Balance seasonal maintenance with projects that make the property easier to use and care for.",
  },
};

let dashboard = null;
let activeView = "overview";
let commandSequence = 0;

document.querySelector("#today-label").textContent = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
}).format(new Date());

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

function showView(view) {
  activeView = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  const copy = viewCopy[view];
  pageEyebrow.textContent = copy.eyebrow;
  pageTitle.textContent = copy.title;
  pageDescription.textContent = copy.description;
  render();
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["X-Mission-Control-Token"] = token;
  }
  const response = await fetch(path, { ...options, headers });
  const document = await response.json();
  if (!response.ok) {
    throw new Error(document?.error?.detail || `Request failed (${response.status})`);
  }
  return document;
}

async function refresh() {
  try {
    dashboard = await request("/api/dashboard");
    connectionLabel.textContent = "Online";
    modeLabel.textContent = dashboard.mode === "demo" ? "Synthetic demo workspace" : "Live workspace";
    versionLabel.textContent = `v${dashboard.version}`;
    statusDot.classList.add("is-online");
    app.setAttribute("aria-busy", "false");
    render();
  } catch (error) {
    connectionLabel.textContent = "Unavailable";
    modeLabel.textContent = "Could not load workspace";
    renderError(error);
  }
}

function render() {
  if (!dashboard) return;
  if (activeView === "house") {
    renderHouse();
  } else if (activeView === "yard") {
    renderYard();
  } else {
    renderOverview();
  }
}

function renderOverview() {
  const summary = dashboard.summary;
  const activeTasks = dashboard.tasks.filter((task) => task.state !== "done");
  const completedTasks = dashboard.tasks.filter((task) => task.state === "done").slice(0, 2);
  const visibleTasks = [...activeTasks, ...completedTasks].slice(0, 7);
  const house = dashboard.demo?.house;
  const yardEntries = landscapeEntries();
  const yardInitiative = yardEntries.find((entry) => entry.kind === "initiative");
  const yardActions = yardEntries.filter((entry) => entry.kind === "action");
  const visibleYardActions = yardActions.slice(0, 4);
  const visibleCoreTasks = visibleTasks.slice(0, Math.max(0, 7 - visibleYardActions.length));
  const visibleCount = visibleYardActions.length + visibleCoreTasks.length;
  const openWork = summary.open + yardActions.length;
  const blockedWork = summary.blocked + yardActions.filter((entry) => entry.state === "blocked").length;

  app.innerHTML = `
    <div class="metric-grid">
      ${metric("Open work", openWork, "Across core and enabled providers")}
      ${metric("In progress", summary.in_progress, "Work currently being moved")}
      ${metric("Blocked", blockedWork, blockedWork ? "Needs a decision or dependency" : "Nothing is stuck")}
      ${metric("Completed", summary.completed, "Durable task history retained")}
    </div>

    <div class="content-grid">
      <section class="panel">
        <div class="panel-header">
          <h2>Next up</h2>
          <span>${visibleCount} visible</span>
        </div>
        <div class="task-list">
          ${visibleCount ? `${visibleYardActions.map(landscapeActionRow).join("")}${visibleCoreTasks.map(taskRow).join("")}` : '<div class="empty">No tasks yet. Add the first shared task below.</div>'}
        </div>
        <form class="quick-add" id="quick-add-form">
          <input id="quick-add-title" name="title" required maxlength="160" placeholder="Add a shared task…" aria-label="New task title">
          <button class="primary-button" type="submit">Add task</button>
        </form>
      </section>

      <div class="stack">
        ${house ? previewCard("House", house.status, house.summary, "house") : livePlaceholder("House planning")}
        ${yardInitiative ? previewCard("Yard", yardInitiative.title, yardInitiative.detail, "yard") : livePlaceholder("Yard planning")}
      </div>
    </div>
  `;

  wireCommandButtons();
  document.querySelector("#quick-add-form").addEventListener("submit", addTask);
  document.querySelectorAll(".text-button[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
}

function renderHouse() {
  const house = dashboard.demo?.house;
  if (!house) {
    renderNoDemo("House planning", "Start mctrld with --demo to load the synthetic showcase workspace.");
    return;
  }
  app.innerHTML = `
    <div class="section-intro">
      <div>
        <h2>One decision model, many candidate homes</h2>
        <p>${escapeHtml(house.summary)}</p>
      </div>
      <div class="status-note">
        <strong>${escapeHtml(house.status)}</strong>
        <span>Candidate properties can change without losing the shared decision criteria.</span>
      </div>
    </div>

    <div class="metric-grid">
      ${house.metrics.map((item) => metric(item.label, item.value, "")).join("")}
    </div>

    <div class="detail-grid">
      <section class="panel">
        <div class="panel-header"><h2>Shared priorities</h2><span>Decision inputs</span></div>
        <div class="panel-body"><ul class="list">${house.priorities.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Scenarios</h2><span>Compare, don't predict</span></div>
        <div class="panel-body">${house.scenarios.map(scenarioRow).join("")}</div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Next steps</h2><span>Small and reversible</span></div>
        <div class="panel-body"><ul class="list">${house.next_steps.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Why this page matters</h2><span>Extension point</span></div>
        <div class="panel-body">
          <p class="task-description">A future financial-planning plugin can own assumptions and scenarios. A home-search plugin can own properties and visits. This page remains a consistent household view across both.</p>
        </div>
      </section>
    </div>
  `;
}

function renderYard() {
  const entries = landscapeEntries();
  if (!entries.length) {
    renderNoDemo("Yard planning", "Start mctrld with --plugin landscape to load the Yard workspace.");
    return;
  }
  const initiatives = entries.filter((entry) => entry.kind === "initiative");
  const actions = entries.filter((entry) => entry.kind === "action");
  const blocked = actions.filter((entry) => entry.state === "blocked").length;
  const seasonal = actions.filter((entry) => entry.timing?.kind === "window").length;
  const primary = initiatives[0];
  app.innerHTML = `
    <div class="section-intro">
      <div>
        <h2>${escapeHtml(primary?.title || "Seasonal work and long-term design")}</h2>
        <p>${escapeHtml(primary?.detail || "Landscape work contributed through the shared agenda contract.")}</p>
      </div>
      <div class="status-note">
        <strong>Landscape-owned state</strong>
        <span>Actions complete through Landscape's command handler and refresh from its durable projection.</span>
      </div>
    </div>

    <div class="metric-grid">
      ${metric("Initiatives", initiatives.length, "Plugin-owned outcomes")}
      ${metric("Open actions", actions.length, "Projected into the shared agenda")}
      ${metric("Blocked", blocked, "Waiting for prerequisite measurements")}
      ${metric("Seasonal windows", seasonal, "Time-bounded preparation")}
    </div>

    <section class="panel">
      <div class="panel-header"><h2>Mission Control action items</h2><span>Landscape provider</span></div>
      <div class="task-list">${actions.map(landscapeActionRow).join("")}</div>
    </section>
  `;
  wireCommandButtons();
}

function metric(label, value, detail) {
  return `<div class="metric"><span class="metric-label">${escapeHtml(label)}</span><strong class="metric-value">${escapeHtml(String(value))}</strong>${detail ? `<span class="metric-detail">${escapeHtml(detail)}</span>` : ""}</div>`;
}

function taskRow(task) {
  const done = task.state === "done";
  const nextState = done ? "ready" : "done";
  const badgeClass = task.blocked ? "is-blocked" : task.state === "in-progress" ? "is-active" : "";
  const detail = task.description || task.waiting_on || "No additional detail";
  return `
    <article class="task-row ${done ? "is-done" : ""}">
      <button class="task-toggle" type="button" data-plugin-id="core" data-entity-type="task" data-entity-id="${escapeHtml(task.id)}" data-revision="${escapeHtml(task.updated_at)}" data-command="set-state" data-next-state="${nextState}" aria-label="${done ? "Reopen" : "Complete"} ${escapeHtml(task.title)}">${done ? "✓" : ""}</button>
      <div>
        <h3 class="task-title">${escapeHtml(task.title)}</h3>
        <p class="task-description">${escapeHtml(detail)}</p>
      </div>
      <span class="state-badge ${badgeClass}">${escapeHtml(task.blocked ? "blocked" : task.state)}</span>
    </article>
  `;
}

function landscapeEntries() {
  return (dashboard.agenda || []).filter((entry) => entry.source?.plugin_id === "landscape");
}

function landscapeActionRow(entry) {
  const badgeClass = entry.state === "blocked" ? "is-blocked" : "";
  const detail = [entry.detail, timingLabel(entry.timing)].filter(Boolean).join(" · ");
  const complete = (entry.affordances || []).find(
    (affordance) => affordance.capability === "lifecycle.complete",
  );
  const control = complete && entry.revision
    ? `<button class="task-toggle" type="button" data-plugin-id="${escapeHtml(entry.source.plugin_id)}" data-entity-type="${escapeHtml(entry.source.entity_type)}" data-entity-id="${escapeHtml(entry.source.entity_id)}" data-revision="${escapeHtml(entry.revision)}" data-command="${escapeHtml(complete.command)}" data-capability="${escapeHtml(complete.capability)}" aria-label="Complete ${escapeHtml(entry.title)}"></button>`
    : '<span class="task-toggle is-read-only" aria-hidden="true">·</span>';
  return `
    <article class="task-row">
      ${control}
      <div>
        <h3 class="task-title">${escapeHtml(entry.title)}</h3>
        <p class="task-description">${escapeHtml(detail || "No additional detail")}</p>
      </div>
      <span class="state-badge ${badgeClass}">${escapeHtml(entry.state || entry.kind)}</span>
    </article>
  `;
}

function timingLabel(timing) {
  if (!timing || timing.kind === "anytime") return "Anytime";
  if (timing.kind === "due-on") return `Due ${timing.due_on}`;
  if (timing.kind === "due-at") return `Due ${timing.due_at}`;
  if (timing.kind === "window") return `${timing.starts_at.slice(0, 10)} to ${timing.ends_at.slice(0, 10)}`;
  return timing.kind;
}

function previewCard(kicker, title, text, view) {
  return `
    <section class="panel preview-card">
      <p class="kicker">${escapeHtml(kicker)}</p>
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(text)}</p>
      <button class="text-button" data-view="${view}" type="button">Open ${escapeHtml(kicker)} →</button>
    </section>
  `;
}

function livePlaceholder(title) {
  return `<section class="panel preview-card"><p class="kicker">Plugin surface</p><h2>${escapeHtml(title)}</h2><p>This live workspace has no demo fixture loaded.</p></section>`;
}

function scenarioRow(item) {
  const className = item.signal.toLowerCase();
  return `<article class="scenario"><div class="scenario-head"><h3>${escapeHtml(item.name)}</h3><span class="signal is-${escapeHtml(className)}">${escapeHtml(item.signal)}</span></div><p>${escapeHtml(item.detail)}</p></article>`;
}

function wireCommandButtons() {
  document.querySelectorAll("button.task-toggle[data-command]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const commandArguments = button.dataset.nextState
          ? { state: button.dataset.nextState }
          : {};
        await request("/api/commands", {
          method: "POST",
          body: JSON.stringify({
            schema_version: "mission-control.command/v1",
            command_id: `web-${Date.now()}-${++commandSequence}`,
            target: {
              plugin_id: button.dataset.pluginId,
              entity_type: button.dataset.entityType,
              entity_id: button.dataset.entityId,
            },
            expected_revision: button.dataset.revision,
            command: button.dataset.command,
            arguments: commandArguments,
          }),
        });
        await refresh();
      } catch (error) {
        renderError(error);
      }
    });
  });
}

async function addTask(event) {
  event.preventDefault();
  const input = document.querySelector("#quick-add-title");
  const title = input.value.trim();
  if (!title) return;
  try {
    await request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
    input.value = "";
    await refresh();
  } catch (error) {
    renderError(error);
  }
}

function renderNoDemo(title, detail) {
  app.innerHTML = `<div class="error-box"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div>`;
}

function renderError(error) {
  app.setAttribute("aria-busy", "false");
  app.innerHTML = `<div class="error-box"><strong>Mission Control could not complete that request.</strong><p>${escapeHtml(error.message || String(error))}</p></div>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

if (configuredMode === "demo") {
  modeLabel.textContent = "Synthetic demo workspace";
}
refresh();
