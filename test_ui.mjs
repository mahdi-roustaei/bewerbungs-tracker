import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const script = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const sample = {
  id: 1,
  company: "Example",
  role: "Backend",
  status: "applied",
  location: "Hannover",
  applied_on: "2026-10-01",
  follow_up_on: null,
  notes: "",
  job_url: null,
  archived: false,
};
const settle = async () => {
  for (let i = 0; i < 12; i++)
    await new Promise((resolve) => setImmediate(resolve));
};

async function setup(rows = [], fail = false) {
  const dom = new JSDOM(html, {
    url: "http://localhost:8000",
    runScripts: "outside-only",
  });
  const { window: w } = dom;
  const calls = [];
  w.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  w.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  w.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (fail) throw new Error("network");
    let body;
    if (options.method === "POST") {
      body = { ...JSON.parse(options.body), id: 2, archived: false };
      rows.push(body);
    } else if (options.method === "PUT") {
      body = { ...rows[0], ...JSON.parse(options.body) };
      rows[0] = body;
    } else if (options.method === "PATCH") {
      Object.assign(rows[0], JSON.parse(options.body));
      body = rows[0];
    } else if (url === "/api/stats")
      body = {
        total: rows.length,
        by_status: { interview: 0, offer: 0 },
        follow_ups_due: 0,
      };
    else if (url.endsWith("/history"))
      body = [
        {
          status: "applied",
          previous_status: null,
          changed_at: "2026-10-01T12:00:00Z",
        },
      ];
    else
      body = rows.filter(
        (r) =>
          r.archived ===
          new URL(url, "http://localhost:8000").searchParams
            .get("archived")
            ?.includes("true"),
      );
    return { ok: true, json: async () => body };
  };
  w.eval(script);
  await settle();
  return { dom, w, calls, rows, $: (id) => w.document.getElementById(id) };
}

test("empty state and stats render without a JavaScript framework", async () => {
  const x = await setup();
  try {
    assert.equal(x.$("empty").hidden, false);
    assert.equal(x.$("stat-total").textContent, "0");
  } finally {
    x.dom.window.close();
  }
});

test("untrusted company names remain text, never HTML", async () => {
  const x = await setup([
    { ...sample, company: "<img src=x onerror=alert(1)>" },
  ]);
  try {
    assert.equal(x.$("applications").querySelector("img"), null);
    assert.match(x.$("applications").textContent, /<img/);
  } finally {
    x.dom.window.close();
  }
});

test("form creates an application and turns blank optional fields into null", async () => {
  const x = await setup();
  try {
    x.$("new-application").click();
    const form = x.$("application-form");
    form.elements.company.value = "New Company";
    form.elements.role.value = "Student";
    form.dispatchEvent(
      new x.w.Event("submit", { bubbles: true, cancelable: true }),
    );
    await settle();
    const call = x.calls.find((c) => c.options.method === "POST");
    assert.equal(JSON.parse(call.options.body).job_url, null);
    assert.equal(call.options.headers["X-Requested-With"], "BewerbungsTracker");
    assert.equal(x.$("editor").open, false);
    assert.match(x.$("applications").textContent, /New Company/);
  } finally {
    x.dom.window.close();
  }
});

test("editing, history, archive and restore remain accessible", async () => {
  const x = await setup([{ ...sample }]);
  try {
    x.$("applications").querySelector("button").click();
    await settle();
    assert.match(x.$("history").textContent, /Beworben/);
    const form = x.$("application-form");
    form.elements.status.value = "interview";
    form.dispatchEvent(new x.w.Event("submit", { cancelable: true }));
    await settle();
    assert.match(x.$("applications").textContent, /Im Gespräch/);
    x.$("applications").querySelector("button").click();
    await settle();
    x.$("archive-button").click();
    await settle();
    assert.equal(x.$("applications").children.length, 0);
    x.$("view-archive").click();
    await settle();
    x.$("applications").querySelector("button").click();
    await settle();
    assert.equal(x.$("archive-button").textContent, "Wiederherstellen");
    x.$("archive-button").click();
    await settle();
    x.$("view-active").click();
    await settle();
    assert.equal(x.$("applications").children.length, 1);
  } finally {
    x.dom.window.close();
  }
});

test("network errors produce a visible actionable message", async () => {
  const x = await setup([], true);
  try {
    assert.equal(x.$("error").hidden, false);
    assert.match(x.$("error").textContent, /Verbindung unterbrochen/);
  } finally {
    x.dom.window.close();
  }
});
