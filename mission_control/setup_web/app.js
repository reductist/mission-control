const statusNode = document.getElementById("status");
const contentNode = document.getElementById("content");
const titleNode = document.getElementById("step-title");
const descriptionNode = document.getElementById("step-description");
const progressNode = document.getElementById("progress");
const noticeNode = document.getElementById("notice");
const fieldsNode = document.getElementById("fields");
const actionsNode = document.getElementById("actions");
const formNode = document.getElementById("setup-form");

let sessionToken = sessionStorage.getItem("mission-control-setup-session");
let currentState = null;

function textElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  const response = await fetch(path, {...options, headers});
  const document = await response.json();
  if (!response.ok) throw new Error(document.error?.detail || "Setup request failed.");
  return document;
}

async function claim() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token");
  if (token) {
    history.replaceState(null, "", window.location.pathname);
    const claimed = await request("/api/claim", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token}),
    });
    sessionToken = claimed.session_token;
    sessionStorage.setItem("mission-control-setup-session", sessionToken);
    return;
  }
  if (sessionToken) return;
  if (!token) throw new Error("This setup invitation is missing or has already been used.");
}

function renderField(field) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const label = textElement("label", "field-label", field.label);
  label.htmlFor = `field-${field.id}`;
  wrapper.append(label);
  if (field.description) wrapper.append(textElement("span", "field-help", field.description));

  let input;
  if (field.widget === "select" || field.widget === "multi-select") {
    input = document.createElement("select");
    input.multiple = field.widget === "multi-select";
    for (const option of field.options || []) {
      const node = document.createElement("option");
      node.value = option.id;
      node.textContent = option.label;
      if (field.widget === "multi-select" && (field.value || []).includes(option.id)) node.selected = true;
      if (field.widget === "select" && field.value === option.id) node.selected = true;
      input.append(node);
    }
  } else {
    input = document.createElement("input");
    input.type = field.widget === "credential-file" ? "file" : field.widget === "checkbox" ? "checkbox" : "text";
    if (field.widget === "checkbox") input.checked = field.value === true;
    else if (field.widget !== "credential-file" && field.value !== undefined) input.value = field.value;
  }
  input.id = `field-${field.id}`;
  input.dataset.fieldId = field.id;
  input.dataset.widget = field.widget;
  input.required = field.required === true;
  wrapper.append(input);
  fieldsNode.append(wrapper);
}

function render(state) {
  currentState = state;
  statusNode.hidden = true;
  contentNode.hidden = false;
  progressNode.textContent = state.complete ? "Complete" : "Guided integration setup";
  titleNode.textContent = state.step.title;
  descriptionNode.textContent = state.step.description || "";
  noticeNode.hidden = !state.notice;
  noticeNode.className = `notice ${state.notice?.kind || ""}`;
  noticeNode.textContent = state.notice?.detail || "";
  fieldsNode.replaceChildren();
  actionsNode.replaceChildren();
  for (const field of state.step.fields) renderField(field);
  for (const action of state.step.actions) {
    const button = document.createElement("button");
    button.type = "submit";
    button.className = action.style;
    button.textContent = action.label;
    button.dataset.actionId = action.id;
    button.dataset.intent = action.intent;
    if (action.intent === "back") button.formNoValidate = true;
    actionsNode.append(button);
  }
  if (state.complete) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary";
    button.textContent = "Save configuration";
    button.addEventListener("click", commit);
    actionsNode.append(button);
  }
}

async function fieldValues(intent) {
  if (intent === "back") return {};
  const values = {};
  for (const input of fieldsNode.querySelectorAll("[data-field-id]")) {
    const id = input.dataset.fieldId;
    const widget = input.dataset.widget;
    if (widget === "credential-file") {
      if (!input.files.length) continue;
      statusNode.hidden = false;
      statusNode.textContent = "Checking credential…";
      const uploaded = await request("/api/credential", {
        method: "POST",
        headers: {"Content-Type": "application/octet-stream"},
        body: input.files[0],
      });
      values[id] = uploaded.handle;
    } else if (widget === "checkbox") {
      values[id] = input.checked;
    } else if (widget === "multi-select") {
      values[id] = [...input.selectedOptions].map(option => option.value);
    } else if (input.value !== "" || input.required || intent !== "back") {
      values[id] = input.value;
    }
  }
  return values;
}

formNode.addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  if (!button) return;
  try {
    setBusy(true, "Working…");
    const values = await fieldValues(button.dataset.intent);
    const state = await request("/api/action", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        action_id: button.dataset.actionId,
        expected_revision: currentState.revision,
        values,
      }),
    });
    render(state);
  } catch (error) {
    setBusy(false, error.message);
  }
});

async function commit() {
  try {
    setBusy(true, "Validating and saving…");
    const result = await request("/api/commit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({expected_revision: currentState.revision}),
    });
    sessionStorage.removeItem("mission-control-setup-session");
    contentNode.hidden = true;
    statusNode.hidden = false;
    statusNode.textContent = result.restart_required
      ? "Saved. Restart Mission Control when you are ready to use this connection."
      : "Saved.";
  } catch (error) {
    setBusy(false, error.message);
  }
}

function setBusy(busy, message) {
  statusNode.hidden = false;
  statusNode.textContent = message;
  for (const button of actionsNode.querySelectorAll("button")) button.disabled = busy;
}

(async () => {
  try {
    await claim();
    render(await request("/api/state", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}));
  } catch (error) {
    statusNode.textContent = error.message;
  }
})();
