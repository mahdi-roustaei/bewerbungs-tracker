/* Plain JavaScript, no build step. All untrusted text is rendered via textContent. */
"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  saved: "Vorgemerkt",
  applied: "Beworben",
  interview: "Im Gespräch",
  offer: "Zusage",
  rejected: "Absage",
  withdrawn: "Zurückgezogen",
};
const form = $("application-form");
let records = [],
  selected = null,
  view = "active",
  generation = 0,
  busy = false;
let searchTimer, toastTimer;
const localISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const displayDate = (value) =>
  value
    ? new Date(value + "T12:00:00").toLocaleDateString("de-DE", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function showError(id, text) {
  $(id).textContent = text;
  $(id).hidden = !text;
}
function notify(text) {
  clearTimeout(toastTimer);
  $("toast").textContent = text;
  $("toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 4500);
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "BewerbungsTracker",
        ...options.headers,
      },
    });
  } catch {
    throw new Error(
      "Verbindung unterbrochen. Prüfe, ob der Tracker läuft, und versuche es erneut.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 422)
      throw new Error(
        "Bitte prüfe deine Angaben: gültige Daten, http(s)-Link und ausgefüllte Pflichtfelder.",
      );
    throw new Error(
      response.status === 404
        ? "Diese Bewerbung wurde nicht gefunden."
        : typeof body.detail === "string"
          ? body.detail
          : "Die Anfrage konnte nicht verarbeitet werden.",
    );
  }
  return response.json();
}
function render() {
  const tbody = $("applications");
  tbody.replaceChildren();
  for (const item of records) {
    const row = element("tr"),
      company = element("td"),
      cell = element("div", undefined, "company-cell");
    cell.append(
      element("span", item.company.slice(0, 2).toUpperCase(), "avatar"),
    );
    const title = element("div");
    title.append(
      element("span", item.company, "company-name"),
      element(
        "span",
        `${item.role}${item.location ? " · " + item.location : ""}`,
        "role-name",
      ),
    );
    cell.append(title);
    company.append(cell);
    const status = element("td");
    status.append(element("span", labels[item.status], "badge " + item.status));
    const due =
      item.follow_up_on &&
      item.follow_up_on <= localISO() &&
      ["saved", "applied", "interview"].includes(item.status);
    const actions = element("td"),
      edit = element("button", "↗", "edit-button");
    edit.type = "button";
    edit.setAttribute("aria-label", `${item.company}: ${item.role} bearbeiten`);
    edit.addEventListener("click", () => openEditor(item));
    actions.append(edit);
    row.append(
      company,
      status,
      element("td", displayDate(item.applied_on), "date-muted"),
      element(
        "td",
        displayDate(item.follow_up_on),
        due ? "due-date" : "date-muted",
      ),
      actions,
    );
    tbody.append(row);
  }
  $("empty").hidden = records.length > 0;
  const filtered =
    $("search").value || $("status-filter").value || view !== "active";
  $("empty-message").textContent = filtered
    ? "Hier gibt es noch keine Einträge. Passe deine Filter an oder lege eine neue Bewerbung an."
    : "Lege deine erste Bewerbung an und behalte alles im Blick.";
  $("empty-create").hidden = Boolean(filtered);
  $("result-count").textContent =
    `${records.length} ${records.length === 1 ? "Bewerbung" : "Bewerbungen"} angezeigt`;
}
async function load() {
  const current = ++generation;
  const params = new URLSearchParams({
    q: $("search").value,
    archived: String(view === "archive"),
    due: String(view === "due"),
  });
  if ($("status-filter").value) params.set("status", $("status-filter").value);
  try {
    const [items, stats] = await Promise.all([
      api("/api/applications?" + params),
      api("/api/stats"),
    ]);
    if (current !== generation) return;
    records = items;
    render();
    showError("error", "");
    $("stat-total").textContent = stats.total;
    $("nav-count").textContent = stats.total;
    $("stat-interview").textContent = stats.by_status.interview;
    $("stat-offer").textContent = stats.by_status.offer;
    $("stat-due").textContent = stats.follow_ups_due;
  } catch (error) {
    if (current === generation) {
      showError("error", error.message);
      $("result-count").textContent =
        "Daten konnten nicht aktualisiert werden.";
    }
  }
}
async function openEditor(item = null) {
  selected = item;
  form.reset();
  showError("form-error", "");
  $("history").replaceChildren();
  $("dialog-title").textContent = item
    ? "Bewerbung bearbeiten"
    : "Neue Bewerbung";
  $("archive-button").hidden = !item;
  $("archive-button").textContent = item?.archived
    ? "Wiederherstellen"
    : "Archivieren";
  $("history-section").hidden = !item;
  if (item)
    for (const name of [
      "company",
      "role",
      "location",
      "status",
      "applied_on",
      "follow_up_on",
      "job_url",
      "notes",
    ])
      form.elements.namedItem(name).value = item[name] || "";
  $("editor").showModal();
  form.elements.namedItem("company").focus();
  if (item) {
    try {
      const history = await api(`/api/applications/${item.id}/history`);
      if (selected?.id !== item.id || !$("editor").open) return;
      for (const entry of history)
        $("history").append(
          element(
            "li",
            `${new Date(entry.changed_at).toLocaleString("de-DE")} · ${entry.previous_status ? labels[entry.previous_status] + " → " : "Erstellt: "}${labels[entry.status]}`,
          ),
        );
    } catch (error) {
      if (selected?.id === item.id) showError("form-error", error.message);
    }
  }
}
function setBusy(value) {
  busy = value;
  for (const id of [
    "save-button",
    "archive-button",
    "cancel-dialog",
    "close-dialog",
  ])
    $(id).disabled = value;
  $("save-button").textContent = value ? "Wird gespeichert …" : "Speichern";
}
function closeEditor() {
  if (!busy) {
    $("editor").close();
    selected = null;
  }
}
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  for (const key of ["job_url", "applied_on", "follow_up_on"])
    if (!data[key]) data[key] = null;
  const editing = selected;
  setBusy(true);
  showError("form-error", "");
  try {
    await api(
      editing ? `/api/applications/${editing.id}` : "/api/applications",
      { method: editing ? "PUT" : "POST", body: JSON.stringify(data) },
    );
    $("editor").close();
    selected = null;
    notify(
      editing
        ? "Änderungen gespeichert."
        : "Neue Bewerbung gespeichert. Viel Erfolg!",
    );
    await load();
  } catch (error) {
    showError("form-error", error.message);
  } finally {
    setBusy(false);
  }
});
$("archive-button").addEventListener("click", async () => {
  if (!selected || busy) return;
  const item = selected;
  setBusy(true);
  try {
    await api(`/api/applications/${item.id}/archive`, {
      method: "PATCH",
      body: JSON.stringify({ archived: !item.archived }),
    });
    $("editor").close();
    selected = null;
    notify(
      item.archived
        ? "Bewerbung wiederhergestellt."
        : "Bewerbung archiviert. Im Archiv jederzeit wiederherstellbar.",
    );
    await load();
  } catch (error) {
    showError("form-error", error.message);
  } finally {
    setBusy(false);
  }
});
$("editor").addEventListener("cancel", (event) => {
  if (busy) event.preventDefault();
  else selected = null;
});
for (const id of ["close-dialog", "cancel-dialog"])
  $(id).addEventListener("click", closeEditor);
for (const id of ["new-application", "empty-create"])
  $(id).addEventListener("click", () => openEditor());
for (const name of ["active", "due", "archive"])
  $("view-" + name).addEventListener("click", () => {
    view = name;
    for (const n of ["active", "due", "archive"]) {
      $("view-" + n).classList.toggle("active", n === name);
      if (n === name) $("view-" + n).setAttribute("aria-current", "page");
      else $("view-" + n).removeAttribute("aria-current");
    }
    $("page-title").textContent = {
      active: "Deine Bewerbungen.",
      due: "Dein nächster Schritt.",
      archive: "Dein Archiv.",
    }[name];
    $("page-subtitle").textContent = {
      active: "Von der ersten Idee bis zur Zusage.",
      due: "Offene Bewerbungen mit fälliger Wiedervorlage.",
      archive: "Abgelegte Chancen. Jederzeit wiederherstellbar.",
    }[name];
    $("list-title").textContent = {
      active: "Deine Chancen",
      due: "Jetzt nachfassen",
      archive: "Archivierte Bewerbungen",
    }[name];
    load();
  });
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(load, 200);
});
$("status-filter").addEventListener("change", load);
$("today").textContent = new Date().toLocaleDateString("de-DE", {
  day: "numeric",
  month: "long",
  year: "numeric",
});
load();
