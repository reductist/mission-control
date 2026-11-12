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
const workspace = document.querySelector("#workspace");
const drawerBackdrop = document.querySelector("#drawer-backdrop");
const mobileSectionTabs = document.querySelector(".mobile-section-tabs");
const narrowLayoutQuery = window.matchMedia?.("(max-width: 680px)");

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
  contacts: {
    eyebrow: "Address book",
    title: "Contacts",
    description: "People and organizations stored as portable JSContact cards.",
  },
  requests: {
    eyebrow: "Follow-through", title: "Requests",
    description: "Open requests, linked work, and results ready for your next step.",
  },
  rewards: {
    eyebrow: "Family rewards",
    title: "Rewards",
    description: "Parent-operated morning credit, play windows, and explicit corrections.",
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
let familyRewardsDetail = null;
let openRequestsDetail = null;
let openRequestsLoadFailed = false;
let requestQuery = "";
let requestHistoryOpen = false;
let requestTogglePending = false;
let requestStatus = "active";
let requestTag = "";
let requestEditor = null;
let rewardsDate = null;
let rewardsTaskDetails = new Map();
let activeView = "overview";
let entityDetail = null;
let detailReturnView = "overview";
let commandSequence = 0;
let activityExpanded = false;
let scheduleFilter = "all";
let scheduleTags = [];
let editingTask = null;
let editingContact = null;
let contactQuery = "";
let scheduleLayout = "agenda";
let calendarRangeMode = "three-day";
let refreshInFlight = false;
const expandedParents = new Set();
const expandedTaskText = new Set();
const TASK_TITLE_PREVIEW_LENGTH = 72;
const TASK_DETAIL_PREVIEW_LENGTH = 120;

document.querySelector("#today-label").textContent = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
}).format(new Date());

document.querySelectorAll(".nav-item, .mobile-section-tab").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

function showView(view) {
  if (isNarrowLayout()) closeDrawers(false);
  activeView = view;
  entityDetail = null;
  activityExpanded = false;
  document.querySelectorAll(".nav-item, .mobile-section-tab").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (button.classList.contains("mobile-section-tab")) {
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
  });
  if (isNarrowLayout()) {
    document.querySelector(`.mobile-section-tab[data-view="${view}"]`)?.scrollIntoView?.({
      block: "nearest",
      inline: "center",
    });
  }
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
    const draft = captureTaskDraft();
    const detailTarget = entityDetail?.source;
    const nextDashboard = await request("/api/dashboard");
    const homeSearchLoad = await loadHomeSearchDetails(nextDashboard);
    const rewardsLoad = await loadFamilyRewardsDetail(nextDashboard);
    const requestsLoad = await loadOpenRequestsDetail(nextDashboard);
    let nextDetail = entityDetail;
    if (detailTarget) {
      nextDetail = await request(entityDetailPath(detailTarget));
    }
    dashboard = nextDashboard;
    homeSearchDetails = homeSearchLoad.details;
    familyRewardsDetail = rewardsLoad;
    openRequestsDetail = requestsLoad.detail;
    openRequestsLoadFailed = requestsLoad.failed;
    entityDetail = nextDetail;
    connectionLabel.textContent = "Online";
    modeLabel.textContent = dashboard.mode === "demo" ? "House showcase enabled" : "Operational workspace";
    versionLabel.textContent = `v${dashboard.version}`;
    statusDot.classList.add("is-online");
    renderSourceHealth();
    app.setAttribute("aria-busy", "false");
    render();
    restoreTaskDraft(draft);
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
    element.dataset?.editTask,
    element.dataset?.editContact,
    element.dataset?.editRequest,
    element.name === "tags" ? element.value : "",
  ].join("|");
}

function render() {
  if (!dashboard) return;
  if (entityDetail) {
    renderEntityDetail();
  } else if (activeView === "schedule") {
    renderSchedule();
  } else if (activeView === "contacts") {
    renderContacts();
  } else if (activeView === "requests") {
    renderOpenRequests();
  } else if (activeView === "rewards") {
    renderRewards();
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
  if (!entityDetail) renderSectionTasks();
}

function renderOverview() {
  const summary = dashboard.summary;
  const activeTasks = dashboard.tasks.filter((task) => !["done", "canceled"].includes(task.state) || task.children_count || task.progress?.total);
  const visibleTasks = overviewTaskRoots(dashboard.tasks);
  const house = providerInitiative("home-search");
  const scheduled = scheduleEntries().filter((entry) => entry.timing?.kind !== "anytime");
  const maintenanceCases = householdEntries().filter((entry) => entry.kind === "initiative");
  const openMaintenanceCases = maintenanceCases.filter((entry) => !["done", "closed", "completed"].includes(entry.state));
  const yardEntries = landscapeEntries();
  const yardInitiative = yardEntries.find((entry) => entry.kind === "initiative");
  const yardActions = yardEntries.filter((entry) => entry.kind === "action");
  const visibleYardActions = yardActions.slice(0, 4);
  const visibleCoreTasks = visibleTasks;
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
      ${compactMetric("Open", openWork)}${compactMetric("Moving", summary.in_progress)}${compactMetric("Blocked", blockedWork)}${compactMetric("Closed", summary.completed)}
    </div>
    <section class="panel queue-section">
      <div class="panel-header"><h2>Work queue</h2><span>${visibleCount} visible</span></div>
      <div class="task-list">${visibleCount ? `${visibleYardActions.map(landscapeActionRow).join("")}${renderTaskHierarchy(dashboard.tasks, visibleCoreTasks)}` : '<div class="empty">No active work. Add a shared task below.</div>'}</div>
      <form class="quick-add" id="quick-add-form"><input id="quick-add-title" name="title" required maxlength="160" placeholder="Add a shared task…" aria-label="New task title"><button class="primary-button" type="submit">Add</button><details class="task-options"><summary>Deadline and tags</summary>${taskMetadataFields("create")}</details><p class="form-error" role="status"></p></form>
    </section>
    <section class="overview-rooms" aria-label="Workspace rooms">
      ${overviewRoom("Schedule", nextScheduled.length ? `${nextScheduled.length} upcoming` : "Clear", nextScheduled.map((entry) => `${scheduleTimingLabel(entry)} — ${entry.title}`), "schedule")}
      ${overviewRoom("Maintenance", `${openMaintenanceCases.length} open`, openMaintenanceCases.slice(0, 2).map((entry) => entry.title), "maintenance")}
      ${overviewRoom("House", house ? "Search active" : "Not enabled", house ? [house.detail || house.title] : [], "house")}
      ${overviewRoom("Yard", `${yardActions.length} actions`, [yardInitiative?.title, ...yardActions.slice(0, 1).map((entry) => entry.title)].filter(Boolean), "yard")}
    </section>
  `;

  wireCommandButtons();
  wireTaskHierarchyControls();
  wireExpandableText();
  wireEntityLinks();
  document.querySelector("#quick-add-form").addEventListener("submit", addTask);
  document.querySelectorAll(".text-button[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
}

function overviewTaskRoots(tasks) {
  return visibleTaskRoots(tasks)
    .filter((task) => !["done", "canceled"].includes(task.state)
      || task.children_count
      || task.progress?.total);
}

function compactMetric(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function overviewRoom(label, status, lines, view) {
  return `<article class="room-row"><div><p class="kicker">${escapeHtml(label)}</p><strong>${escapeHtml(status)}</strong></div><ul>${lines.length ? lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("") : "<li>No current items</li>"}</ul><button class="text-button" data-view="${view}" type="button" aria-label="Open ${escapeHtml(label)}">Open →</button></article>`;
}

function contactCollectionValue(collection, property) {
  const entries = Object.entries(collection || {}).sort((left, right) =>
    (left[1]?.pref || 101) - (right[1]?.pref || 101) || left[0].localeCompare(right[0]));
  return entries[0]?.[1]?.[property] || "";
}

function contactName(contact) {
  return contact.record?.name?.full
    || contactCollectionValue(contact.record?.organizations, "name")
    || "Unnamed contact";
}

function renderContacts() {
  const contacts = (dashboard.contacts || []).filter((contact) => {
    const record = contact.record || {};
    const haystack = [
      contactName(contact),
      contactCollectionValue(record.emails, "address"),
      contactCollectionValue(record.phones, "number"),
      contactCollectionValue(record.organizations, "name"),
    ].join(" ").toLocaleLowerCase();
    return haystack.includes(contactQuery.toLocaleLowerCase());
  });
  app.innerHTML = `
    <section class="panel contact-toolbar" aria-label="Contact actions">
      <label for="contact-search">Find contact<input id="contact-search" type="search" value="${escapeHtml(contactQuery)}" placeholder="Name, email, phone, organization"></label>
      <button class="primary-button" id="add-contact" type="button">Add contact</button>
    </section>
    <section class="panel contact-panel">
      <div class="panel-header"><h2>Address book</h2><span>${contacts.length} ${contacts.length === 1 ? "contact" : "contacts"}</span></div>
      <div class="contact-list">${contacts.length ? contacts.map(contactRow).join("") : `<div class="empty">${contactQuery ? "No contacts match this search." : "No contacts yet. Add a person or organization to begin."}</div>`}</div>
    </section>`;
  document.querySelector("#add-contact").addEventListener("click", () => openContactEditor());
  document.querySelector("#contact-search").addEventListener("input", (event) => {
    contactQuery = event.target.value;
    renderContacts();
    const search = document.querySelector("#contact-search");
    search.focus({ preventScroll: true });
    search.setSelectionRange(contactQuery.length, contactQuery.length);
  });
  document.querySelectorAll("[data-edit-contact]").forEach((button) => {
    button.addEventListener("click", () => openContactEditor(button.dataset.editContact));
  });
}

function contactRow(contact) {
  const record = contact.record || {};
  const email = contactCollectionValue(record.emails, "address");
  const phone = contactCollectionValue(record.phones, "number");
  const organization = contactCollectionValue(record.organizations, "name");
  const address = contactCollectionValue(record.addresses, "full");
  return `<article class="contact-row">
    <div class="contact-identity"><span class="contact-avatar" aria-hidden="true">${escapeHtml(contactName(contact).slice(0, 1).toLocaleUpperCase() || "·")}</span><div><strong>${escapeHtml(contactName(contact))}</strong><p>${escapeHtml(organization || record.kind || "individual")}</p></div></div>
    <dl class="contact-details">${email ? `<div><dt>Email</dt><dd><a href="mailto:${escapeHtml(email)}">${escapeHtml(email)}</a></dd></div>` : ""}${phone ? `<div><dt>Phone</dt><dd><a href="tel:${escapeHtml(phone)}">${escapeHtml(phone)}</a></dd></div>` : ""}${address ? `<div><dt>Address</dt><dd>${escapeHtml(address)}</dd></div>` : ""}${!email && !phone && !address ? "<div><dt>Details</dt><dd>None added</dd></div>" : ""}</dl>
    <button class="text-button" type="button" data-edit-contact="${escapeHtml(contact.source.entity_id)}" aria-label="Edit ${escapeHtml(contactName(contact))}">Edit</button>
  </article>`;
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
        ${tagPicker("schedule-tags", scheduleTags, "Filter by tags", true)}
        <p class="tag-filter-note">Matches any selected tag. Untagged entries appear when all tags are cleared.</p>
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
  wireCommandButtons();
  wireTaskHierarchyControls();
  wireExpandableText();
  const tagFilter = document.querySelector("#schedule-tags");
  tagFilter?.addEventListener("change", () => {
    scheduleTags = selectedTags(tagFilter);
    rerenderSchedulePreservingFocus();
  });
  document.querySelector("[data-clear-schedule-tags]")?.addEventListener("click", () => {
    scheduleTags = [];
    rerenderSchedulePreservingFocus();
  });
}

function rerenderSchedulePreservingFocus() {
  const savedFocus = captureAppFocus();
  renderSchedule();
  restoreAppFocus(savedFocus);
}

function renderAgendaSchedule(entries, timeZone) {
  if (scheduleFilter === "tasks") return renderTaskReminderAgenda(entries, timeZone);
  return renderChronologicalAgenda(entries, timeZone);
}

function renderChronologicalAgenda(entries, timeZone) {
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

function renderTaskReminderAgenda(entries, timeZone) {
  const matchedIds = new Set(entries
    .filter((entry) => entry.source?.plugin_id === "core"
      && entry.source?.entity_type === "task")
    .map((entry) => entry.source.entity_id));
  const hierarchy = taskHierarchyForMatchedIds(matchedIds);
  const providerEntries = entries.filter((entry) => entry.source?.plugin_id !== "core");
  return `
    ${hierarchy.roots.length ? `
      <section class="panel schedule-task-hierarchy">
        <div class="panel-header"><h2>Shared tasks</h2><span>${matchedIds.size} matched · parent context retained</span></div>
        <div class="task-list">${renderTaskHierarchy(hierarchy.tasks, hierarchy.roots)}</div>
      </section>
    ` : ""}
    ${providerEntries.length ? renderChronologicalAgenda(providerEntries, timeZone) : ""}
    ${!hierarchy.roots.length && !providerEntries.length
      ? '<section class="panel empty">Nothing scheduled in this range.</section>'
      : ""}
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
  const kindMatches = scheduleFilter === "all"
    || (scheduleFilter === "events" && entry.kind === "event")
    || (scheduleFilter === "tasks" && entry.kind === "action");
  return kindMatches && matchesTags(entryTags(entry), scheduleTags);
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
  const parent = parentTaskForEntry(entry);
  const coreTask = entry.source?.plugin_id === "core" && entry.source?.entity_type === "task";
  const title = coreTask
    ? taskTextPreview(entry.title, `calendar:${entry.source.entity_id}:title`, 56, "calendar-title")
    : boundedTextPreview(entry.title, 56, "calendar-title");
  const content = `<span>${escapeHtml(time)}</span>${title}<small>${escapeHtml([parent ? `Child of ${parent.title}` : "", entryProvenance(entry)].filter(Boolean).join(" · "))}</small>`;
  if (coreTask) {
    return `<div class="calendar-item ${kindClass}">${content}<button class="text-button" type="button" data-edit-task="${escapeHtml(entry.source.entity_id)}" aria-label="Edit ${escapeHtml(entry.title)}">Edit</button></div>`;
  }
  if (providerHasCapability(entry.source?.plugin_id, "entity-details")) {
    return `<button class="calendar-item ${kindClass}"${entryAccentAttribute(entry)} type="button" data-entity-link data-plugin-id="${escapeHtml(entry.source.plugin_id)}" data-entity-type="${escapeHtml(entry.source.entity_type)}" data-entity-id="${escapeHtml(entry.source.entity_id)}" aria-label="${escapeHtml(`${time}: ${entry.title}`)}">${content}</button>`;
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
  const parent = parentTaskForEntry(entry);
  const identity = `${entry.source?.plugin_id || "unknown"}:${entry.source?.entity_type || "entry"}:${entry.source?.entity_id || entry.id}`;
  const title = taskTextPreview(
    entry.title,
    `schedule:${identity}:title`,
    TASK_TITLE_PREVIEW_LENGTH,
    "task-title-text",
  );
  const detail = entry.detail
    ? taskTextPreview(
      entry.detail,
      `schedule:${identity}:detail`,
      TASK_DETAIL_PREVIEW_LENGTH,
      "task-detail-text",
    )
    : "";
  const detailControl = entry.source?.plugin_id !== "core"
    && providerHasCapability(entry.source?.plugin_id, "entity-details")
    ? `<button class="text-button" type="button" data-entity-link data-plugin-id="${escapeHtml(entry.source.plugin_id)}" data-entity-type="${escapeHtml(entry.source.entity_type)}" data-entity-id="${escapeHtml(entry.source.entity_id)}">Open details</button>`
    : "";
  return `
    <article class="schedule-row"${entryAccentAttribute(entry)}>
      <time class="schedule-time"${timeValue ? ` datetime="${escapeHtml(timeValue)}"` : ""}>${escapeHtml(scheduleTimingLabel(entry))}</time>
      <div>
        <h3 class="task-title">${title}</h3>
        ${detail ? `<p class="task-description">${detail}</p>` : ""}
        <p class="item-meta">${parent ? `Child of ${escapeHtml(parent.title)} · ` : ""}${escapeHtml(provenance)}${entry.source?.plugin_id === "core" ? ` · ${escapeHtml(taskDeadlineLabel(dashboard.tasks.find((task) => task.id === entry.source.entity_id) || {}))}` : ""}</p>
        ${entry.source?.plugin_id === "core" ? `<button class="text-button" type="button" data-edit-task="${escapeHtml(entry.source.entity_id)}">Edit</button>` : detailControl}
      </div>
      <span class="state-badge">${escapeHtml(kindLabel)}</span>
    </article>
  `;
}

function parentTaskForEntry(entry) {
  if (entry.source?.plugin_id !== "core" || entry.source?.entity_type !== "task") return null;
  const task = dashboard?.tasks?.find((candidate) => candidate.id === entry.source.entity_id);
  return task?.parent_id
    ? dashboard.tasks.find((candidate) => candidate.id === task.parent_id) || null
    : null;
}

function entityTitle(entry) {
  if (entry.source?.plugin_id === "core" && entry.source?.entity_type === "task") {
    return `<button class="entity-link" type="button" data-edit-task="${escapeHtml(entry.source.entity_id)}">${escapeHtml(entry.title)}</button>`;
  }
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
  wireExpandableText();
}

function requestRecords(detail = openRequestsDetail) {
  return (detail?.attributes || []).filter((item) => item.key.startsWith("request:")).flatMap((item) => {
    try { return [JSON.parse(item.value)]; } catch (_error) { return []; }
  });
}

async function loadOpenRequestsDetail(source) {
  const tracker = (source?.agenda || []).find((entry) => entry.source?.plugin_id === "open-requests" && entry.source.entity_type === "tracker");
  if (!tracker) return { detail: null, failed: false };
  try { return { detail: await request(entityDetailPath(tracker.source)), failed: false }; }
  catch (_error) { return { detail: openRequestsDetail, failed: true }; }
}

function requestSourceKey(source) { return JSON.stringify([source.plugin_id, source.entity_type, source.entity_id]); }

function requestTaskOptions(selected = []) {
  const entries = new Map();
  for (const task of dashboard?.tasks || []) {
    const source = { plugin_id: "core", entity_type: "task", entity_id: task.id };
    entries.set(requestSourceKey(source), { source, title: task.title, state: task.state });
  }
  for (const task of [...(dashboard?.agenda || []), ...(dashboard?.closed_items || [])]) {
    if (task.source?.plugin_id !== "open-requests" && task.kind === "action") entries.set(requestSourceKey(task.source), task);
  }
  for (const source of selected) {
    const key = requestSourceKey(source);
    if (!entries.has(key)) entries.set(key, { source, title: `${source.plugin_id} / ${source.entity_id}`, state: "Not in current view" });
  }
  return [...entries.values()];
}

function filteredRequests(records = requestRecords(), status = requestStatus) {
  const query = requestQuery.trim().toLocaleLowerCase();
  return records.filter((item) => (status === "all" || (status === "active" ? item.status !== "closed" : item.status === status))
    && (!requestTag || item.tags.includes(requestTag))
    && (!query || [item.title, item.description, item.next_step, ...item.tags].join(" ").toLocaleLowerCase().includes(query)));
}

function requestWebLinks(links) {
  return links.map((link) => {
    const url = safeHttpUrl(link.url);
    return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.label || link.url)}</a>` : `<span>${escapeHtml(link.label || "Unavailable link")}</span>`;
  }).join(" · ");
}

function requestCard(item) {
  const tasks = requestTaskOptions(item.task_links);
  return `<article class="request-card">
    <div class="request-card-heading"><label class="request-completion"><input type="checkbox" data-complete-request="${escapeHtml(item.id)}" aria-label="${item.status === "closed" ? "Reopen" : "Complete"} request: ${escapeHtml(item.title)}"${item.status === "closed" ? " checked" : ""}${requestTogglePending ? " disabled" : ""}><h3>${escapeHtml(item.title)}</h3></label><span class="state-badge">${escapeHtml(item.status === "ready" ? "Ready for you" : item.status)}</span></div>
    ${item.description ? `<p class="request-description">${escapeHtml(item.description)}</p>` : ""}
    <p><strong>Next step:</strong> ${escapeHtml(item.next_step || "Not recorded yet")}</p>
    ${item.tags.length ? `<p class="request-tags">${item.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</p>` : ""}
    <dl class="request-links"><div><dt>Linked tasks</dt><dd>${item.task_links.length ? item.task_links.map((source) => { const task = tasks.find((candidate) => requestSourceKey(candidate.source) === requestSourceKey(source)); return `${entityLink(task)} <small>${escapeHtml(task.state || "")}</small>`; }).join(" · ") : "None linked"}</dd></div>
    <div><dt>Follow-up work</dt><dd>${item.work_links.length ? requestWebLinks(item.work_links) : "No link yet"}</dd></div>
    <div><dt>Results / solutions</dt><dd>${item.result_links.length ? requestWebLinks(item.result_links) : "No result link yet"}</dd></div></dl>
    <div class="request-card-footer"><small><span class="request-id">Request ID: <code>${escapeHtml(item.id)}</code></span>Updated ${escapeHtml(formatDateTime(item.updated_at))}</small><button class="text-button" type="button" data-edit-request="${escapeHtml(item.id)}">Edit details</button></div>
  </article>`;
}

function renderOpenRequests() {
  if (!openRequestsDetail) {
    renderNoDemo("Open requests unavailable", openRequestsLoadFailed ? "The request tracker could not be loaded. Try refreshing." : "Enable the open-requests plugin to track requests and link their follow-up work.");
    return;
  }
  const records = requestRecords();
  const tags = [...new Set(records.flatMap((item) => item.tags))].sort();
  const items = filteredRequests(records);
  const completed = filteredRequests(records, "closed");
  app.innerHTML = `<section class="panel requests-panel">
    <div class="panel-header"><h2>Your requests</h2><button class="primary-button" id="add-request" type="button">Add request</button></div>
    ${openRequestsLoadFailed ? '<p class="requests-warning" role="status">Showing previously loaded requests. Refresh failed; changes may conflict with newer work.</p>' : ""}
    <p class="requests-guidance">Keep a request open until your follow-through is finished. Completed tasks and result links do not close it automatically.</p>
    <div class="requests-toolbar"><label>Search<input id="request-search" type="search" value="${escapeHtml(requestQuery)}" placeholder="Title, next step, or tag"></label>
    <label>Status<select id="request-status">${[["active", "Open requests"], ["open", "Open"], ["waiting", "Waiting"], ["ready", "Ready for you"]].map(([value, label]) => `<option value="${value}"${requestStatus === value ? " selected" : ""}>${label}</option>`).join("")}</select></label>
    <label>Tag<select id="request-tag"><option value="">All tags</option>${tags.map((tag) => `<option value="${escapeHtml(tag)}"${requestTag === tag ? " selected" : ""}>${escapeHtml(tag)}</option>`).join("")}</select></label></div>
    <p class="requests-count">${items.length} shown · ${records.filter((item) => item.status !== "closed").length} open</p>
    <div class="request-list">${items.length ? items.map(requestCard).join("") : '<div class="empty">No open requests match these filters.</div>'}</div>
    <details class="request-history"${requestHistoryOpen ? " open" : ""}><summary>Completed history (${completed.length})</summary><p class="requests-guidance">Uncheck a request to reopen it. Search and tag filters also apply here.</p>${completed.length ? completed.map(requestCard).join("") : '<div class="empty">No completed requests match these filters.</div>'}</details></section>`;
  document.querySelector("#add-request").addEventListener("click", () => openRequestEditor());
  document.querySelector("#request-search").addEventListener("input", (event) => {
    requestQuery = event.target.value; renderOpenRequests();
    const input = document.querySelector("#request-search"); input.focus();
  });
  for (const [id, setter] of [["request-status", (value) => { requestStatus = value; }], ["request-tag", (value) => { requestTag = value; }]]) {
    document.querySelector(`#${id}`).addEventListener("change", (event) => { setter(event.target.value); renderOpenRequests(); });
  }
  document.querySelectorAll("[data-edit-request]").forEach((button) => button.addEventListener("click", () => openRequestEditor(button.dataset.editRequest)));
  document.querySelector(".request-history").addEventListener("toggle", (event) => { requestHistoryOpen = event.target.open; });
  document.querySelectorAll("[data-complete-request]").forEach((input) => input.addEventListener("change", () => toggleRequestCompletion(input)));
  wireEntityLinks();
}

async function toggleRequestCompletion(input) {
  if (requestTogglePending || requestEditor?.pending) return;
  const item = requestRecords().find((record) => record.id === input.dataset.completeRequest);
  if (!item) return;
  const status = input.checked ? "closed" : "open";
  const document = Object.fromEntries(["title", "description", "next_step", "tags", "task_links", "work_links", "result_links"].map((key) => [key, item[key]]));
  document.status = status;
  requestTogglePending = true;
  let notice;
  let tone = "success";
  renderOpenRequests();
  try {
    await request("/api/commands", { method: "POST", body: JSON.stringify({
      schema_version: "mission-control.command/v1", command_id: `web-request-${Date.now()}-${++commandSequence}`,
      target: { plugin_id: "open-requests", entity_type: "tracker", entity_id: "requests" },
      expected_revision: openRequestsDetail.revision,
      command: "update-request", arguments: { request_id: item.id, request: document },
    }) });
    await refresh();
    notice = status === "closed" ? "Request completed. Find it in Completed history." : "Request reopened.";
  } catch (error) {
    await refresh();
    tone = "warning";
    notice = error.status === 409 ? "Requests changed. Review the refreshed status before trying again." : "Could not confirm the change. Check the current status before trying again.";
  } finally {
    requestTogglePending = false;
    if (activeView === "requests" && !entityDetail) { renderOpenRequests(); showNotice(notice, tone); }
  }
}

function requestLinkEditor(kind, links) {
  return `<fieldset class="request-link-editor" data-request-links="${kind}"><legend>${kind === "work_links" ? "Follow-up work links" : "Result / solution links"}</legend><p>Paste a shareable HTTP(S) link, such as a Drive document. This does not change its sharing permissions.</p><div class="request-link-rows">${links.map(requestLinkRow).join("")}</div><button class="secondary-button" type="button" data-add-request-link>Add link</button></fieldset>`;
}

function requestLinkRow(link = { label: "", url: "" }) {
  return `<div class="request-link-row"><label>Label<input data-link-label maxlength="128" value="${escapeHtml(link.label)}" required></label><label>URL<input data-link-url type="url" maxlength="1024" value="${escapeHtml(link.url)}" placeholder="https://" required></label><button class="text-button" type="button" data-remove-request-link aria-label="Remove link">Remove</button></div>`;
}

function openRequestEditor(id = null) {
  if (requestTogglePending || requestEditor?.pending || !openRequestsDetail) return;
  const item = id ? requestRecords().find((record) => record.id === id) : null;
  if (id && !item) return;
  requestEditor = { id, revision: openRequestsDetail.revision, pending: false };
  const selected = item?.task_links || [];
  const tasks = requestTaskOptions(selected);
  const dialog = document.querySelector("#request-editor-dialog");
  document.querySelector("#request-editor-content").innerHTML = `<form id="request-edit-form" class="task-edit-form">
    <div class="dialog-heading"><h2 id="request-editor-title">${id ? "Edit request" : "Add request"}</h2><button type="button" data-close-request-editor aria-label="Close request editor">×</button></div>
    <label>Title<input name="title" value="${escapeHtml(item?.title || "")}" maxlength="256" required autofocus></label>
    <label>Request / context<textarea name="description" maxlength="1200" rows="3">${escapeHtml(item?.description || "")}</textarea></label>
    <label>Status<select name="status">${[["open", "Open"], ["waiting", "Waiting"], ["ready", "Ready for you"], ["closed", "Closed"]].map(([value, label]) => `<option value="${value}"${item?.status === value ? " selected" : ""}>${label}</option>`).join("")}</select></label>
    <label>Next step<input name="next_step" value="${escapeHtml(item?.next_step || "")}" maxlength="512"></label>
    <label>Tags (comma-separated)<input name="request_tags" value="${escapeHtml((item?.tags || []).join(", "))}"></label>
    <fieldset class="request-task-picker"><legend>Linked tasks (up to 20)</legend>${tasks.length ? tasks.map((task) => `<label><input type="checkbox" name="request_tasks" value="${escapeHtml(JSON.stringify(task.source))}"${selected.some((source) => requestSourceKey(source) === requestSourceKey(task.source)) ? " checked" : ""}><span>${escapeHtml(task.title)} <small>${escapeHtml(task.state || "")}</small></span></label>`).join("") : '<p>No tasks available yet.</p>'}</fieldset>
    ${requestLinkEditor("work_links", item?.work_links || [])}${requestLinkEditor("result_links", item?.result_links || [])}
    <p class="deadline-note">Links may be reused across requests. Keep the complete record under 4,096 characters, including link metadata. Saving never changes linked tasks or closes this request automatically.</p>
    <p class="form-error" role="status"></p><div class="review-controls"><button class="primary-button" type="submit">Save request</button><button class="secondary-button" type="button" data-close-request-editor>Cancel</button></div>
  </form>`;
  const form = document.querySelector("#request-edit-form");
  form.addEventListener("submit", saveRequest);
  form.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-request-editor]")) closeRequestEditor();
    if (event.target.closest("[data-add-request-link]")) event.target.closest("fieldset").querySelector(".request-link-rows").insertAdjacentHTML("beforeend", requestLinkRow());
    if (event.target.closest("[data-remove-request-link]")) event.target.closest(".request-link-row").remove();
  });
  dialog.showModal();
}

function requestFromForm(form) {
  const result = {
    title: form.elements.title.value.trim(), description: form.elements.description.value.trim(), status: form.elements.status.value,
    next_step: form.elements.next_step.value.trim(), tags: [...new Set(form.elements.request_tags.value.split(",").map((value) => value.trim()).filter(Boolean))],
    task_links: [...form.querySelectorAll('[name="request_tasks"]:checked')].map((input) => JSON.parse(input.value)),
  };
  for (const kind of ["work_links", "result_links"]) result[kind] = [...form.querySelectorAll(`[data-request-links="${kind}"] .request-link-row`)].map((row) => {
    const label = row.querySelector("[data-link-label]").value.trim();
    const url = row.querySelector("[data-link-url]").value.trim();
    if (!label || !safeHttpUrl(url)) throw new Error("Each link needs a label and a valid HTTP(S) URL.");
    return { label, url };
  });
  if (!result.title) throw new Error("Add a request title.");
  return result;
}

function closeRequestEditor() {
  if (requestEditor?.pending) return;
  requestEditor = null;
  dialogClose("#request-editor-dialog");
}

async function saveRequest(event) {
  event.preventDefault();
  if (!requestEditor || requestEditor.pending) return;
  const editor = requestEditor;
  const form = event.currentTarget;
  try {
    const document = requestFromForm(form);
    editor.pending = true;
    form.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    const fingerprint = JSON.stringify(document);
    if (editor.attempt && editor.attempt.fingerprint !== fingerprint) {
      throw new Error("A previous save may have reached the server. Retry the unchanged draft, or close and reopen after refreshing before making different changes.");
    }
    editor.attempt ||= { fingerprint, body: JSON.stringify({
      schema_version: "mission-control.command/v1", command_id: `web-request-${Date.now()}-${++commandSequence}`,
      target: { plugin_id: "open-requests", entity_type: "tracker", entity_id: "requests" }, expected_revision: editor.revision,
      command: editor.id ? "update-request" : "create-request", arguments: { ...(editor.id ? { request_id: editor.id } : {}), request: document },
    }) };
    await request("/api/commands", { method: "POST", body: editor.attempt.body });
    editor.pending = false;
    closeRequestEditor();
    await refresh();
    showNotice(editor.id ? "Request updated." : "Request added.");
  } catch (error) {
    form.querySelector(".form-error").textContent = error.status === 409
      ? "Requests changed while you were editing. Your draft is still here. Copy any changes, then close and reopen to review the latest version."
      : error.message;
    if (error.status && error.status < 500) editor.attempt = null;
    if (error.status === 409) await refresh();
  } finally {
    editor.pending = false;
    form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function familyRewardsAccount(source = dashboard) {
  return (source?.agenda || []).find((entry) =>
    entry.source?.plugin_id === "family-rewards"
      && entry.source?.entity_type === "account"
      && entry.source?.entity_id === "family-credit");
}

async function loadFamilyRewardsDetail(source) {
  const account = familyRewardsAccount(source);
  if (!account) return null;
  try {
    return await request(entityDetailPath(account.source));
  } catch (_error) {
    return familyRewardsDetail;
  }
}

function rewardAttribute(key, detail = familyRewardsDetail) {
  return (detail?.attributes || []).find((item) => item.key === key)?.value;
}

function rewardDocument(key, fallback) {
  try {
    return JSON.parse(rewardAttribute(key) || "");
  } catch (_error) {
    return fallback;
  }
}

function rewardTaskState(task, localDate, snapshot) {
  if (localDate === snapshot.local_date) {
    return (snapshot.tasks || []).find((item) => item.id === task.id) || task;
  }
  const detail = rewardsTaskDetails.get(task.id);
  const attributes = Object.fromEntries((detail?.attributes || []).map((item) => [item.key, item.value]));
  return {
    ...task,
    completed: detail?.state === "checked",
    award_entry_id: attributes["award-entry-id"] === "none" ? null : attributes["award-entry-id"],
  };
}

async function loadRewardsTasks(localDate) {
  const settings = rewardDocument("rewards-settings", { tasks: [] });
  const pairs = await Promise.all((settings.tasks || []).map(async (task) => {
    const source = { plugin_id: "family-rewards", entity_type: "routine-task", entity_id: `morning:${localDate}:${task.id}` };
    try {
      return [task.id, await request(entityDetailPath(source))];
    } catch (_error) {
      return [task.id, null];
    }
  }));
  rewardsTaskDetails = new Map(pairs);
}

function renderRewards() {
  if (!familyRewardsDetail) {
    app.innerHTML = renderNoDemo(
      "Family rewards is not enabled",
      "Enable the family-rewards plugin to use the parent-operated point ledger. This view does not add child authentication or device enforcement.",
    );
    return;
  }
  const snapshot = rewardDocument("rewards-snapshot", {});
  const settings = rewardDocument("rewards-settings", { tasks: [], windows: [] });
  const overrides = rewardDocument("rewards-overrides", []);
  rewardsDate ||= snapshot.local_date;
  const tasks = (settings.tasks || []).map((task) => rewardTaskState(task, rewardsDate, snapshot));
  const reversed = new Set((familyRewardsDetail.activity || []).map((entry) =>
    entry.body?.match(/Reverses entry: ([^\n]+)/)?.[1]).filter(Boolean));
  app.innerHTML = `
    <div class="ops-summary rewards-summary" aria-label="Reward summary">
      ${compactMetric("Available", `${snapshot.balance_minutes} min`)}
      ${compactMetric("School cap", `${settings.school_day_cap_minutes} min`)}
      ${compactMetric("Other-day cap", `${settings.non_school_day_cap_minutes} min`)}
      ${compactMetric("Timezone", settings.timezone)}
    </div>
    <section class="panel rewards-routine">
      <div class="panel-header"><h2>Morning routine</h2><label>Family date <input id="rewards-date" type="date" value="${escapeHtml(rewardsDate)}"></label></div>
      <p class="rewards-guidance">Each task earns independently. The morning target is guidance, not an all-or-nothing cliff; reminders and parent support count.</p>
      <div class="reward-task-list">${tasks.map((task) => `<article class="reward-task ${task.completed ? "is-complete" : ""}"><div><strong>${escapeHtml(task.label)}</strong><p>${task.minutes} minutes</p></div><button class="${task.completed ? "secondary-button" : "primary-button"}" type="button" data-reward-task="${escapeHtml(task.id)}" data-entry-id="${escapeHtml(task.award_entry_id || "")}">${task.completed ? "Undo correction" : "Check off"}</button></article>`).join("")}</div>
    </section>
    <section class="panel rewards-spend">
      <div class="panel-header"><h2>Record play credit</h2><span>No timer or device enforcement</span></div>
      <form class="reward-inline-form" id="reward-spend-form">
        <label>Minutes<input name="minutes" type="number" min="1" max="1440" required></label>
        <label>Note<input name="note" maxlength="240" placeholder="Optional context"></label>
        <button class="primary-button" type="submit">Redeem</button><p class="form-error" role="status"></p>
      </form>
    </section>
    <section class="panel rewards-history">
      <div class="panel-header"><h2>Audit history</h2><span>Corrections append; entries are never edited</span></div>
      <div class="activity-list">${(familyRewardsDetail.activity || []).length ? [...familyRewardsDetail.activity].reverse().map((entry) => {
        const entryId = entry.activity_id.replace(/^ledger:/, "");
        const reversible = ["family-rewards.earn", "family-rewards.spend"].includes(entry.activity_type) && !reversed.has(entryId);
        return `<article class="activity-row"><div><strong>${escapeHtml(entry.summary)}</strong><p>${escapeHtml(entry.body || "")}</p><small>${escapeHtml(formatDateTime(entry.occurred_at))}</small></div>${reversible ? `<button class="text-button" type="button" data-reverse-entry="${escapeHtml(entryId)}">${entry.activity_type.endsWith("spend") ? "Refund" : "Correct"}</button>` : ""}</article>`;
      }).join("") : '<div class="empty">No credit activity yet.</div>'}</div>
    </section>
    <details class="panel rewards-settings"><summary>Reward settings</summary>
      <form class="snapshot-form" id="reward-settings-form">
        <div class="reward-settings-grid"><label>Timezone<input name="timezone" value="${escapeHtml(settings.timezone)}" required></label><label>School-day cap<input name="school-cap" type="number" min="0" max="1440" value="${settings.school_day_cap_minutes}" required></label><label>Non-school-day cap<input name="other-cap" type="number" min="0" max="1440" value="${settings.non_school_day_cap_minutes}" required></label></div>
        <fieldset><legend>Four independent morning tasks</legend>${(settings.tasks || []).map((task) => `<div class="reward-task-setting"><label>Label<input name="task-label-${escapeHtml(task.id)}" maxlength="160" value="${escapeHtml(task.label)}" required></label><label>Minutes<input name="task-minutes-${escapeHtml(task.id)}" type="number" min="1" max="240" value="${task.minutes}" required></label></div>`).join("")}</fieldset>
        <label>Recurring play windows (JSON)<textarea name="windows" rows="8" spellcheck="false">${escapeHtml(JSON.stringify(settings.windows, null, 2))}</textarea></label>
        <div class="review-controls"><button class="primary-button" type="submit">Save settings</button><button class="secondary-button" id="cancel-reward-settings" type="button">Cancel changes</button></div><p class="form-error" role="status"></p>
      </form>
    </details>
    <section class="panel rewards-overrides">
      <div class="panel-header"><h2>Date overrides</h2><span>Holidays and late pickups</span></div>
      <form class="reward-inline-form" id="reward-override-form">
        <label>Date<input name="local-date" type="date" required></label><label>Day type<select name="school-day"><option value="default">Use weekday default</option><option value="school">School day</option><option value="other">Non-school day</option></select></label><label><input name="eligible" type="checkbox" checked> Eligible for play</label><label>Starts<input name="starts-at" type="time" value="15:00"></label><label>Ends<input name="ends-at" type="time" value="19:00"></label><label>Note<input name="note" maxlength="160"></label><button class="primary-button" type="submit">Save override</button><p class="form-error" role="status"></p>
      </form>
      <div class="override-list">${overrides.length ? overrides.map((item) => `<article><div><strong>${escapeHtml(item.local_date)}</strong><p>${item.eligible ? `${escapeHtml(item.starts_at)}–${escapeHtml(item.ends_at)}` : "Not eligible"}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</p></div><button class="text-button" type="button" data-remove-override="${escapeHtml(item.local_date)}">Remove</button></article>`).join("") : '<div class="empty">No date overrides.</div>'}</div>
    </section>`;
  wireRewards();
}

async function sendRewardCommand(operation, arguments, control) {
  control?.setAttribute("disabled", "");
  try {
    await request("/api/commands", { method: "POST", body: JSON.stringify({
      schema_version: "mission-control.command/v1",
      command_id: `web-reward-${Date.now()}-${++commandSequence}`,
      target: familyRewardsDetail.source,
      expected_revision: familyRewardsDetail.revision,
      command: operation,
      arguments,
    }) });
    await refresh();
    if (rewardsDate && rewardsDate !== rewardDocument("rewards-snapshot", {}).local_date) {
      await loadRewardsTasks(rewardsDate);
      renderRewards();
    }
  } catch (error) {
    showNotice(error.message, error.status === 409 ? "warning" : "error");
    control?.removeAttribute("disabled");
  }
}

function wireRewards() {
  document.querySelector("#rewards-date")?.addEventListener("change", async (event) => {
    rewardsDate = event.target.value;
    await loadRewardsTasks(rewardsDate);
    renderRewards();
  });
  document.querySelectorAll("[data-reward-task]").forEach((button) => button.addEventListener("click", () => {
    const operation = button.dataset.entryId ? "reverse-entry" : "award-task";
    const arguments = button.dataset.entryId
      ? { entry_id: button.dataset.entryId, note: "Morning checkmark corrected" }
      : { local_date: rewardsDate, task_id: button.dataset.rewardTask };
    sendRewardCommand(operation, arguments, button);
  }));
  document.querySelectorAll("[data-reverse-entry]").forEach((button) => button.addEventListener("click", () => {
    sendRewardCommand("reverse-entry", { entry_id: button.dataset.reverseEntry, note: "Parent-recorded correction" }, button);
  }));
  document.querySelector("#reward-spend-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    sendRewardCommand("spend-credit", { local_date: rewardsDate, minutes: Number(form.elements.minutes.value), note: form.elements.note.value }, form.querySelector("button"));
  });
  document.querySelector("#reward-settings-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const current = rewardDocument("rewards-settings", { tasks: [] });
    let windows;
    try { windows = JSON.parse(form.elements.windows.value); } catch (_error) {
      form.querySelector(".form-error").textContent = "Recurring windows must be valid JSON.";
      return;
    }
    const settings = {
      timezone: form.elements.timezone.value.trim(),
      school_day_cap_minutes: Number(form.elements["school-cap"].value),
      non_school_day_cap_minutes: Number(form.elements["other-cap"].value),
      tasks: current.tasks.map((task) => ({ id: task.id, label: form.elements[`task-label-${task.id}`].value.trim(), minutes: Number(form.elements[`task-minutes-${task.id}`].value) })),
      windows,
    };
    sendRewardCommand("update-settings", { settings }, form.querySelector("button[type=submit]"));
  });
  document.querySelector("#cancel-reward-settings")?.addEventListener("click", renderRewards);
  document.querySelector("#reward-override-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const schoolValue = form.elements["school-day"].value;
    const eligible = form.elements.eligible.checked;
    sendRewardCommand("set-date-override", { local_date: form.elements["local-date"].value, school_day: schoolValue === "default" ? null : schoolValue === "school", eligible, starts_at: eligible ? form.elements["starts-at"].value : null, ends_at: eligible ? form.elements["ends-at"].value : null, note: form.elements.note.value }, form.querySelector("button"));
  });
  document.querySelectorAll("[data-remove-override]").forEach((button) => button.addEventListener("click", () => sendRewardCommand("remove-date-override", { local_date: button.dataset.removeOverride }, button)));
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
  const relatedRequests = requestRecords().filter((item) => item.task_links.some((source) => requestSourceKey(source) === requestSourceKey(detail.source)));
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
          ${relatedRequests.length ? `<div class="related-requests"><h3>Related requests</h3>${relatedRequests.map((item) => `<p>${entityLink({title: item.title, source: {plugin_id: "open-requests", entity_type: "request", entity_id: item.id}})} <small>${escapeHtml(item.status)}</small></p>`).join("")}</div>` : ""}
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
  wireEntityLinks();
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

function taskChildren(task, tasks = dashboard?.tasks || []) {
  return tasks
    .filter((candidate) => candidate.parent_id === task.id)
    .sort((left, right) => (left.sibling_order ?? 0) - (right.sibling_order ?? 0)
      || left.title.localeCompare(right.title));
}

function visibleTaskRoots(tasks) {
  const ids = new Set(tasks.map((task) => task.id));
  return tasks
    .filter((task) => !task.parent_id || !ids.has(task.parent_id))
    .sort((left, right) => (left.sibling_order ?? 0) - (right.sibling_order ?? 0)
      || left.title.localeCompare(right.title));
}

function renderTaskHierarchy(tasks, roots = visibleTaskRoots(tasks), forceExpanded = false) {
  return roots.map((task) => {
    const children = taskChildren(task, tasks);
    const expanded = forceExpanded || task.filter_context || expandedParents.has(task.id);
    return `${taskRow(task, { children, expanded })}${children.length && expanded
      ? `<div class="task-children" role="group" aria-label="Children of ${escapeHtml(task.title)}">${children.map((child, index) => taskRow(child, { child: true, position: index, siblingCount: children.length })).join("")}</div>`
      : ""}`;
  }).join("");
}

function taskTextPreview(value, key, limit, className) {
  const text = value || "";
  if (text.length <= limit) return `<span class="${className}">${escapeHtml(text)}</span>`;
  const expanded = expandedTaskText.has(key);
  const preview = `${text.slice(0, limit).trimEnd()}...`;
  return `<button class="expandable-text ${className}" type="button" data-expand-text="${escapeHtml(key)}" aria-expanded="${expanded}" aria-label="${expanded ? "Collapse" : "Expand"} full text"><span class="text-preview"${expanded ? " hidden" : ""}>${escapeHtml(preview)}</span><span class="text-full"${expanded ? "" : " hidden"}>${escapeHtml(text)}</span></button>`;
}

function boundedTextPreview(value, limit, className) {
  const text = value || "";
  const preview = text.length > limit ? `${text.slice(0, limit).trimEnd()}...` : text;
  return `<strong class="${className}" title="${escapeHtml(text)}">${escapeHtml(preview)}</strong>`;
}

function parentProgress(task, children) {
  if (task.progress) return task.progress;
  const done = children.filter((child) => child.state === "done").length;
  const canceled = children.filter((child) => child.state === "canceled").length;
  return { done, canceled, unfinished: children.length - done - canceled, total: children.length };
}

function taskRow(task, options = {}) {
  const { children = [], child = false, position = 0, siblingCount = 0 } = options;
  const done = task.state === "done";
  const closed = done || task.state === "canceled";
  const nextState = closed ? "ready" : "done";
  const badgeClass = task.blocked ? "is-blocked" : task.state === "in-progress" ? "is-active" : "";
  const detail = task.description || task.waiting_on || "No additional detail";
  const parent = children.length > 0 || task.children_count > 0 || task.progress?.total > 0;
  const expanded = options.expanded ?? expandedParents.has(task.id);
  const progress = parentProgress(task, children);
  const progressLabel = parent
    ? `${progress.done || 0}/${progress.total ?? task.children_count ?? 0} done${progress.canceled ? ` · ${progress.canceled} canceled` : ""}`
    : "";
  const completionControl = parent && progress.unfinished > 0 && !closed
    ? `<button class="task-toggle has-unfinished" type="button" data-show-unfinished="${escapeHtml(task.id)}" aria-label="${escapeHtml(`${progress.unfinished} unfinished child tasks; expand ${task.title}`)}">!</button>`
    : `<button class="task-toggle" type="button" data-plugin-id="core" data-entity-type="task" data-entity-id="${escapeHtml(task.id)}" data-revision="${escapeHtml(task.updated_at)}" data-command="set-state" data-next-state="${nextState}" aria-label="${closed ? "Reopen" : "Complete"} ${escapeHtml(task.title)}">${done ? "✓" : task.state === "canceled" ? "×" : ""}</button>`;
  return `
    <article class="task-row ${done ? "is-done" : ""} ${parent ? "is-parent" : ""} ${child ? "is-child" : ""}" data-task-id="${escapeHtml(task.id)}">
      <div class="task-leading">
        ${parent ? `<button class="task-disclosure" type="button" data-toggle-children="${escapeHtml(task.id)}" aria-expanded="${expanded}" aria-label="${expanded ? "Collapse" : "Expand"} ${escapeHtml(task.title)} children">${expanded ? "▾" : "▸"}</button>` : ""}
        ${completionControl}
      </div>
      <div class="task-main">
        <h3 class="task-title">${taskTextPreview(task.title, `${task.id}:title`, TASK_TITLE_PREVIEW_LENGTH, "task-title-text")}</h3>
        <p class="task-description">${taskTextPreview(detail, `${task.id}:detail`, TASK_DETAIL_PREVIEW_LENGTH, "task-detail-text")}</p>
        <p class="item-meta">${escapeHtml(taskDeadlineLabel(task))}${task.tags?.length ? ` · ${escapeHtml(task.tags.map(tagLabel).join(" · "))}` : ""}</p>
        <div class="task-actions">
          ${task.filter_context ? '<span class="item-meta">Parent context</span>' : ""}
          <button class="text-button" type="button" data-edit-task="${escapeHtml(task.id)}" aria-label="Edit ${escapeHtml(task.title)}">Edit</button>
          ${!child ? `<button class="text-button" type="button" data-add-child="${escapeHtml(task.id)}">Add child</button>` : ""}
          ${child ? `<span class="reorder-controls" aria-label="Reorder ${escapeHtml(task.title)}"><button type="button" data-move-task="up" data-task-id="${escapeHtml(task.id)}" ${position === 0 ? "disabled" : ""} aria-label="Move ${escapeHtml(task.title)} up">↑</button><button type="button" data-move-task="down" data-task-id="${escapeHtml(task.id)}" ${position === siblingCount - 1 ? "disabled" : ""} aria-label="Move ${escapeHtml(task.title)} down">↓</button></span>` : ""}
        </div>
      </div>
      <div class="task-state">${parent ? `<span class="task-progress">${escapeHtml(progressLabel)}</span>` : ""}${(task.ready_to_close || task.progress?.ready_to_close) ? '<span class="ready-to-close">Ready to close</span>' : ""}<span class="state-badge ${badgeClass}">${escapeHtml(task.blocked ? "blocked" : task.state)}</span></div>
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
          <h3 class="task-title">${item.source?.plugin_id === "core" ? taskTextPreview(item.title, `history:${item.source.entity_id}:title`, TASK_TITLE_PREVIEW_LENGTH, "task-title-text") : entityTitle(item)}</h3>
          <span class="state-badge">${escapeHtml(item.state)}</span>
        </div>
        <p class="task-description">${item.source?.plugin_id === "core" ? taskTextPreview(item.detail || "No additional detail", `history:${item.source.entity_id}:detail`, TASK_DETAIL_PREVIEW_LENGTH, "task-detail-text") : escapeHtml(item.detail || "No additional detail")}</p>
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

function wireCommandButtons(root = document) {
  root.querySelectorAll("button[data-command]:not([data-activity-command])").forEach((button) => {
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
  if (source.plugin_id === "core" && source.entity_type === "task") {
    if (!dashboard?.tasks?.some((item) => item.id === source.entity_id)) { showNotice("This linked task is not in the current snapshot.", "warning"); return; }
    openTaskEditor(source.entity_id);
    return;
  }
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
  const form = event.currentTarget;
  const input = document.querySelector("#quick-add-title");
  const title = input.value.trim();
  if (!title) return;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const metadata = readTaskMetadata(form, "create");
    await request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ title, ...metadata }),
    });
    input.value = "";
    form.reset();
    await refresh();
  } catch (error) {
    form.querySelector(".form-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

function captureTaskDraft() {
  const form = document.querySelector("#quick-add-form");
  if (!form) return null;
  return {
    fields: [...(form.querySelectorAll?.("input, select") || [])].map((input) => ({ id: input.id, name: input.name, value: input.value, checked: input.checked })),
    expanded: Boolean(form.querySelector?.(".task-options")?.open),
  };
}

function restoreTaskDraft(draft) {
  const form = document.querySelector("#quick-add-form");
  if (!draft || !form) return;
  for (const saved of draft.fields) {
    const input = saved.id ? form.querySelector(`#${saved.id}`) : [...form.querySelectorAll('input[name="tags"]')].find((item) => item.value === saved.value);
    if (!input) continue;
    input.value = saved.value;
    if (input.type === "checkbox") input.checked = saved.checked;
  }
  const options = form.querySelector(".task-options");
  if (options) options.open = draft.expanded;
  const specific = form.querySelector(".specific-time-fields");
  if (specific) specific.hidden = form.querySelector('[name="deadline_mode"]').value !== "specific";
}

function taskTagCatalog() {
  return dashboard?.task_tag_catalog || [];
}

function tagLabel(id) {
  return taskTagCatalog().find((tag) => tag.id === id)?.label || id;
}

function entryTags(entry) {
  if (entry.source?.plugin_id === "core" && entry.source?.entity_type === "task") {
    return dashboard?.tasks?.find((task) => task.id === entry.source.entity_id)?.tags || [];
  }
  return taskTagCatalog().filter((tag) => (tag.plugin_ids || []).includes(entry.source?.plugin_id)).map((tag) => tag.id);
}

function matchesTags(tags, selected) {
  return !selected.length || selected.some((tag) => tags.includes(tag));
}

function tagPicker(id, selected, label = "Tags", filter = false) {
  return `<details class="tag-picker" data-tag-label="${escapeHtml(label)}"${filter && selected.length ? " open" : ""}><summary>${escapeHtml(label)}${selected.length ? ` (${selected.length})` : ""}</summary><fieldset id="${id}"><legend class="sr-only">${escapeHtml(label)}</legend>${taskTagCatalog().map((tag) => `<label><input id="${id}-${escapeHtml(tag.id)}" type="checkbox" name="tags" value="${escapeHtml(tag.id)}"${selected.includes(tag.id) ? " checked" : ""}>${escapeHtml(tag.label)}</label>`).join("")}</fieldset>${filter ? '<button class="text-button" type="button" data-clear-schedule-tags>Clear all tags</button>' : `<div class="custom-tag-row"><label for="${id}-custom">New tag</label><input id="${id}-custom" name="custom_tag" maxlength="40" placeholder="e.g. Weekend projects"><button class="secondary-button" type="button" data-add-custom-tag>Add tag</button></div><p class="tag-filter-note">Choose several tags or add a label. Matching capitalization and spacing are combined.</p>`}</details>`;
}

function selectedTags(root) {
  return [...root.querySelectorAll('input[name="tags"]:checked')].map((input) => input.value);
}

function normalizeTag(value) {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function addCustomTag(picker) {
  const input = picker.querySelector('[name="custom_tag"]');
  const label = input.value.trim().replace(/\s+/g, " ");
  const normalized = normalizeTag(label);
  if (!normalized) return;
  const existing = [...picker.querySelectorAll('input[name="tags"]')]
    .find((candidate) => normalizeTag(candidate.value) === normalized
      || normalizeTag(candidate.closest("label")?.textContent || "") === normalized);
  if (existing) {
    existing.checked = true;
  } else {
    const fieldset = picker.querySelector("fieldset");
    fieldset.insertAdjacentHTML("beforeend", `<label><input type="checkbox" name="tags" value="${escapeHtml(label)}" checked>${escapeHtml(label)}</label>`);
  }
  input.value = "";
  const count = selectedTags(picker).length;
  picker.querySelector("summary").textContent = `${picker.dataset.tagLabel} (${count})`;
}

function wallTimeParts(value, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const part = (type) => parts.find((item) => item.type === type)?.value;
  return { date: `${part("year")}-${part("month")}-${part("day")}`, time: `${part("hour")}:${part("minute")}` };
}

function buildTaskDeadline(date, time, timeZone, occurrence = "earlier") {
  if (!date) return null;
  // Validate the zone even for civil dates. End of day remains a calendar date.
  new Intl.DateTimeFormat("en", { timeZone }).format(new Date());
  if (!time) return { kind: "due-on", due_on: date, time_zone: timeZone };
  const wall = Date.parse(`${date}T${time}:00Z`);
  const matches = [];
  for (let offset = -840; offset <= 840; offset += 15) {
    const instant = wall - offset * 60000;
    const parts = wallTimeParts(instant, timeZone);
    if (parts.date === date && parts.time === time) matches.push({ instant, offset });
  }
  matches.sort((a, b) => a.instant - b.instant);
  if (!matches.length) throw new Error("That time does not exist in this timezone because the clocks change. Choose another time.");
  const match = occurrence === "later" ? matches.at(-1) : matches[0];
  const sign = match.offset < 0 ? "-" : "+";
  const minutes = Math.abs(match.offset);
  const offset = `${sign}${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return { kind: "due-at", due_at: `${date}T${time}:00${offset}`, time_zone: timeZone };
}

function taskMetadataFields(prefix, task = {}) {
  const deadline = task.deadline;
  const zone = deadline?.time_zone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const parts = deadline?.kind === "due-at" ? wallTimeParts(deadline.due_at, zone) : { date: deadline?.due_on || "", time: "" };
  let later = false;
  if (deadline?.kind === "due-at") {
    later = Math.floor(new Date(buildTaskDeadline(parts.date, parts.time, zone, "earlier").due_at).valueOf() / 60000) !== Math.floor(new Date(deadline.due_at).valueOf() / 60000);
  }
  const suggested = prefix === "create"
    ? taskTagCatalog().filter((tag) => tag.suggested || tag.default_selected).map((tag) => tag.id)
    : [];
  return `<div class="task-metadata-fields"><label for="${prefix}-date">Due date (optional)<input id="${prefix}-date" name="due_date" type="date" value="${escapeHtml(parts.date)}"></label><label for="${prefix}-deadline-mode">Deadline<select id="${prefix}-deadline-mode" name="deadline_mode"><option value="end-of-day"${parts.time ? "" : " selected"}>End of day</option><option value="specific"${parts.time ? " selected" : ""}>Specific time</option></select></label><div class="specific-time-fields"${parts.time ? "" : " hidden"}><label for="${prefix}-time">Time<input id="${prefix}-time" name="due_time" type="time" value="${parts.time}"></label><label for="${prefix}-occurrence">If the clock repeats this time<select id="${prefix}-occurrence" name="occurrence"><option value="earlier"${later ? "" : " selected"}>First occurrence</option><option value="later"${later ? " selected" : ""}>Second occurrence</option></select></label></div><label for="${prefix}-zone">Timezone<input id="${prefix}-zone" name="time_zone" value="${escapeHtml(zone)}" required spellcheck="false"></label><p class="deadline-note">End of day keeps this date in the named timezone. Clear the date to remove the deadline. Deadlines do not send notifications.</p>${tagPicker(`${prefix}-tags`, task.tags || suggested)}</div>`;
}

function deadlineForTaskFields(date, time, timeZone, occurrence, original = null) {
  const next = buildTaskDeadline(date, time, timeZone, occurrence);
  if (original?.kind === "due-at" && next?.kind === "due-at" && original.time_zone === next.time_zone
      && Math.floor(new Date(original.due_at).valueOf() / 60000) === Math.floor(new Date(next.due_at).valueOf() / 60000)) {
    return original;
  }
  return next;
}

function readTaskMetadata(form, originalDeadline = null) {
  const value = (name) => form.querySelector(`[name="${name}"]`).value;
  const date = value("due_date");
  const specific = value("deadline_mode") === "specific";
  if (date && specific && !value("due_time")) throw new Error("Choose a time or select End of day.");
  return { deadline: deadlineForTaskFields(date, specific ? value("due_time") : "", value("time_zone"), value("occurrence"), originalDeadline), tags: selectedTags(form) };
}

function taskDeadlineLabel(task) {
  const deadline = task.deadline;
  if (!deadline) return "No deadline";
  if (deadline.kind === "due-on") return `Due ${deadline.due_on} · End of day (${deadline.time_zone})`;
  const parts = wallTimeParts(deadline.due_at, deadline.time_zone);
  return `Due ${parts.date} ${parts.time} (${deadline.time_zone})`;
}

function sectionTaskHierarchy(ids, sourceTasks = dashboard.tasks) {
  const matches = sourceTasks.filter((task) =>
    !["done", "canceled"].includes(task.state)
    && matchesTags(task.tags || [], ids));
  const matchedIds = new Set(matches.map((task) => task.id));
  return { matches, ...taskHierarchyForMatchedIds(matchedIds, sourceTasks) };
}

function taskHierarchyForMatchedIds(matchedIds, sourceTasks = dashboard.tasks) {
  const roots = visibleTaskRoots(sourceTasks).flatMap((task) => {
    const childMatch = taskChildren(task, sourceTasks).some(
      (child) => matchedIds.has(child.id),
    );
    return matchedIds.has(task.id) || childMatch
      ? [{ ...task, filter_context: !matchedIds.has(task.id) }]
      : [];
  });
  return {
    roots,
    tasks: [
      ...roots,
      ...sourceTasks.filter((task) => task.parent_id
        && (matchedIds.has(task.id) || matchedIds.has(task.parent_id))),
    ],
  };
}

function renderSectionTasks() {
  const ids = taskTagCatalog().filter((tag) => tag.view === activeView).map((tag) => tag.id);
  if (!ids.length) return;
  const filtered = sectionTaskHierarchy(ids);
  app.insertAdjacentHTML("beforeend", `<section class="panel section-core-tasks"><div class="panel-header"><h2>Shared tasks for ${escapeHtml(viewCopy[activeView].title)}</h2><span>${filtered.matches.length} tagged · parent context retained</span></div><div class="task-list">${filtered.roots.length ? renderTaskHierarchy(filtered.tasks, filtered.roots, true) : '<p class="empty">Tag a shared task to show it here.</p>'}</div></section>`);
  wireCommandButtons(app.querySelector(".section-core-tasks"));
  wireTaskHierarchyControls(app.querySelector(".section-core-tasks"));
  wireExpandableText(app.querySelector(".section-core-tasks"));
}

function taskParentOptions(task) {
  if (task?.progress?.total || taskChildren(task).length) return "";
  return (dashboard?.tasks || [])
    .filter((candidate) => candidate.id !== task?.id && !candidate.parent_id)
    .map((candidate) => `<option value="${escapeHtml(candidate.id)}"${task?.parent_id === candidate.id ? " selected" : ""}>${escapeHtml(candidate.title)}</option>`)
    .join("");
}

function contactFormValue(record, collection, property) {
  return contactCollectionValue(record?.[collection], property);
}

function contactKindOptions(selected = "individual") {
  const kinds = [
    ["individual", "Person"],
    ["org", "Organization"],
    ["group", "Group"],
    ["location", "Location"],
    ["device", "Device"],
    ["application", "Application"],
  ];
  if (selected && !kinds.some(([value]) => value === selected)) {
    kinds.push([selected, `Other (${selected})`]);
  }
  return kinds.map(([value, label]) => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
}

function openContactEditor(id = null) {
  editingContact = id
    ? (dashboard?.contacts || []).find((contact) => contact.source.entity_id === id)
    : null;
  if (id && !editingContact) return;
  const record = editingContact?.record || {};
  const dialog = document.querySelector("#contact-editor-dialog");
  document.querySelector("#contact-editor-content").innerHTML = `<form id="contact-edit-form" class="task-edit-form contact-edit-form">
    <div class="dialog-heading"><h2 id="contact-editor-title">${editingContact ? "Edit contact" : "Add contact"}</h2><button type="button" data-close-contact-editor aria-label="Close contact editor">×</button></div>
    <div class="contact-form-grid">
      <label class="contact-full-field" for="contact-name">Name<input id="contact-name" name="name" value="${escapeHtml(record.name?.full || "")}" maxlength="200" autofocus></label>
      <label for="contact-kind">Kind<select id="contact-kind" name="kind">${contactKindOptions(record.kind || "individual")}</select></label>
      <label for="contact-organization">Organization<input id="contact-organization" name="organization" value="${escapeHtml(contactFormValue(record, "organizations", "name"))}" maxlength="200"></label>
      <label for="contact-email">Primary email<input id="contact-email" name="email" type="email" value="${escapeHtml(contactFormValue(record, "emails", "address"))}" maxlength="320" autocomplete="email"></label>
      <label for="contact-phone">Primary phone<input id="contact-phone" name="phone" type="tel" value="${escapeHtml(contactFormValue(record, "phones", "number"))}" maxlength="80" autocomplete="tel"></label>
      <label class="contact-full-field" for="contact-address">Address<textarea id="contact-address" name="address" maxlength="500" autocomplete="street-address">${escapeHtml(contactFormValue(record, "addresses", "full"))}</textarea></label>
    </div>
    <p class="deadline-note">Mission Control keeps the complete JSContact card. Editing these primary fields preserves any additional standard or extension properties.</p>
    <p class="form-error" role="status"></p><button class="primary-button" type="submit">${editingContact ? "Save contact" : "Add contact"}</button>
  </form>`;
  document.querySelector("#contact-edit-form").addEventListener("submit", saveContact);
  dialog.showModal();
}

function updateContactCollection(record, collection, property, value, type) {
  const current = record[collection] && typeof record[collection] === "object"
    ? { ...record[collection] }
    : {};
  const key = Object.entries(current).sort((left, right) =>
    (left[1]?.pref || 101) - (right[1]?.pref || 101) || left[0].localeCompare(right[0]))[0]?.[0]
    || "primary";
  if (value) current[key] = { ...(current[key] || {}), "@type": type, [property]: value };
  else delete current[key];
  if (Object.keys(current).length) record[collection] = current;
  else delete record[collection];
}

function contactRecordFromForm(form) {
  const record = editingContact
    ? JSON.parse(JSON.stringify(editingContact.record))
    : { "@type": "Card", version: "2.0" };
  record.kind = form.elements.kind.value;
  const fullName = form.elements.name.value.trim();
  const name = { ...(record.name || {}) };
  if (fullName) name.full = fullName;
  else delete name.full;
  if (Object.keys(name).length) record.name = name;
  else delete record.name;
  updateContactCollection(record, "organizations", "name", form.elements.organization.value.trim(), "Organization");
  updateContactCollection(record, "emails", "address", form.elements.email.value.trim(), "EmailAddress");
  updateContactCollection(record, "phones", "number", form.elements.phone.value.trim(), "Phone");
  updateContactCollection(record, "addresses", "full", form.elements.address.value.trim(), "Address");
  return record;
}

async function saveContact(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    if (!form.elements.name.value.trim() && !form.elements.organization.value.trim()) {
      throw new Error("Add a name or organization.");
    }
    const editing = editingContact;
    const path = editing
      ? `/api/contacts/${encodeURIComponent(editing.source.entity_id)}`
      : "/api/contacts";
    await request(path, {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify({
        record: contactRecordFromForm(form),
        ...(editing ? { expected_revision: editing.revision } : {}),
      }),
    });
    dialogClose("#contact-editor-dialog");
    editingContact = null;
    await refresh();
    showNotice(editing ? "Contact updated." : "Contact added.");
  } catch (error) {
    form.querySelector(".form-error").textContent = error.status === 409
      ? "This contact changed. Close and reopen the editor to review the latest values."
      : error.message;
    if (error.status === 409) await refresh();
  } finally {
    submit.disabled = false;
  }
}

function dialogClose(selector) {
  const dialog = document.querySelector(selector);
  if (dialog?.open) dialog.close();
}

function openTaskEditor(id) {
  const task = dashboard?.tasks?.find((item) => item.id === id);
  if (!task) return;
  editingTask = task;
  const related = requestRecords().filter((item) => item.task_links.some((source) => source.plugin_id === "core" && source.entity_type === "task" && source.entity_id === id));
  const dialog = document.querySelector("#task-editor-dialog");
  document.querySelector("#task-editor-content").innerHTML = `<form id="task-edit-form" class="task-edit-form"><div class="dialog-heading"><h2 id="task-editor-title">Edit shared task</h2><button type="button" data-close-task-editor aria-label="Close task editor">×</button></div><label for="edit-task-title">Title<input id="edit-task-title" name="title" value="${escapeHtml(task.title)}" required maxlength="160"></label><label for="edit-task-description">Description<textarea id="edit-task-description" name="description">${escapeHtml(task.description || "")}</textarea></label><label for="edit-task-parent">Parent task<select id="edit-task-parent" name="parent_id"><option value="">No parent</option>${taskParentOptions(task)}</select></label><p class="deadline-note">Moving a task changes its presentation only; it does not create a dependency or copy dates and tags.</p>${taskMetadataFields("edit", task)}${related.length ? `<div class="related-requests"><h3>Related requests</h3>${related.map((item) => `<p><button type="button" class="entity-link" data-related-request="${escapeHtml(item.id)}">${escapeHtml(item.title)}</button> <small>${escapeHtml(item.status)}</small></p>`).join("")}</div>` : ""}<p class="form-error" role="status"></p><button class="primary-button" type="submit">Save task</button></form>`;
  document.querySelector("#task-edit-form").addEventListener("submit", saveTaskEdit);
  dialog.querySelectorAll("[data-related-request]").forEach((button) => button.addEventListener("click", () => {
    dialog.close();
    openEntityDetail({plugin_id: "open-requests", entity_type: "request", entity_id: button.dataset.relatedRequest});
  }));
  dialog.showModal();
}

async function saveTaskEdit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await request(`/api/tasks/${encodeURIComponent(editingTask.id)}`, { method: "PATCH", body: JSON.stringify({ title: form.querySelector('[name="title"]').value.trim(), description: form.querySelector('[name="description"]').value, parent_id: form.querySelector('[name="parent_id"]').value || null, ...readTaskMetadata(form, editingTask.deadline), expected_revision: editingTask.updated_at }) });
    document.querySelector("#task-editor-dialog").close();
    await refresh();
  } catch (error) {
    form.querySelector(".form-error").textContent = error.status === 409 ? "This task changed. Close and reopen the editor to review current values before saving." : error.message;
    if (error.status === 409) await refresh();
  } finally {
    submit.disabled = false;
  }
}

function openAddChildEditor(parentId) {
  const parent = dashboard?.tasks?.find((task) => task.id === parentId);
  if (!parent) return;
  const dialog = document.querySelector("#task-editor-dialog");
  document.querySelector("#task-editor-content").innerHTML = `<form id="task-child-form" class="task-edit-form" data-parent-id="${escapeHtml(parentId)}"><div class="dialog-heading"><h2 id="task-editor-title">Add child to ${escapeHtml(parent.title)}</h2><button type="button" data-close-task-editor aria-label="Close child task editor">×</button></div><label for="child-task-title">Title<input id="child-task-title" name="title" required maxlength="160" autofocus></label><label for="child-task-description">Description<textarea id="child-task-description" name="description"></textarea></label><p class="deadline-note">This child keeps its own status, dates, and tags. Nothing is inherited from its parent.</p>${taskMetadataFields("child")}<p class="form-error" role="status"></p><button class="primary-button" type="submit">Add child</button></form>`;
  document.querySelector("#task-child-form").addEventListener("submit", addChildTask);
  dialog.showModal();
}

async function addChildTask(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await request("/api/tasks", { method: "POST", body: JSON.stringify({ title: form.querySelector('[name="title"]').value.trim(), description: form.querySelector('[name="description"]').value, parent_id: form.dataset.parentId, ...readTaskMetadata(form) }) });
    expandedParents.add(form.dataset.parentId);
    document.querySelector("#task-editor-dialog").close();
    await refresh();
  } catch (error) {
    form.querySelector(".form-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const edit = event.target.closest?.("[data-edit-task]");
  if (edit) openTaskEditor(edit.dataset.editTask);
  const addChild = event.target.closest?.("[data-add-child]");
  if (addChild) openAddChildEditor(addChild.dataset.addChild);
  const customTag = event.target.closest?.("[data-add-custom-tag]");
  if (customTag) addCustomTag(customTag.closest(".tag-picker"));
  if (event.target.closest?.("[data-close-task-editor]")) document.querySelector("#task-editor-dialog").close();
  if (event.target.closest?.("[data-close-contact-editor]")) {
    editingContact = null;
    dialogClose("#contact-editor-dialog");
  }
});
document.addEventListener("change", (event) => {
  if (event.target.name === "tags") {
    const picker = event.target.closest(".tag-picker");
    const count = selectedTags(picker).length;
    picker.querySelector("summary").textContent = `${picker.dataset.tagLabel}${count ? ` (${count})` : ""}`;
  }
  if (event.target.name === "deadline_mode") {
    const form = event.target.closest("form");
    form.querySelector(".specific-time-fields").hidden = event.target.value !== "specific";
  }
});

function wireExpandableText(root = document) {
  root.querySelectorAll("[data-expand-text]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.expandText;
      const expanded = button.getAttribute("aria-expanded") === "true";
      if (expanded) expandedTaskText.delete(key);
      else expandedTaskText.add(key);
      button.setAttribute("aria-expanded", String(!expanded));
      button.setAttribute("aria-label", `${expanded ? "Expand" : "Collapse"} full text`);
      button.querySelector(".text-preview").hidden = !expanded;
      button.querySelector(".text-full").hidden = expanded;
    });
  });
}

function wireTaskHierarchyControls(root = document) {
  root.querySelectorAll("[data-toggle-children]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.toggleChildren;
      if (expandedParents.has(id)) expandedParents.delete(id);
      else expandedParents.add(id);
      render();
    });
  });
  root.querySelectorAll("[data-move-task]").forEach((button) => {
    button.addEventListener("click", () => moveTaskSibling(button.dataset.taskId, button.dataset.moveTask));
  });
  root.querySelectorAll("[data-show-unfinished]").forEach((button) => {
    button.addEventListener("click", () => {
      expandedParents.add(button.dataset.showUnfinished);
      render();
      showNotice("Finish or cancel the remaining child tasks before completing this parent.", "warning");
    });
  });
  root.querySelectorAll(".task-row.is-child").forEach((row) => {
    row.tabIndex = 0;
    row.addEventListener("keydown", (event) => {
      if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      moveTaskSibling(row.dataset.taskId, event.key === "ArrowUp" ? "up" : "down");
    });
  });
}

async function moveTaskSibling(id, direction) {
  const task = dashboard?.tasks?.find((candidate) => candidate.id === id);
  if (!task?.parent_id) return;
  const siblings = taskChildren({ id: task.parent_id });
  const index = siblings.findIndex((candidate) => candidate.id === id);
  const targetIndex = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || targetIndex < 0 || targetIndex >= siblings.length) return;
  try {
    await request(`/api/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ sibling_order: targetIndex, expected_revision: task.updated_at }),
    });
    await refresh();
    document.querySelector(`[data-task-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
  } catch (error) {
    showNotice(error.status === 409 ? "Task order changed elsewhere. The current order was refreshed." : error.message, "warning");
    if (error.status === 409) await refresh();
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
  const pane = event.target.closest?.("[data-pane], [data-mobile-pane]");
  if (pane) setActivePane(pane.dataset.pane || pane.dataset.mobilePane, false);
  if (event.target.closest?.("#app")) inspectElement(event.target);
});

const paneOrder = ["navigator", "queue", "inspector"];
let activePane = "navigator";
let jumpState = null;
let openDrawer = null;
let lastDrawerTrigger = null;
let wasNarrowLayout = isNarrowLayout();
const desktopPaneVisibility = { navigator: true, inspector: true };
const focusHistory = [];
const helpDialog = document.querySelector("#help-dialog");
const jumpLayer = document.querySelector("#jump-layer");
const keyboardAnnouncer = document.querySelector("#keyboard-announcer");
const keyboardModeLabel = document.querySelector("#keyboard-mode-label");
const focusableSelector = "button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";

function isTypingTarget(target) {
  return Boolean(target?.matches?.("input, textarea, select, [contenteditable='true']"));
}

function isNarrowViewport(width) {
  return Number(width) <= 680;
}

function isNarrowLayout() {
  return narrowLayoutQuery?.matches ?? isNarrowViewport(window.innerWidth || 1024);
}

function paneToggleForKey(key) {
  return ({ "[": "navigator", "]": "inspector" })[key] || null;
}

function toggledPaneVisibility(visibility, name) {
  return { ...visibility, [name]: !visibility[name] };
}

function nextDrawerState(current, name) {
  return current === name ? null : name;
}

function drawerStateAfterResize(current, previousNarrow, nextNarrow) {
  return previousNarrow === nextNarrow ? current : null;
}

function paneIsVisible(name) {
  if (name === "queue") return true;
  if (isNarrowLayout()) return name === "navigator" || openDrawer === name;
  return desktopPaneVisibility[name];
}

function visiblePaneOrder() {
  return paneOrder.filter(paneIsVisible);
}

function fallbackPaneName(name, visibleNames) {
  return visibleNames.includes(name) ? name : "queue";
}

function syncPaneLayout() {
  if (!workspace) return;
  const narrow = isNarrowLayout();
  const navigatorVisible = !narrow && desktopPaneVisibility.navigator;
  const inspectorVisible = narrow ? openDrawer === "inspector" : desktopPaneVisibility.inspector;
  workspace.classList.toggle("is-navigator-hidden", !navigatorVisible);
  workspace.classList.toggle("is-inspector-hidden", !inspectorVisible);
  workspace.classList.toggle("is-inspector-drawer-open", narrow && inspectorVisible);
  document.querySelectorAll("[data-toggle-pane]").forEach((button) => {
    const visible = button.dataset.togglePane === "navigator"
      ? (narrow || navigatorVisible)
      : inspectorVisible;
    button.setAttribute("aria-expanded", String(visible));
    button.setAttribute("aria-label", `${visible ? "Hide" : "Show"} ${button.dataset.togglePane === "navigator" ? "sections" : "inspector"}`);
  });
  if (drawerBackdrop) drawerBackdrop.hidden = !(narrow && openDrawer);
  const nextActivePane = fallbackPaneName(activePane, visiblePaneOrder());
  if (nextActivePane !== activePane) setActivePane(nextActivePane, false);
}

function revealPane(name) {
  if (name === "queue") return;
  if (isNarrowLayout()) {
    if (name === "inspector") {
      openDrawer = name;
      lastDrawerTrigger = document.querySelector("#inspector-toggle");
    }
  } else desktopPaneVisibility[name] = true;
  syncPaneLayout();
}

function togglePane(name, trigger = document.querySelector(`[data-toggle-pane="${name}"]`)) {
  const wasVisible = paneIsVisible(name);
  if (isNarrowLayout()) {
    if (name === "navigator") {
      setActivePane("navigator");
      return;
    }
    openDrawer = nextDrawerState(openDrawer, "inspector");
    if (openDrawer) lastDrawerTrigger = trigger;
  } else {
    Object.assign(desktopPaneVisibility, toggledPaneVisibility(desktopPaneVisibility, name));
  }
  syncPaneLayout();
  if (wasVisible && !paneIsVisible(name)) trigger?.focus?.({ preventScroll: true });
  else if (!wasVisible && paneIsVisible(name) && !isNarrowLayout()) setActivePane(name);
}

function closeDrawers(restoreFocus = true) {
  if (!openDrawer) return false;
  openDrawer = null;
  syncPaneLayout();
  if (restoreFocus) lastDrawerTrigger?.focus?.({ preventScroll: true });
  return true;
}

function handleLayoutResize() {
  const focusedPane = document.activeElement?.closest?.("[data-pane], [data-mobile-pane]");
  const narrow = isNarrowLayout();
  openDrawer = drawerStateAfterResize(openDrawer, wasNarrowLayout, narrow);
  wasNarrowLayout = narrow;
  syncPaneLayout();
  if (focusedPane && focusedPane !== paneElement(focusedPane.dataset.pane || focusedPane.dataset.mobilePane)) {
    setActivePane("queue");
  }
}

function paneForKey(key) {
  return ({ s: "navigator", d: "queue", f: "inspector" })[key.toLowerCase()] || null;
}

function movementForKey(key) {
  return ({ ArrowLeft: "left", h: "left", ArrowRight: "right", l: "right", ArrowUp: "up", k: "up", ArrowDown: "down", j: "down" })[key] || null;
}

function cycledPaneName(name, delta) {
  const panes = visiblePaneOrder();
  const current = Math.max(0, panes.indexOf(name));
  return panes[(current + delta + panes.length) % panes.length];
}

function paneElement(name) {
  if (name === "navigator" && isNarrowLayout()) return mobileSectionTabs;
  return document.querySelector(`[data-pane="${name}"]`);
}

function visibleFocusable(pane) {
  return [...pane.querySelectorAll(focusableSelector)].filter((item) => {
    if (item.closest("[hidden]")) return false;
    return !item.hasAttribute("disabled") && item.getAttribute("aria-hidden") !== "true";
  });
}

function setActivePane(name, moveFocus = true) {
  if (!paneIsVisible(name)) revealPane(name);
  const pane = paneElement(name);
  if (!pane) return;
  activePane = name;
  document.querySelectorAll("[data-pane], [data-mobile-pane]").forEach((item) => {
    item.classList.toggle("is-keyboard-active", item === pane);
  });
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
  const panes = visiblePaneOrder();
  const current = panes.indexOf(activePane);
  const next = Math.max(0, Math.min(panes.length - 1, current + delta));
  if (next === current) {
    announce(`${activePane} pane boundary`);
    return;
  }
  setActivePane(panes[next]);
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
    ["[ / ]", "Toggle the Sections or Inspector sidebar"],
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
  if (document.querySelector("#request-editor-dialog")?.open) { closeRequestEditor(); return; }
  const contactDialog = document.querySelector("#contact-editor-dialog");
  if (contactDialog?.open) {
    editingContact = null;
    contactDialog.close();
    return;
  }
  const taskDialog = document.querySelector("#task-editor-dialog");
  if (taskDialog?.open) {
    taskDialog.close();
    return;
  }
  if (jumpState) return cancelJump();
  if (helpDialog?.open) {
    helpDialog.close();
    keyboardModeLabel.textContent = "NAV";
    return;
  }
  if (closeDrawers()) return;
  if (entityDetail) {
    showView(detailReturnView);
    return;
  }
  const prior = focusHistory.pop();
  if (prior?.isConnected) prior.focus({ preventScroll: true });
  else setActivePane("navigator");
}

document.querySelector("#request-editor-dialog")?.addEventListener("cancel", (event) => { event.preventDefault(); closeRequestEditor(); });

document.querySelector("#help-button")?.addEventListener("click", openHelp);
helpDialog?.addEventListener("close", () => { keyboardModeLabel.textContent = "NAV"; });
document.querySelectorAll("[data-toggle-pane]").forEach((button) => {
  button.addEventListener("click", () => togglePane(button.dataset.togglePane, button));
});
drawerBackdrop?.addEventListener("click", () => closeDrawers());
narrowLayoutQuery?.addEventListener?.("change", handleLayoutResize);
window.addEventListener?.("resize", handleLayoutResize);
syncPaneLayout();

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    handleEscape();
    return;
  }
  if (document.querySelector("#request-editor-dialog")?.open || helpDialog?.open || document.querySelector("#task-editor-dialog")?.open || document.querySelector("#contact-editor-dialog")?.open || isTypingTarget(event.target)) return;
  const toggledPane = paneToggleForKey(event.key);
  if (toggledPane && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    togglePane(toggledPane);
    return;
  }
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
  if (event.key === "Tab" && document.activeElement?.closest?.("[data-pane], [data-mobile-pane]")) {
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
