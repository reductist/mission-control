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
const inspectorContent = document.querySelector("#inspector-content");
const sourceHealthList = document.querySelector("#source-health-list");

const viewCopy = {
  overview: {
    eyebrow: "Household overview",
    title: "Overview",
    description: "Decisions, schedule, and active work.",
  },
  schedule: {
    eyebrow: "Household schedule",
    title: "Schedule",
    description: "Events, appointments, tasks, and reminders from enabled sources.",
  },
  house: {
    eyebrow: "House search",
    title: "House",
    description: "Sourced candidates, unknowns, costs, and review decisions.",
  },
  maintenance: {
    eyebrow: "Household maintenance",
    title: "Maintenance",
    description: "Cases, testing, references, and scheduled visits.",
  },
  yard: {
    eyebrow: "Landscape and yard",
    title: "Yard",
    description: "Seasonal maintenance and longer-term projects.",
  },
  history: {
    eyebrow: "Completed work",
    title: "History",
    description: "Completed work and owner-declared reopen actions.",
  },
};

let dashboard = null;
let homeSearchDetails = new Map();
let activeView = "overview";
let entityDetail = null;
let detailReturnView = "overview";
let commandSequence = 0;
let activityExpanded = false;
let scheduleFilter = "all";
let scheduleLayout = "agenda";
let calendarRangeMode = "three-day";
let refreshInFlight = false;

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
  entityDetail = null;
  activityExpanded = false;
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
    const error = new Error(document?.error?.detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.document = document;
    throw error;
  }
  return document;
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const focus = captureAppFocus();
    const detailTarget = entityDetail?.source;
    const nextDashboard = await request("/api/dashboard");
    const homeSearchLoad = await loadHomeSearchDetails(nextDashboard);
    let nextDetail = entityDetail;
    if (detailTarget) {
      nextDetail = await request(entityDetailPath(detailTarget));
    }
    dashboard = nextDashboard;
    homeSearchDetails = homeSearchLoad.details;
    entityDetail = nextDetail;
    connectionLabel.textContent = "Online";
    modeLabel.textContent = dashboard.mode === "demo" ? "House showcase enabled" : "Operational workspace";
    versionLabel.textContent = `v${dashboard.version}`;
    statusDot.classList.add("is-online");
    renderSourceHealth();
    app.setAttribute("aria-busy", "false");
    render();
    restoreAppFocus(focus);
    if (homeSearchLoad.failed) {
      showNotice("Some home-search details could not be refreshed. Last-known details remain visible.", "warning");
    }
  } catch (error) {
    connectionLabel.textContent = dashboard ? "Showing cached view" : "Unavailable";
    modeLabel.textContent = dashboard
      ? `Last loaded ${formatDateTime(dashboard.generated_at)}`
      : "Could not load workspace";
    if (dashboard) {
      showNotice("Could not refresh. The last loaded schedule remains visible.", "warning");
    } else {
      renderError(error);
    }
  } finally {
    refreshInFlight = false;
  }
}

function captureAppFocus() {
  const active = document.activeElement;
  if (!active || !app.contains(active)) return null;
  const candidates = [...app.querySelectorAll("button, input, textarea, select, a[href], [tabindex]")];
  return {
    index: candidates.indexOf(active),
    signature: focusSignature(active),
    value: "value" in active ? active.value : null,
    selectionStart: active.selectionStart,
    selectionEnd: active.selectionEnd,
  };
}

function restoreAppFocus(saved) {
  if (!saved) return;
  const candidates = [...app.querySelectorAll("button, input, textarea, select, a[href], [tabindex]")];
  const target = candidates.find((item) => focusSignature(item) === saved.signature)
    || candidates[saved.index];
  if (!target) return;
  if (saved.value !== null && "value" in target) target.value = saved.value;
  target.focus({ preventScroll: true });
  if (
    saved.selectionStart !== null
    && saved.selectionStart !== undefined
    && typeof target.setSelectionRange === "function"
  ) {
    target.setSelectionRange(saved.selectionStart, saved.selectionEnd);
  }
}

function focusSignature(element) {
  return [
    element.tagName,
    element.id,
    element.dataset?.view,
    element.dataset?.scheduleFilter,
    element.dataset?.scheduleLayout,
    element.dataset?.calendarRange,
    element.dataset?.pluginId,
    element.dataset?.entityType,
    element.dataset?.entityId,
    element.dataset?.command,
  ].join("|");
}

function render() {
  if (!dashboard) return;
  if (entityDetail) {
    renderEntityDetail();
  } else if (activeView === "schedule") {
    renderSchedule();
  } else if (activeView === "house") {
    renderHouse();
  } else if (activeView === "maintenance") {
    renderMaintenance();
  } else if (activeView === "yard") {
    renderYard();
  } else if (activeView === "history") {
    renderHistory();
  } else {
    renderOverview();
  }
  resetInspector();
}

function renderOverview() {
  const summary = dashboard.summary;
  const activeTasks = dashboard.tasks.filter((task) => task.state !== "done");
  const visibleTasks = activeTasks.slice(0, 7);
  const house = providerInitiative("home-search");
  const scheduled = scheduleEntries().filter((entry) => entry.timing?.kind !== "anytime");
  const maintenanceCases = householdEntries().filter((entry) => entry.kind === "initiative");
  const openMaintenanceCases = maintenanceCases.filter((entry) => !["done", "closed", "completed"].includes(entry.state));
  const yardEntries = landscapeEntries();
  const yardInitiative = yardEntries.find((entry) => entry.kind === "initiative");
  const yardActions = yardEntries.filter((entry) => entry.kind === "action");
  const visibleYardActions = yardActions.slice(0, 4);
  const visibleCoreTasks = visibleTasks.slice(0, Math.max(0, 7 - visibleYardActions.length));
  const visibleCount = visibleYardActions.length + visibleCoreTasks.length;
  const openWork = summary.open + yardActions.length + openMaintenanceCases.length;
  const blockedWork = summary.blocked
    + yardActions.filter((entry) => entry.state === "blocked").length
    + openMaintenanceCases.filter((entry) => entry.state === "blocked").length;

  const attention = [
    ...openMaintenanceCases.filter((entry) => entry.state === "blocked").map((entry) => ({ entry, area: "Maintenance" })),
    ...yardActions.filter((entry) => entry.state === "blocked").map((entry) => ({ entry, area: "Yard" })),
    ...activeTasks.filter((entry) => entry.blocked).map((entry) => ({ entry, area: "Core" })),
  ].slice(0, 4);
  const nextScheduled = scheduled.slice(0, 3);

  app.innerHTML = `
    ${attention.length ? `<div class="attention-strip" role="status"><span>${attention.length}</span><strong>Needs attention</strong><p>${escapeHtml(attention.map(({ entry }) => entry.title).join(" · "))}</p></div>` : ""}
    <div class="ops-summary" aria-label="Workspace summary">
      ${compactMetric("Open", openWork)}${compactMetric("Moving", summary.in_progress)}${compactMetric("Blocked", blockedWork)}${compactMetric("Done", summary.completed)}
    </div>
    <section class="panel queue-section">
      <div class="panel-header"><h2>Work queue</h2><span>${visibleCount} visible</span></div>
      <div class="task-list">${visibleCount ? `${visibleYardActions.map(landscapeActionRow).join("")}${visibleCoreTasks.map(taskRow).join("")}` : '<div class="empty">No active work. Add a shared task below.</div>'}</div>
      <form class="quick-add" id="quick-add-form"><input id="quick-add-title" name="title" required maxlength="160" placeholder="Add a shared task…" aria-label="New task title"><button class="primary-button" type="submit">Add</button></form>
    </section>
    <section class="overview-rooms" aria-label="Workspace rooms">
      ${overviewRoom("Schedule", nextScheduled.length ? `${nextScheduled.length} upcoming` : "Clear", nextScheduled.map((entry) => `${scheduleTimingLabel(entry)} — ${entry.title}`), "schedule")}
      ${overviewRoom("Maintenance", `${openMaintenanceCases.length} open`, openMaintenanceCases.slice(0, 2).map((entry) => entry.title), "maintenance")}
      ${overviewRoom("House", house ? "Search active" : "Not enabled", house ? [house.detail || house.title] : [], "house")}
      ${overviewRoom("Yard", `${yardActions.length} actions`, [yardInitiative?.title, ...yardActions.slice(0, 1).map((entry) => entry.title)].filter(Boolean), "yard")}
    </section>
  `;

  wireCommandButtons();
  wireEntityLinks();
  document.querySelector("#quick-add-form").addEventListener("submit", addTask);
  document.querySelectorAll(".text-button[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
}

function compactMetric(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function overviewRoom(label, status, lines, view) {
  return `<article class="room-row"><div><p class="kicker">${escapeHtml(label)}</p><strong>${escapeHtml(status)}</strong></div><ul>${lines.length ? lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("") : "<li>No current items</li>"}</ul><button class="text-button" data-view="${view}" type="button" aria-label="Open ${escapeHtml(label)}">Open →</button></article>`;
}

function renderSchedule() {
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";
  const entries = scheduleEntries()
    .filter(scheduleEntryMatchesFilter)
    .sort((left, right) => compareScheduleEntries(left, right, timeZone));
  const degraded = (dashboard.providers || []).filter((provider) =>
    ["degraded", "failed"].includes(provider.health?.state),
  );
  const starting = (dashboard.providers || []).filter((provider) =>
    provider.health?.state === "starting",
  );
  const lastSuccess = (dashboard.providers || [])
    .map((provider) => provider.health?.last_success_at)
    .filter(Boolean)
    .sort()
    .at(-1);

  app.innerHTML = `
    ${degraded.length ? `
      <div class="notice is-warning" role="status">
        ${escapeHtml(degraded.map((provider) => `${provider.name}: ${provider.health.detail}`).join(" "))}
      </div>
    ` : starting.length ? `
      <div class="notice" role="status">
        ${escapeHtml(starting.map((provider) => `${provider.name}: ${provider.health.detail}`).join(" "))}
      </div>
    ` : ""}
    <div class="schedule-toolbar panel">
      <div class="schedule-controls">
        <div class="schedule-layouts" role="group" aria-label="Schedule layout">
          ${scheduleLayoutButton("agenda", "Agenda")}
          ${scheduleLayoutButton("calendar", "Calendar")}
        </div>
        ${scheduleLayout === "calendar" ? `
          <div class="calendar-ranges" role="group" aria-label="Calendar range">
            ${calendarRangeButton("three-day", "3 days")}
            ${calendarRangeButton("weekdays", "Weekdays")}
            ${calendarRangeButton("week", "1 week")}
            ${calendarRangeButton("month", "1 month")}
          </div>
        ` : ""}
        <div class="schedule-filters" role="group" aria-label="Filter schedule">
          ${scheduleFilterButton("all", "All")}
          ${scheduleFilterButton("events", "Events")}
          ${scheduleFilterButton("tasks", "Tasks & reminders")}
        </div>
      </div>
      <div class="schedule-freshness">
        <span>Times shown in ${escapeHtml(timeZone)}</span>
        <span>${lastSuccess ? `Updated ${escapeHtml(formatDateTime(lastSuccess))}` : starting.length ? "Waiting for first refresh" : `Loaded ${escapeHtml(formatDateTime(dashboard.generated_at))}`}</span>
      </div>
    </div>
    ${scheduleLayout === "calendar"
      ? renderCalendarSchedule(entries, timeZone)
      : renderAgendaSchedule(entries, timeZone)}
  `;

  document.querySelectorAll("[data-schedule-layout]").forEach((button) => {
    button.addEventListener("click", () => {
      scheduleLayout = button.dataset.scheduleLayout;
      rerenderSchedulePreservingFocus();
    });
  });
  document.querySelectorAll("[data-calendar-range]").forEach((button) => {
    button.addEventListener("click", () => {
      calendarRangeMode = button.dataset.calendarRange;
      rerenderSchedulePreservingFocus();
    });
  });
  document.querySelectorAll("[data-schedule-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      scheduleFilter = button.dataset.scheduleFilter;
      rerenderSchedulePreservingFocus();
    });
  });
  wireEntityLinks();
}

function rerenderSchedulePreservingFocus() {
  const savedFocus = captureAppFocus();
  renderSchedule();
  restoreAppFocus(savedFocus);
}

function renderAgendaSchedule(entries, timeZone) {
  const groups = new Map();
  entries.forEach((entry) => {
    const key = scheduleDateKey(entry, timeZone);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  });
  return `
    <div class="schedule-days">
      ${groups.size
        ? [...groups].map(([key, items]) => scheduleDay(key, items)).join("")
        : '<section class="panel empty">Nothing scheduled in this range.</section>'}
    </div>
  `;
}

function renderCalendarSchedule(entries, timeZone) {
  const range = calendarRange(calendarRangeMode, localCivilDate(new Date()));
  const scheduled = entries.filter((entry) => entry.timing?.kind !== "anytime");
  const anytimeCount = entries.length - scheduled.length;
  return `
    <section class="panel calendar-heading">
      <div>
        <p class="kicker">${escapeHtml(calendarRangeLabel(calendarRangeMode))}</p>
        <h2>${escapeHtml(calendarPeriodLabel(range, calendarRangeMode))}</h2>
      </div>
      ${anytimeCount ? `<button class="text-button" data-schedule-layout="agenda" type="button">${anytimeCount} unscheduled ${anytimeCount === 1 ? "item" : "items"} in Agenda</button>` : ""}
    </section>
    <div class="calendar-scroll" tabindex="0" aria-label="${escapeHtml(calendarRangeLabel(calendarRangeMode))} calendar">
      <div class="calendar-grid is-${escapeHtml(calendarRangeMode)}">
        ${range.days.slice(0, range.columns).map(calendarWeekdayHeading).join("")}
        ${range.days.map((day) => calendarDayCell(day, scheduled, timeZone, range.month)).join("")}
      </div>
    </div>
  `;
}

function scheduleEntries() {
  return (dashboard.agenda || []).filter((entry) =>
    entry.kind === "event" || (entry.kind === "action" && entry.timing),
  );
}

function scheduleEntryMatchesFilter(entry) {
  return scheduleFilter === "all"
    || (scheduleFilter === "events" && entry.kind === "event")
    || (scheduleFilter === "tasks" && entry.kind === "action");
}

function scheduleLayoutButton(value, label) {
  const selected = scheduleLayout === value;
  return `<button class="schedule-choice ${selected ? "is-active" : ""}" data-schedule-layout="${value}" type="button" aria-pressed="${selected}">${escapeHtml(label)}</button>`;
}

function calendarRangeButton(value, label) {
  const selected = calendarRangeMode === value;
  return `<button class="schedule-filter ${selected ? "is-active" : ""}" data-calendar-range="${value}" type="button" aria-pressed="${selected}">${escapeHtml(label)}</button>`;
}

function scheduleFilterButton(value, label) {
  const selected = scheduleFilter === value;
  return `<button class="schedule-filter ${selected ? "is-active" : ""}" data-schedule-filter="${value}" type="button" aria-pressed="${selected}">${escapeHtml(label)}</button>`;
}

function attributionCatalog() {
  return dashboard?.attribution_catalog || { principals: [], accents: [] };
}

function entryProvenance(entry) {
  const catalog = attributionCatalog();
  const principalById = new Map(
    (catalog.principals || []).map((principal) => [principal.id, principal.label]),
  );
  const people = (entry.attribution?.principal_ids || [])
    .map((principalId) => principalById.get(principalId) || principalId);
  const integration = entry.attribution?.integration;
  const source = integration
    ? [integration.collection?.label, integration.connection?.label].filter(Boolean).join(" · ")
    : pluginLabel(entry.source?.plugin_id);
  return [people.join(" & "), source].filter(Boolean).join(" — ");
}

function entryAccentToken(entry) {
  const attribution = entry.attribution || {};
  const integration = attribution.integration;
  const pluginId = entry.source?.plugin_id;
  const accents = attributionCatalog().accents || [];
  const principalIds = new Set(attribution.principal_ids || []);
  const principalTokens = new Set(
    accents
      .filter((item) => item?.target?.kind === "principal"
        && principalIds.has(item.target.principal_id)
        && /^accent-[1-8]$/.test(item.token))
      .map((item) => item.token),
  );
  if (principalTokens.size === 1) return [...principalTokens][0];
  const candidates = [
    (target) => target.kind === "collection"
      && target.plugin_id === pluginId
      && target.connection_id === integration?.connection?.id
      && target.collection_id === integration?.collection?.id,
    (target) => target.kind === "connection"
      && target.plugin_id === pluginId
      && target.connection_id === integration?.connection?.id,
    (target) => target.kind === "plugin" && target.plugin_id === pluginId,
  ];
  for (const matches of candidates) {
    const preference = accents.find(
      (item) => item?.target && matches(item.target),
    );
    if (preference && /^accent-[1-8]$/.test(preference.token)) return preference.token;
  }
  return "";
}

function entryAccentAttribute(entry) {
  const token = entryAccentToken(entry);
  return token ? ` data-accent="${token}"` : "";
}

function calendarRange(mode, anchor) {
  if (mode === "three-day") {
    return { columns: 3, month: null, days: civilDateSequence(anchor, 3) };
  }
  if (mode === "weekdays") {
    const weekday = civilDateWeekday(anchor);
    const monday = shiftCivilDate(anchor, -(weekday === 0 ? 6 : weekday - 1));
    return { columns: 5, month: null, days: civilDateSequence(monday, 5) };
  }
  if (mode === "week") {
    const sunday = shiftCivilDate(anchor, -civilDateWeekday(anchor));
    return { columns: 7, month: null, days: civilDateSequence(sunday, 7) };
  }
  const monthStart = `${anchor.slice(0, 7)}-01`;
  const nextMonth = shiftCivilMonth(monthStart, 1);
  const lastDay = shiftCivilDate(nextMonth, -1);
  const gridStart = shiftCivilDate(monthStart, -civilDateWeekday(monthStart));
  const gridEnd = shiftCivilDate(lastDay, 6 - civilDateWeekday(lastDay));
  const length = Math.round((civilDateValue(gridEnd) - civilDateValue(gridStart)) / 86400000) + 1;
  return { columns: 7, month: anchor.slice(0, 7), days: civilDateSequence(gridStart, length) };
}

function civilDateSequence(start, length) {
  return Array.from({ length }, (_, index) => shiftCivilDate(start, index));
}

function shiftCivilDate(value, amount) {
  const shifted = new Date(civilDateValue(value));
  shifted.setUTCDate(shifted.getUTCDate() + amount);
  return shifted.toISOString().slice(0, 10);
}

function shiftCivilMonth(value, amount) {
  const [year, month] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1 + amount, 1)).toISOString().slice(0, 10);
}

function civilDateWeekday(value) {
  return new Date(civilDateValue(value)).getUTCDay();
}

function calendarRangeLabel(mode) {
  return {
    "three-day": "3-day view",
    weekdays: "Weekdays",
    week: "1-week view",
    month: "1-month view",
  }[mode];
}

function calendarPeriodLabel(range, mode) {
  if (mode === "month") {
    return formatCivilDate(`${range.month}-01`, { month: "long", year: "numeric" });
  }
  const first = range.days[0];
  const last = range.days.at(-1);
  const sameYear = first.slice(0, 4) === last.slice(0, 4);
  if (sameYear) {
    return `${formatCivilDate(first, { month: "short", day: "numeric" })}–${formatCivilDate(last, { month: "short", day: "numeric" })}, ${last.slice(0, 4)}`;
  }
  return `${formatCivilDate(first, { month: "short", day: "numeric", year: "numeric" })}–${formatCivilDate(last, { month: "short", day: "numeric", year: "numeric" })}`;
}

function formatCivilDate(value, options) {
  return new Intl.DateTimeFormat(undefined, { ...options, timeZone: "UTC" })
    .format(new Date(civilDateValue(value)));
}

function calendarWeekdayHeading(day) {
  return `<div class="calendar-weekday">${escapeHtml(formatCivilDate(day, { weekday: "short" }))}</div>`;
}

function calendarDayCell(day, entries, timeZone, month) {
  const matches = entries.filter((entry) => calendarEntryIntersectsDay(entry, day, timeZone));
  const classes = [
    "calendar-day",
    day === localCivilDate(new Date()) ? "is-today" : "",
    month && day.slice(0, 7) !== month ? "is-outside" : "",
  ].filter(Boolean).join(" ");
  return `
    <section class="${classes}" aria-label="${escapeHtml(formatCivilDate(day, { weekday: "long", month: "long", day: "numeric", year: "numeric" }))}">
      <div class="calendar-date"><span>${escapeHtml(formatCivilDate(day, { weekday: "short" }))}</span><strong>${Number(day.slice(-2))}</strong></div>
      <div class="calendar-items">
        ${matches.length ? matches.map((entry) => calendarEntryChip(entry, day, timeZone)).join("") : '<span class="calendar-empty">No items</span>'}
      </div>
    </section>
  `;
}

function calendarEntryIntersectsDay(entry, day, timeZone) {
  const timing = entry.timing || {};
  if (timing.kind === "all-day") {
    return timing.occurs_on <= day && day < (timing.ends_before || shiftCivilDate(timing.occurs_on, 1));
  }
  if (timing.kind === "due-on") return timing.due_on === day;
  if (timing.kind === "due-at") return dateKeyInTimeZone(timing.due_at, timeZone) === day;
  if (timing.kind === "timed" || timing.kind === "window") {
    const start = new Date(timing.starts_at).valueOf();
    const end = new Date(timing.ends_at).valueOf();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    const first = dateKeyInTimeZone(timing.starts_at, timeZone);
    const last = dateKeyInTimeZone(new Date(end - 1).toISOString(), timeZone);
    return first <= day && day <= last;
  }
  return false;
}

function calendarEntryChip(entry, day, timeZone) {
  const timing = entry.timing || {};
  let time = "";
  if (timing.kind === "timed") {
    time = dateKeyInTimeZone(timing.starts_at, timeZone) === day ? formatTime(timing.starts_at) : "Continues";
  } else if (timing.kind === "window") {
    time = dateKeyInTimeZone(timing.starts_at, timeZone) === day ? formatTime(timing.starts_at) : "Window";
  } else if (timing.kind === "due-at") {
    time = `Due ${formatTime(timing.due_at)}`;
  } else if (timing.kind === "due-on") {
    time = "Due";
  } else {
    time = "All day";
  }
  const kindClass = entry.kind === "event" ? "is-event" : "is-task";
  const content = `<span>${escapeHtml(time)}</span><strong>${escapeHtml(entry.title)}</strong><small>${escapeHtml(entryProvenance(entry))}</small>`;
  if (providerHasCapability(entry.source?.plugin_id, "entity-details")) {
    return `<button class="calendar-item ${kindClass}"${entryAccentAttribute(entry)} type="button" data-entity-link data-plugin-id="${escapeHtml(entry.source.plugin_id)}" data-entity-type="${escapeHtml(entry.source.entity_type)}" data-entity-id="${escapeHtml(entry.source.entity_id)}">${content}</button>`;
  }
  return `<div class="calendar-item ${kindClass}"${entryAccentAttribute(entry)}>${content}</div>`;
}

function scheduleDay(key, entries) {
  return `
    <section class="panel schedule-day" aria-labelledby="schedule-${escapeHtml(key)}">
      <div class="panel-header">
        <h2 id="schedule-${escapeHtml(key)}">${escapeHtml(scheduleDayLabel(key))}</h2>
        <span>${entries.length} ${entries.length === 1 ? "item" : "items"}</span>
      </div>
      <div class="schedule-list">${entries.map(scheduleRow).join("")}</div>
    </section>
  `;
}

function scheduleRow(entry) {
  const kindLabel = entry.kind === "event" ? "Event" : "Task";
  const provenance = [entryProvenance(entry), kindLabel]
    .filter(Boolean)
    .join(" · ");
  const timeValue = scheduleTimeValue(entry);
  return `
    <article class="schedule-row"${entryAccentAttribute(entry)}>
      <time class="schedule-time"${timeValue ? ` datetime="${escapeHtml(timeValue)}"` : ""}>${escapeHtml(scheduleTimingLabel(entry))}</time>
      <div>
        <h3 class="task-title">${entityTitle(entry)}</h3>
        ${entry.detail ? `<p class="task-description">${escapeHtml(entry.detail)}</p>` : ""}
        <p class="item-meta">${escapeHtml(provenance)}</p>
      </div>
      <span class="state-badge">${escapeHtml(kindLabel)}</span>
    </article>
  `;
}

function entityTitle(entry) {
  return providerHasCapability(entry.source?.plugin_id, "entity-details")
    ? entityLink(entry)
    : escapeHtml(entry.title);
}

function providerHasCapability(pluginId, capability) {
  return (dashboard.providers || []).some((provider) =>
    provider.id === pluginId && (provider.capabilities || []).includes(capability),
  );
}

function compareScheduleEntries(left, right, timeZone) {
  const leftDay = scheduleDateKey(left, timeZone);
  const rightDay = scheduleDateKey(right, timeZone);
  if (leftDay !== rightDay) {
    if (leftDay === "anytime") return 1;
    if (rightDay === "anytime") return -1;
    return leftDay.localeCompare(rightDay);
  }
  const leftRank = scheduleTimingRank(left);
  const rightRank = scheduleTimingRank(right);
  const leftValue = scheduleSortValue(left);
  const rightValue = scheduleSortValue(right);
  return leftRank - rightRank
    || leftValue - rightValue
    || left.kind.localeCompare(right.kind)
    || left.title.localeCompare(right.title)
    || left.id.localeCompare(right.id);
}

function scheduleTimingRank(entry) {
  const kind = entry.timing?.kind;
  if (kind === "all-day") return 0;
  if (["timed", "window", "due-at"].includes(kind)) return 1;
  if (kind === "due-on") return 2;
  return 3;
}

function scheduleSortValue(entry) {
  const timing = entry.timing || {};
  if (timing.kind === "all-day") return civilDateValue(timing.occurs_on);
  if (timing.kind === "due-on") return civilDateValue(timing.due_on) + 86399000;
  if (timing.kind === "timed" || timing.kind === "window") {
    return new Date(timing.starts_at).valueOf();
  }
  if (timing.kind === "due-at") return new Date(timing.due_at).valueOf();
  return Number.MAX_SAFE_INTEGER;
}

function scheduleDateKey(entry, timeZone) {
  const timing = entry.timing || {};
  if (timing.kind === "all-day") {
    const today = localCivilDate(new Date());
    if (timing.ends_before && timing.occurs_on < today && today < timing.ends_before) {
      return today;
    }
    return timing.occurs_on;
  }
  if (timing.kind === "due-on") return timing.due_on;
  if (timing.kind === "anytime") return "anytime";
  return dateKeyInTimeZone(
    timing.starts_at || timing.due_at,
    timeZone,
  );
}

function dateKeyInTimeZone(value, timeZone) {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function scheduleDayLabel(key) {
  if (key === "anytime") return "Anytime";
  const today = localCivilDate(new Date());
  const tomorrowDate = new Date();
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrow = localCivilDate(tomorrowDate);
  if (key === today) return "Today";
  if (key === tomorrow) return "Tomorrow";
  const [year, month, day] = key.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: year === new Date().getFullYear() ? undefined : "numeric",
  }).format(new Date(year, month - 1, day, 12));
}

function localCivilDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function civilDateValue(value) {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function scheduleTimeValue(entry) {
  const timing = entry.timing || {};
  return timing.starts_at || timing.due_at || timing.occurs_on || timing.due_on || "";
}

function scheduleTimingLabel(entry) {
  const timing = entry.timing || {};
  if (timing.kind === "all-day") {
    if (timing.ends_before && civilDateValue(timing.ends_before) > civilDateValue(timing.occurs_on) + 86400000) {
      const last = new Date(civilDateValue(timing.ends_before) - 86400000);
      return `All day through ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(last)}`;
    }
    return "All day";
  }
  if (timing.kind === "timed") {
    return `${formatTime(timing.starts_at)}–${formatTime(timing.ends_at)}`;
  }
  if (timing.kind === "due-on") return "Due";
  if (timing.kind === "due-at") return `Due ${formatTime(timing.due_at)}`;
  if (timing.kind === "window") return `${formatDateTime(timing.starts_at)}–${formatDateTime(timing.ends_at)}`;
  return "Anytime";
}

function formatTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(parsed);
}

function renderHistory() {
  const items = dashboard.closed_items || [];
  const reopenable = items.filter((item) => (item.affordances || []).some(
    (affordance) => affordance.capability === "lifecycle.reopen",
  )).length;
  const providers = new Set(items.map((item) => item.source?.plugin_id)).size;
  app.innerHTML = `
    <div class="metric-grid history-metrics">
      ${metric("Closed items", items.length, "Outside the active agenda")}
      ${metric("Reopenable", reopenable, "Declared by authoritative owners")}
      ${metric("Sources", providers, "Core and enabled plugins")}
    </div>

    <section class="panel">
      <div class="panel-header"><h2>Completed and closed</h2><span>Newest first</span></div>
      <div class="closed-list">
        ${items.length ? items.map(closedItemRow).join("") : '<div class="empty">No completed or closed items yet.</div>'}
      </div>
    </section>
  `;
  wireCommandButtons();
  wireEntityLinks();
}

function renderHouse() {
  const enabled = (dashboard.providers || []).some((provider) => provider.id === "home-search");
  const search = providerInitiative("home-search");
  if (!enabled || !search) {
    renderNoDemo(
      "Home search is not enabled",
      "Enable the home-search plugin to import sourced research. No listings are being watched or recommended by this empty workspace.",
    );
    return;
  }
  const searchDetail = homeSearchDetail(search);
  const candidates = homeSearchCandidates();
  const verified = candidates.filter(
    (entry) => detailValue(homeSearchDetail(entry), "verification") === "verified",
  );
  const shortlisted = candidates.filter(
    (entry) => detailValue(homeSearchDetail(entry), "review-status") === "shortlisted",
  );
  const freshness = detailValue(
    searchDetail,
    "freshness",
    "No verified search snapshot imported yet",
  );
  app.innerHTML = `
    <section class="panel house-search-status">
      <div class="panel-header">
        <h2>${entityLink(search)}</h2>
        <span>Budget unset · watcher inactive</span>
      </div>
      <div class="panel-body">
        <p class="task-description">${escapeHtml(search.detail)}</p>
        <p class="item-meta">Daily checks are approved after mortgage reconciliation; alert only for worthwhile matches. This interface does not run a feed.</p>
      </div>
    </section>

    <div class="metric-grid">
      ${metric("Current candidates", candidates.length, "Imported from sourced research")}
      ${metric("Source-verified", verified.length, "Still requires independent diligence")}
      ${metric("Shortlisted", shortlisted.length, "Explicit review decisions")}
      ${metric("Last checked", freshness, "Source-reported time, not page refresh time")}
    </div>

    <section class="panel house-criteria">
      <div class="panel-header"><h2>Search criteria</h2><span>Renderer-neutral decision record</span></div>
      <dl class="house-criteria-grid">
        ${(searchDetail?.attributes || [])
          .filter((attribute) => !["freshness", "candidate-counts"].includes(attribute.key))
          .map(detailAttribute)
          .join("")}
      </dl>
    </section>

    <section class="panel house-candidates">
      <div class="panel-header"><h2>Discovered purchase targets</h2><span>${candidates.length} current</span></div>
      <div class="candidate-list">
        ${candidates.length ? candidates.map(homeCandidateCard).join("") : homeSearchEmptyState(freshness)}
      </div>
    </section>

    <details class="panel import-disclosure">
      <summary class="activity-disclosure-summary">
        <span class="activity-disclosure-title">Import research snapshot</span>
        <span class="activity-disclosure-meta">Validated, revision-checked, full replacement</span>
        <span class="activity-disclosure-icon" aria-hidden="true"></span>
      </summary>
      <form class="snapshot-form" id="home-search-import-form">
        <label for="home-search-snapshot">Paste a <code>mission-control.home-search-snapshot/v1</code> JSON document</label>
        <textarea id="home-search-snapshot" rows="10" required spellcheck="false" placeholder='{"schema_version":"mission-control.home-search-snapshot/v1", …}'></textarea>
        <p class="item-meta">Imports must use actual checked time and source URLs. Invalid imports leave the last good snapshot unchanged. Review decisions survive later snapshots with the same candidate IDs.</p>
        <button class="primary-button" type="submit">Validate and import</button>
      </form>
    </details>
  `;
  wireEntityLinks();
  wireHomeSearchReviewButtons();
  document.querySelector("#home-search-import-form").addEventListener(
    "submit",
    (event) => importHomeSearchSnapshot(event, search),
  );
}

function homeSearchEmptyState(freshness) {
  const imported = freshness !== "No verified search snapshot imported yet";
  return `<div class="empty">${escapeHtml(imported
    ? `The imported snapshot was checked ${freshness} and included no worthwhile candidates. This does not imply an active or exhaustive listing feed.`
    : "No verified research snapshot has been imported. Budget is still unset pending mortgage reconciliation, and the daily watcher is not active.")}</div>`;
}

function homeCandidateCard(entry) {
  const detail = homeSearchDetail(entry);
  const review = detailValue(detail, "review-status", "unreviewed");
  const sourceUrl = safeHttpUrl(detailValue(detail, "source-url", ""));
  const fields = [
    ["Why it fits", detailValue(detail, "why-fit")],
    ["Tradeoffs", detailValue(detail, "tradeoffs")],
    ["Unknowns", detailValue(detail, "unknowns")],
    ["Estimated all-in", detailValue(detail, "estimated-all-in")],
    ["Estimate confidence", detailValue(detail, "cost-confidence")],
    ["Assumptions", detailValue(detail, "cost-assumptions")],
  ];
  return `
    <article class="candidate-card">
      <div class="candidate-head">
        <div>
          <p class="kicker">${escapeHtml(detailValue(detail, "verification"))} · ${escapeHtml(detailValue(detail, "listing-status"))}</p>
          <h3>${entityLink(entry)}</h3>
          <p class="item-meta">${escapeHtml(detailValue(detail, "usable-indoor-space"))} · ${escapeHtml(detailValue(detail, "list-price"))} · checked ${escapeHtml(detailValue(detail, "last-checked"))}</p>
        </div>
        <span class="state-badge">${escapeHtml(review)}</span>
      </div>
      <dl class="candidate-facts">
        ${fields.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
      </dl>
      <div class="candidate-actions">
        ${sourceUrl ? `<a class="text-button" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">Open source ↗</a>` : '<span class="read-only-label">No safe source URL</span>'}
        <div class="review-controls" aria-label="Review decision">
          ${reviewButton(entry, "shortlisted", "Shortlist", review)}
          ${reviewButton(entry, "rejected", "Reject", review)}
          ${reviewButton(entry, "unreviewed", "Reset", review)}
        </div>
      </div>
    </article>
  `;
}

function reviewButton(entry, status, label, current) {
  return `<button class="secondary-button" type="button" data-home-review data-plugin-id="home-search" data-entity-type="candidate" data-entity-id="${escapeHtml(entry.source.entity_id)}" data-revision="${escapeHtml(entry.revision)}" data-review-status="${status}"${status === current ? " disabled" : ""}>${label}</button>`;
}

function safeHttpUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch (_error) {
    return null;
  }
}

function renderMaintenance() {
  const entries = householdEntries();
  if (!entries.length) {
    renderNoDemo("Household maintenance", "Enable the household plugin and configure a maintenance case to use this workspace.");
    return;
  }
  const cases = entries.filter((entry) => entry.kind === "initiative");
  const appointments = entries.filter((entry) => entry.kind === "event");
  const openCases = cases.filter((entry) => !["done", "closed", "completed"].includes(entry.state));
  const blockedCases = openCases.filter((entry) => entry.state === "blocked");
  app.innerHTML = `
    <div class="section-intro">
      <div>
        <h2>Maintenance records that keep their context</h2>
        <p>Open a case to record tests and decisions, find contractor details and reference links, or review related task IDs.</p>
      </div>
      <div class="status-note">
        <strong>Household-owned records</strong>
        <span>Cases and visits come from the household plugin. Notes are saved in Mission Control and remain available after restarts.</span>
      </div>
    </div>

    <div class="metric-grid history-metrics">
      ${metric("Open cases", openCases.length, "Problems still being tracked")}
      ${metric("Blocked", blockedCases.length, "Waiting for a decision or dependency")}
      ${metric("Scheduled visits", appointments.length, "Also shown in Schedule")}
    </div>

    <div class="detail-grid">
      <section class="panel">
        <div class="panel-header"><h2>Maintenance cases</h2><span>${cases.length} ${cases.length === 1 ? "case" : "cases"}</span></div>
        <div class="task-list">
          ${cases.length ? cases.map(householdCaseRow).join("") : '<div class="empty">No maintenance cases configured.</div>'}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><h2>Visits and appointments</h2><span>Household provider</span></div>
        <div class="schedule-list">
          ${appointments.length ? appointments.map(scheduleRow).join("") : '<div class="empty">No visits scheduled.</div>'}
        </div>
      </section>
    </div>
  `;
  wireEntityLinks();
}

function renderYard() {
  const entries = landscapeEntries();
  if (!entries.length) {
    renderNoDemo("Yard planning", "Enable the landscape plugin in Mission Control configuration to load the Yard workspace.");
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
        <h2>${primary ? entityLink(primary) : "Seasonal work and long-term design"}</h2>
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
  wireEntityLinks();
}

function renderEntityDetail() {
  const detail = entityDetail;
  const annotate = (detail.affordances || []).find(
    (affordance) => affordance.capability === "entity.annotate",
  );
  const lifecycle = (detail.affordances || []).find(
    (affordance) => ["lifecycle.complete", "lifecycle.reopen"].includes(affordance.capability),
  );
  const lifecycleLabel = lifecycle?.capability === "lifecycle.reopen" ? "Reopen" : "Complete";
  const allActivity = [...(detail.activity || [])].reverse();
  const activeNotes = allActivity.filter(
    (entry) => entry.kind === "note" && entry.state === "active",
  );
  const removedNotes = allActivity.filter(
    (entry) => entry.kind === "note" && entry.state === "inactive",
  );
  pageEyebrow.textContent = `${pluginLabel(detail.source.plugin_id)} · ${detail.source.entity_type}`;
  pageTitle.textContent = detail.title;
  pageDescription.textContent = detail.description || "Entity details, notes, and history.";

  app.innerHTML = `
    <button class="back-button" id="entity-detail-back" type="button">← Back to ${escapeHtml(viewCopy[detailReturnView].title)}</button>
    <div class="entity-layout">
      <section class="panel entity-summary">
        <div class="panel-header">
          <h2>Details</h2>
          ${detail.state ? `<span>${escapeHtml(detail.state)}</span>` : ""}
        </div>
        <div class="panel-body">
          ${detail.description ? `<p class="entity-description">${escapeHtml(detail.description)}</p>` : '<p class="task-description">No additional description.</p>'}
          ${detail.attributes?.length ? `<dl class="attribute-list">${detail.attributes.map(detailAttribute).join("")}</dl>` : ""}
          ${lifecycle && detail.revision ? `<button class="secondary-button entity-action" type="button" data-plugin-id="${escapeHtml(detail.source.plugin_id)}" data-entity-type="${escapeHtml(detail.source.entity_type)}" data-entity-id="${escapeHtml(detail.source.entity_id)}" data-revision="${escapeHtml(detail.revision)}" data-command="${escapeHtml(lifecycle.command)}" data-capability="${escapeHtml(lifecycle.capability)}">${lifecycleLabel}</button>` : ""}
        </div>
      </section>

      <div class="stack">
        <section class="panel">
          <div class="panel-header">
            <h2 id="notes-heading" tabindex="-1">Notes</h2>
            <span>${activeNotes.length} active</span>
          </div>
          <div class="note-list">
            ${activeNotes.length ? activeNotes.map(noteRow).join("") : '<div class="empty">No active notes.</div>'}
          </div>
          ${annotate && detail.revision ? `
            <form class="note-form" id="entity-note-form">
              <label class="note-form-label" for="entity-note-body">Add a note</label>
              <textarea id="entity-note-body" name="body" required maxlength="16384" rows="5" placeholder="Record measurements, observations, decisions, or other context…"></textarea>
              <button class="primary-button" type="submit">Save note</button>
            </form>
          ` : ""}
        </section>
        <details class="panel activity-disclosure"${activityExpanded ? " open" : ""}>
          <summary class="activity-disclosure-summary">
            <span class="activity-disclosure-title">Activity</span>
            <span class="activity-disclosure-meta">${allActivity.length} ${allActivity.length === 1 ? "entry" : "entries"}${removedNotes.length ? ` · ${removedNotes.length} removed note${removedNotes.length === 1 ? "" : "s"}` : " · Full audit trail"}</span>
            <span class="activity-disclosure-icon" aria-hidden="true"></span>
          </summary>
          <div class="activity-list">
            ${allActivity.length ? allActivity.map(activityRow).join("") : '<div class="empty">No activity has been recorded.</div>'}
          </div>
        </details>
      </div>
    </div>
  `;

  document.querySelector("#entity-detail-back").addEventListener("click", () => showView(detailReturnView));
  wireCommandButtons();
  const noteForm = document.querySelector("#entity-note-form");
  if (noteForm) {
    noteForm.addEventListener("submit", (event) => addEntityNote(event, annotate));
  }
  const activityDisclosure = document.querySelector(".activity-disclosure");
  activityDisclosure.addEventListener("toggle", () => {
    activityExpanded = activityDisclosure.open;
  });
  wireActivityCommands();
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

function householdEntries() {
  return (dashboard.agenda || []).filter((entry) => entry.source?.plugin_id === "household");
}

function householdCaseRow(entry) {
  const badgeClass = entry.state === "blocked" ? "is-blocked" : entry.state === "in-progress" ? "is-active" : "";
  return `
    <article class="task-row">
      <span class="task-toggle is-read-only" aria-hidden="true">·</span>
      <div>
        <h3 class="task-title">${entityLink(entry)}</h3>
        <p class="task-description">${escapeHtml(entry.detail || "Open the case for contacts, links, related tasks, and notes.")}</p>
      </div>
      <span class="state-badge ${badgeClass}">${escapeHtml(entry.state || "open")}</span>
    </article>
  `;
}

function providerEntries(pluginId, source = dashboard) {
  return (source?.agenda || []).filter((entry) => entry.source?.plugin_id === pluginId);
}

function providerInitiative(pluginId, source = dashboard) {
  return providerEntries(pluginId, source).find((entry) => entry.kind === "initiative");
}

function homeSearchCandidates(source = dashboard) {
  return providerEntries("home-search", source).filter(
    (entry) => entry.source?.entity_type === "candidate",
  );
}

async function loadHomeSearchDetails(source) {
  const entries = providerEntries("home-search", source);
  const activeKeys = new Set(entries.map(
    (entry) => `${entry.source.entity_type}:${entry.source.entity_id}`,
  ));
  const details = new Map(
    [...homeSearchDetails].filter(([key]) => activeKeys.has(key)),
  );
  const results = await Promise.allSettled(entries.map(async (entry) => [
    `${entry.source.entity_type}:${entry.source.entity_id}`,
    await request(entityDetailPath(entry.source)),
  ]));
  results.forEach((result) => {
    if (result.status === "fulfilled") details.set(...result.value);
  });
  return {
    details,
    failed: results.some((result) => result.status === "rejected"),
  };
}

function homeSearchDetail(entry) {
  return homeSearchDetails.get(`${entry.source.entity_type}:${entry.source.entity_id}`);
}

function detailValue(detail, key, fallback = "Not recorded") {
  return detail?.attributes?.find((attribute) => attribute.key === key)?.value || fallback;
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
        <h3 class="task-title">${entityLink(entry)}</h3>
        <p class="task-description">${escapeHtml(detail || "No additional detail")}</p>
      </div>
      <span class="state-badge ${badgeClass}">${escapeHtml(entry.state || entry.kind)}</span>
    </article>
  `;
}

function closedItemRow(item) {
  const reopen = (item.affordances || []).find(
    (affordance) => affordance.capability === "lifecycle.reopen",
  );
  const coreNextState = item.source?.plugin_id === "core" ? ' data-next-state="ready"' : "";
  const control = reopen && item.revision
    ? `<button class="secondary-button" type="button" data-plugin-id="${escapeHtml(item.source.plugin_id)}" data-entity-type="${escapeHtml(item.source.entity_type)}" data-entity-id="${escapeHtml(item.source.entity_id)}" data-revision="${escapeHtml(item.revision)}" data-command="${escapeHtml(reopen.command)}" data-capability="${escapeHtml(reopen.capability)}"${coreNextState}>Reopen</button>`
    : '<span class="read-only-label">Read only</span>';
  const provenance = [pluginLabel(item.source?.plugin_id), `Closed ${formatDateTime(item.closed_at)}`]
    .filter(Boolean)
    .join(" · ");
  return `
    <article class="closed-row">
      <div>
        <div class="closed-title-line">
          <h3 class="task-title">${providerHasCapability(item.source?.plugin_id, "entity-details") ? entityLink(item) : escapeHtml(item.title)}</h3>
          <span class="state-badge">${escapeHtml(item.state)}</span>
        </div>
        <p class="task-description">${escapeHtml(item.detail || "No additional detail")}</p>
        <p class="item-meta">${escapeHtml(provenance)}</p>
      </div>
      ${control}
    </article>
  `;
}

function entityLink(item) {
  return `<button class="entity-link" type="button" data-entity-link data-plugin-id="${escapeHtml(item.source.plugin_id)}" data-entity-type="${escapeHtml(item.source.entity_type)}" data-entity-id="${escapeHtml(item.source.entity_id)}">${escapeHtml(item.title)}</button>`;
}

function detailAttribute(attribute) {
  const sourceUrls = attribute.key === "source-urls"
    ? attribute.value.split(" • ").map(safeHttpUrl).filter(Boolean)
    : [];
  if (sourceUrls.length) {
    const links = sourceUrls
      .map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(url)} ↗</a>`)
      .join("<br>");
    return `<div><dt>${escapeHtml(attribute.label)}</dt><dd>${links}</dd></div>`;
  }
  const href = attribute.key === "source-url"
    ? safeHttpUrl(attribute.value) || ""
    : safeDetailHref(attribute.value);
  const display = href.startsWith("mailto:") || href.startsWith("tel:")
    ? attribute.value.slice(attribute.value.indexOf(":") + 1)
    : attribute.value;
  const value = href
    ? `<a href="${escapeHtml(href)}"${/^https?:\/\//i.test(href) ? ' target="_blank" rel="noreferrer"' : ""}>${escapeHtml(display)}${attribute.key === "source-url" ? " ↗" : ""}</a>`
    : escapeHtml(display);
  return `<div><dt>${escapeHtml(attribute.label)}</dt><dd>${value}</dd></div>`;
}

function safeDetailHref(value) {
  return /^(https?:\/\/|mailto:|tel:)/i.test(value) ? value : "";
}

function noteRow(entry) {
  const provenance = [noteActor(entry), formatDateTime(entry.occurred_at)].filter(Boolean).join(" · ");
  const action = noteLifecycleAction(entry, ["lifecycle.dismiss"]);
  return `
    <article class="note-row">
      <div>
        <p class="note-body">${escapeHtml(entry.body)}</p>
        <p class="item-meta">${escapeHtml(provenance)}</p>
      </div>
      ${action}
    </article>
  `;
}

function activityRow(entry) {
  const note = entry.kind === "note";
  const noteActivity = entry.activity_type?.startsWith("core.note-");
  const provenance = note || noteActivity
    ? noteProvenance(entry)
    : [pluginLabel(entityDetail.source.plugin_id), formatDateTime(entry.occurred_at)].join(" · ");
  const action = note ? noteLifecycleAction(entry, ["lifecycle.reopen"]) : "";
  return `
    <article class="activity-row ${note ? "is-note" : ""} ${entry.state === "inactive" ? "is-inactive" : ""}">
      <div class="activity-marker" aria-hidden="true"></div>
      <div>
        <p class="activity-summary">${escapeHtml(entry.summary)}</p>
        ${entry.body ? `<p class="activity-body">${escapeHtml(entry.body)}</p>` : ""}
        <p class="item-meta">${escapeHtml(provenance)}</p>
      </div>
      ${action}
    </article>
  `;
}

function noteProvenance(entry) {
  return [
    "Note",
    noteActor(entry),
    formatDateTime(entry.occurred_at),
  ].filter(Boolean).join(" · ");
}

function noteActor(entry) {
  if (!entry.actor) return null;
  return entry.actor === "local-operator" ? "You" : entry.actor;
}

function noteLifecycleAction(entry, capabilities) {
  const affordance = entry.affordances?.find((item) => capabilities.includes(item.capability));
  const actionLabel = affordance?.capability === "lifecycle.dismiss"
    ? "Remove"
    : affordance?.capability === "lifecycle.reopen" ? "Restore" : null;
  return affordance && entry.source && entry.revision
    ? `<button class="activity-action ${entry.state === "active" ? "is-destructive" : ""}" type="button" data-activity-command data-plugin-id="${escapeHtml(entry.source.plugin_id)}" data-entity-type="${escapeHtml(entry.source.entity_type)}" data-entity-id="${escapeHtml(entry.source.entity_id)}" data-revision="${escapeHtml(entry.revision)}" data-command="${escapeHtml(affordance.command)}" data-capability="${escapeHtml(affordance.capability)}" aria-label="${actionLabel} note from ${escapeHtml(formatDateTime(entry.occurred_at))}">${actionLabel}</button>`
    : "";
}

function pluginLabel(pluginId) {
  if (pluginId === "core") return "Core";
  const provider = (dashboard?.providers || []).find((item) => item.id === pluginId);
  if (provider) return provider.name;
  return pluginId || "Unknown source";
}

function formatDateTime(value) {
  if (!value) return "at an unknown time";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function timingLabel(timing) {
  if (!timing || timing.kind === "anytime") return "Anytime";
  if (timing.kind === "due-on") return `Due ${timing.due_on}`;
  if (timing.kind === "due-at") return `Due ${formatDateTime(timing.due_at)}`;
  if (timing.kind === "window") return `${timing.starts_at.slice(0, 10)} to ${timing.ends_at.slice(0, 10)}`;
  if (timing.kind === "all-day") return scheduleTimingLabel({ timing });
  if (timing.kind === "timed") return `${formatDateTime(timing.starts_at)} to ${formatDateTime(timing.ends_at)}`;
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

async function importHomeSearchSnapshot(event, search) {
  event.preventDefault();
  const textarea = document.querySelector("#home-search-snapshot");
  const submit = event.currentTarget.querySelector("button[type='submit']");
  let snapshot;
  try {
    snapshot = JSON.parse(textarea.value);
  } catch (_error) {
    showNotice("The snapshot is not valid JSON. Nothing was imported.", "warning");
    return;
  }
  submit.disabled = true;
  try {
    await request("/api/commands", {
      method: "POST",
      body: JSON.stringify({
        schema_version: "mission-control.command/v1",
        command_id: `web-home-import-${Date.now()}-${++commandSequence}`,
        target: search.source,
        expected_revision: search.revision,
        command: "import-snapshot",
        arguments: { snapshot },
      }),
    });
    textarea.value = "";
    await refresh();
    showNotice("The sourced home-search snapshot was imported.");
  } catch (error) {
    if (error.status === 409) {
      await refresh();
      showNotice("Home-search data changed while importing. The view was refreshed; review it before retrying.", "warning");
    } else {
      showNotice(error.message || String(error), "warning");
    }
  } finally {
    if (document.body.contains(submit)) submit.disabled = false;
  }
}

function wireHomeSearchReviewButtons() {
  document.querySelectorAll("button[data-home-review]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await request("/api/commands", {
          method: "POST",
          body: JSON.stringify({
            schema_version: "mission-control.command/v1",
            command_id: `web-home-review-${Date.now()}-${++commandSequence}`,
            target: {
              plugin_id: button.dataset.pluginId,
              entity_type: button.dataset.entityType,
              entity_id: button.dataset.entityId,
            },
            expected_revision: button.dataset.revision,
            command: "set-review-status",
            arguments: { status: button.dataset.reviewStatus },
          }),
        });
        await refresh();
        showNotice("The candidate review decision was saved.");
      } catch (error) {
        if (error.status === 409) {
          await refresh();
          showNotice("That candidate changed after this view loaded. Review the refreshed details before retrying.", "warning");
        } else {
          showNotice(error.message || String(error), "warning");
        }
      } finally {
        if (document.body.contains(button)) button.disabled = false;
      }
    });
  });
}

function wireCommandButtons() {
  document.querySelectorAll("button[data-command]:not([data-activity-command])").forEach((button) => {
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
        showNotice("The item was updated from its authoritative owner.");
      } catch (error) {
        if (error.status === 409) {
          await refresh();
          showNotice("That item changed after this view loaded. The view has been refreshed; review the current state before retrying.", "warning");
        } else {
          renderError(error);
        }
      }
    });
  });
}

function wireEntityLinks() {
  document.querySelectorAll("[data-entity-link]").forEach((button) => {
    button.addEventListener("click", () => openEntityDetail({
      plugin_id: button.dataset.pluginId,
      entity_type: button.dataset.entityType,
      entity_id: button.dataset.entityId,
    }));
  });
}

function entityDetailPath(source) {
  return `/api/entities/${encodeURIComponent(source.plugin_id)}/${encodeURIComponent(source.entity_type)}/${encodeURIComponent(source.entity_id)}`;
}

async function openEntityDetail(source) {
  detailReturnView = activeView;
  activityExpanded = false;
  app.setAttribute("aria-busy", "true");
  try {
    entityDetail = await request(entityDetailPath(source));
    app.setAttribute("aria-busy", "false");
    render();
  } catch (error) {
    renderError(error);
  }
}

function wireActivityCommands() {
  document.querySelectorAll("button[data-activity-command]").forEach((button) => {
    button.addEventListener("click", async () => {
      const removing = button.dataset.capability === "lifecycle.dismiss";
      if (removing && !window.confirm(
        "Remove this note? You can restore it from Activity.",
      )) return;
      button.disabled = true;
      try {
        await request("/api/commands", {
          method: "POST",
          body: JSON.stringify({
            schema_version: "mission-control.command/v1",
            command_id: `web-note-lifecycle-${Date.now()}-${++commandSequence}`,
            target: {
              plugin_id: button.dataset.pluginId,
              entity_type: button.dataset.entityType,
              entity_id: button.dataset.entityId,
            },
            expected_revision: button.dataset.revision,
            command: button.dataset.command,
            arguments: {},
          }),
        });
        await refresh();
        showNotice(
          removing
            ? "Note removed. You can restore it from Activity."
            : "Note restored to Notes.",
        );
        document.querySelector("#notes-heading")?.focus({ preventScroll: true });
      } catch (error) {
        if (error.status === 409) {
          await refresh();
          showNotice("That note changed after this view loaded. The details were refreshed; review its current state before retrying.", "warning");
        } else {
          showNotice(error.message || String(error), "warning");
        }
      } finally {
        if (document.body.contains(button)) button.disabled = false;
      }
    });
  });
}

async function addEntityNote(event, affordance) {
  event.preventDefault();
  const input = document.querySelector("#entity-note-body");
  const body = input.value.trim();
  if (!body) return;
  const submit = event.currentTarget.querySelector("button[type='submit']");
  submit.disabled = true;
  try {
    await request("/api/commands", {
      method: "POST",
      body: JSON.stringify({
        schema_version: "mission-control.command/v1",
        command_id: `web-note-${Date.now()}-${++commandSequence}`,
        target: entityDetail.source,
        expected_revision: entityDetail.revision,
        command: affordance.command,
        arguments: { body },
      }),
    });
    await refresh();
    showNotice("Note added.");
  } catch (error) {
    if (error.status === 409) {
      await refresh();
      showNotice("This entity changed while you were writing. The details were refreshed; review them before retrying.", "warning");
    } else {
      renderError(error);
    }
  } finally {
    if (document.body.contains(submit)) submit.disabled = false;
  }
}

function showNotice(message, tone = "success") {
  const existing = document.querySelector(".notice");
  if (existing) existing.remove();
  app.insertAdjacentHTML(
    "afterbegin",
    `<div class="notice is-${escapeHtml(tone)}" role="status">${escapeHtml(message)}</div>`,
  );
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
  app.innerHTML = `<div class="error-box"><strong>Mission Control could not complete that request.</strong><p>${escapeHtml(error.message || String(error))}</p><button class="secondary-button" id="retry-load" type="button">Retry</button></div>`;
  document.querySelector("#retry-load").addEventListener("click", refresh);
}

function renderSourceHealth() {
  if (!sourceHealthList) return;
  const providers = dashboard?.providers || [];
  sourceHealthList.innerHTML = providers.length
    ? providers.map((provider) => {
      const state = provider.health?.state || "unknown";
      return `<div class="source-row"><i class="health-dot is-${escapeHtml(state)}" aria-hidden="true"></i><span>${escapeHtml(provider.name)}</span><small>${escapeHtml(state)}</small></div>`;
    }).join("")
    : '<p class="muted-copy">No plugin sources enabled.</p>';
}

let inspectorActions = [];

function resetInspector() {
  if (!inspectorContent) return;
  inspectorActions = [];
  inspectorContent.innerHTML = `
    <div class="inspector-empty">
      <span class="inspector-glyph" aria-hidden="true">⌁</span>
      <h2>${escapeHtml(viewCopy[activeView]?.title || "Nothing selected")}</h2>
      <p>Move through the queue to inspect context and available commands.</p>
    </div>`;
}

function inspectElement(element) {
  if (!inspectorContent || !element) return;
  const context = element.closest("article, .task-row, .schedule-row, .candidate-card, .panel, .attention-strip") || element;
  document.querySelectorAll(".is-inspected").forEach((item) => item.classList.remove("is-inspected"));
  context.classList.add("is-inspected");
  const title = context.querySelector("h2, h3, .task-title, strong")?.textContent?.trim()
    || element.getAttribute("aria-label") || element.textContent.trim() || "Selected item";
  const detail = context.querySelector(".task-description, .entity-description, .activity-body, p")?.textContent?.trim();
  const state = context.querySelector(".state-badge, .signal")?.textContent?.trim();
  const sourceId = element.dataset.pluginId
    || context.querySelector("[data-plugin-id]")?.dataset.pluginId;
  const actionNodes = [...context.querySelectorAll("button:not([disabled]), a[href]")]
    .filter((node) => !node.closest("#inspector-content"));
  inspectorActions = actionNodes;
  inspectorContent.innerHTML = `
    <section class="inspector-detail">
      <p class="kicker">${escapeHtml(sourceId ? pluginLabel(sourceId) : viewCopy[activeView]?.eyebrow || "Workspace")}</p>
      <h2>${escapeHtml(title)}</h2>
      <div class="inspector-badges">${state ? `<span class="state-badge">${escapeHtml(state)}</span>` : ""}${sourceId ? `<span class="state-badge">${escapeHtml(sourceId)}</span>` : ""}</div>
      <p class="inspector-description">${escapeHtml(detail || "No additional detail is available for this item.")}</p>
      <div class="inspector-section">
        <h3>Commands</h3>
        ${actionNodes.length ? `<div class="command-table">${actionNodes.map((node, index) => `<button type="button" data-inspector-action="${index}"><span>${escapeHtml(inspectorActionLabel(node))}</span><kbd>↵</kbd></button>`).join("")}</div>` : '<p class="muted-copy">This source exposes no command for the selected item.</p>'}
      </div>
      <div class="inspector-section"><h3>Provenance</h3><p class="muted-copy">${escapeHtml(sourceId ? `Owned by ${pluginLabel(sourceId)}. Commands return to the authoritative source.` : "Rendered from the current Mission Control projection.")}</p></div>
    </section>`;
}

function inspectorActionLabel(node) {
  return node.getAttribute("aria-label") || node.textContent.trim() || "Open";
}

inspectorContent?.addEventListener("click", (event) => {
  const proxy = event.target.closest("[data-inspector-action]");
  if (!proxy) return;
  inspectorActions[Number(proxy.dataset.inspectorAction)]?.click();
});

document.addEventListener("focusin", (event) => {
  const pane = event.target.closest?.("[data-pane]");
  if (pane) setActivePane(pane.dataset.pane, false);
  if (event.target.closest?.("#app")) inspectElement(event.target);
});

const paneOrder = ["navigator", "queue", "inspector"];
let activePane = "navigator";
let jumpState = null;
const focusHistory = [];
const helpDialog = document.querySelector("#help-dialog");
const jumpLayer = document.querySelector("#jump-layer");
const keyboardAnnouncer = document.querySelector("#keyboard-announcer");
const keyboardModeLabel = document.querySelector("#keyboard-mode-label");
const focusableSelector = "button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";

function isTypingTarget(target) {
  return Boolean(target?.matches?.("input, textarea, select, [contenteditable='true']"));
}

function paneForKey(key) {
  return ({ s: "navigator", d: "queue", f: "inspector" })[key.toLowerCase()] || null;
}

function movementForKey(key) {
  return ({ ArrowLeft: "left", h: "left", ArrowRight: "right", l: "right", ArrowUp: "up", k: "up", ArrowDown: "down", j: "down" })[key] || null;
}

function cycledPaneName(name, delta) {
  const current = paneOrder.indexOf(name);
  return paneOrder[(current + delta + paneOrder.length) % paneOrder.length];
}

function paneElement(name) {
  return document.querySelector(`[data-pane="${name}"]`);
}

function visibleFocusable(pane) {
  return [...pane.querySelectorAll(focusableSelector)].filter((item) => {
    if (item.closest("[hidden]")) return false;
    return !item.hasAttribute("disabled") && item.getAttribute("aria-hidden") !== "true";
  });
}

function setActivePane(name, moveFocus = true) {
  const pane = paneElement(name);
  if (!pane) return;
  activePane = name;
  document.querySelectorAll("[data-pane]").forEach((item) => item.classList.toggle("is-keyboard-active", item === pane));
  if (moveFocus) {
    const target = pane.querySelector(".is-inspected")?.querySelector(focusableSelector) || visibleFocusable(pane)[0];
    (target || pane).focus({ preventScroll: true });
  }
  announce(`${name} pane`);
}

function moveWithinPane(delta) {
  const pane = paneElement(activePane);
  const items = pane ? visibleFocusable(pane) : [];
  if (!items.length) return;
  const current = items.indexOf(document.activeElement);
  const next = Math.max(0, Math.min(items.length - 1, current < 0 ? 0 : current + delta));
  items[next].focus({ preventScroll: true });
  items[next].scrollIntoView?.({ block: "nearest" });
}

function moveAcrossPanes(delta) {
  const current = paneOrder.indexOf(activePane);
  const next = Math.max(0, Math.min(paneOrder.length - 1, current + delta));
  if (next === current) {
    announce(`${activePane} pane boundary`);
    return;
  }
  setActivePane(paneOrder[next]);
}

function cyclePane(delta) {
  setActivePane(cycledPaneName(activePane, delta));
}

function announce(message) {
  if (!keyboardAnnouncer) return;
  keyboardAnnouncer.textContent = "";
  window.setTimeout?.(() => { keyboardAnnouncer.textContent = message; }, 0);
}

function contextualCommands() {
  const commands = [
    ["S / D / F", "Focus Navigator, Queue, or Inspector"],
    ["H J K L / arrows", "Move between panes or through the active pane"],
    ["Tab / Shift+Tab", "Cycle top-level panes in navigation mode"],
    ["G", "Jump: type two search characters, then a home-row hint"],
    ["Enter", "Activate the focused control"],
    ["Esc", "Cancel, close, or return"],
  ];
  if (document.querySelector("#entity-note-body")) commands.splice(5, 0, ["E", "Edit the current entity note"]);
  return commands;
}

function openHelp() {
  cancelJump();
  const commands = contextualCommands();
  document.querySelector("#help-commands").innerHTML = `<dl class="help-grid">${commands.map(([keys, description]) => `<div><dt>${escapeHtml(keys)}</dt><dd>${escapeHtml(description)}</dd></div>`).join("")}</dl>`;
  if (typeof helpDialog.showModal === "function") helpDialog.showModal();
  keyboardModeLabel.textContent = "HELP";
}

function startJump() {
  const pane = paneElement(activePane);
  const targets = pane ? visibleFocusable(pane) : [];
  if (!targets.length) return;
  jumpState = { query: "", targets, matches: [], hints: new Map() };
  jumpLayer.replaceChildren();
  keyboardModeLabel.textContent = "JUMP 0/2";
  announce("Jump mode. Type two characters from the target text.");
}

function updateJump(character) {
  if (!jumpState) return;
  jumpState.query += character.toLowerCase();
  keyboardModeLabel.textContent = `JUMP ${jumpState.query.length}/2`;
  if (jumpState.query.length < 2) {
    announce(`Jump search ${jumpState.query}. Type one more character.`);
    return;
  }
  const query = jumpState.query.slice(0, 2);
  jumpState.matches = jumpState.targets.filter((target) => jumpTargetText(target).includes(query));
  if (jumpState.matches.length === 1) {
    finishJump(jumpState.matches[0]);
    return;
  }
  const hints = "asdfghjklqwertyuiopzxcvbnm";
  jumpState.matches.slice(0, hints.length).forEach((target, index) => {
    const hint = hints[index];
    jumpState.hints.set(hint, target);
    const rect = target.getBoundingClientRect();
    const label = document.createElement("span");
    label.className = "jump-label";
    label.textContent = hint.toUpperCase();
    label.style.left = `${Math.max(4, rect.left - 8)}px`;
    label.style.top = `${Math.max(4, rect.top - 8)}px`;
    jumpLayer.append(label);
  });
  announce(jumpState.matches.length ? `${jumpState.matches.length} matches. Type the adjacent hint.` : `No targets contain ${query}. Press Escape to cancel.`);
}

function jumpTargetText(target) {
  return `${target.getAttribute("aria-label") || ""} ${target.textContent || ""}`.trim().toLowerCase();
}

function finishJump(target) {
  cancelJump();
  target.focus({ preventScroll: true });
  target.scrollIntoView?.({ block: "nearest" });
  announce(`Focused ${inspectorActionLabel(target)}`);
}

function cancelJump() {
  jumpState = null;
  jumpLayer?.replaceChildren();
  if (keyboardModeLabel) keyboardModeLabel.textContent = "NAV";
}

function handleEscape() {
  if (jumpState) return cancelJump();
  if (helpDialog?.open) {
    helpDialog.close();
    keyboardModeLabel.textContent = "NAV";
    return;
  }
  if (entityDetail) {
    showView(detailReturnView);
    return;
  }
  const prior = focusHistory.pop();
  if (prior?.isConnected) prior.focus({ preventScroll: true });
  else setActivePane("navigator");
}

document.querySelector("#help-button")?.addEventListener("click", openHelp);
helpDialog?.addEventListener("close", () => { keyboardModeLabel.textContent = "NAV"; });

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    handleEscape();
    return;
  }
  if (helpDialog?.open || isTypingTarget(event.target)) return;
  if (jumpState) {
    if (event.key === "Backspace") {
      event.preventDefault();
      cancelJump();
      startJump();
      return;
    }
    const hintTarget = jumpState.hints.get(event.key.toLowerCase());
    if (hintTarget) {
      event.preventDefault();
      finishJump(hintTarget);
    } else if (/^[a-z0-9]$/i.test(event.key) && jumpState.query.length < 2) {
      event.preventDefault();
      updateJump(event.key);
    }
    return;
  }
  if (event.key === "?" && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    openHelp();
    return;
  }
  if (event.key.toLowerCase() === "g" && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    startJump();
    return;
  }
  if (event.key.toLowerCase() === "e" && document.querySelector("#entity-note-body")) {
    event.preventDefault();
    document.querySelector("#entity-note-body").focus();
    return;
  }
  const pane = paneForKey(event.key);
  if (pane && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    focusHistory.push(document.activeElement);
    setActivePane(pane);
    return;
  }
  const movement = movementForKey(event.key);
  if (movement) {
    event.preventDefault();
    if (movement === "up" || movement === "down") moveWithinPane(movement === "up" ? -1 : 1);
    else moveAcrossPanes(movement === "left" ? -1 : 1);
    return;
  }
  if (event.key === "Tab" && event.target.closest?.("form")) return;
  if (event.key === "Tab" && document.activeElement?.closest?.("[data-pane]")) {
    event.preventDefault();
    cyclePane(event.shiftKey ? -1 : 1);
  }
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

if (configuredMode === "demo") {
  modeLabel.textContent = "House showcase enabled";
}
refresh();
setInterval(refresh, 300000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refresh();
});
