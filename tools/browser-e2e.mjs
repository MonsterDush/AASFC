import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const frontendBase = String(
  process.env.E2E_FRONTEND_BASE || "http://127.0.0.1:8765",
).replace(/\/+$/, "");
const apiBase = String(
  process.env.E2E_API_BASE || "http://127.0.0.1:9001",
).replace(/\/+$/, "");
const ownerPhone = process.env.E2E_OWNER_PHONE || "+79990000001";
const staffPhone = process.env.E2E_STAFF_PHONE || "+79990000002";
const password = process.env.E2E_PASSWORD || "AxelioE2E123!";
const venueName = process.env.E2E_VENUE_NAME || "Axelio E2E Lounge";
const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const axeSource = fs.readFileSync(
  path.join(repoRoot, "node_modules/axe-core/axe.min.js"),
  "utf8",
);
const performanceBudgets = JSON.parse(
  fs.readFileSync(
    path.join(repoRoot, "tools/performance-budgets.json"),
    "utf8",
  ),
);
const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 375, height: 812 },
];
const expectedScenarios = [
  "owner-auth",
  "owner-venues",
  "owner-summary",
  "owner-expenses",
  "owner-payroll",
  "owner-settings",
  "owner-positions",
  "owner-day-economics",
  "staff-auth",
  "staff-shifts",
  "staff-salary",
  "public-demo-readonly",
];

function browserExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  if (!executable) {
    throw new Error(
      `Chrome executable not found; checked: ${candidates.join(", ")}`,
    );
  }
  return executable;
}

function attachDiagnostics(page, label) {
  const pageErrors = [];
  const consoleErrors = [];
  const serverErrors = [];
  page.on("pageerror", (error) =>
    pageErrors.push(String(error?.message || error)),
  );
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.url().startsWith(apiBase) && response.status() >= 500) {
      serverErrors.push(
        `${response.status()} ${response.request().method()} ${response.url()}`,
      );
    }
  });
  return () => {
    assert.deepEqual(pageErrors, [], `${label}: uncaught page errors`);
    assert.deepEqual(serverErrors, [], `${label}: API 5xx responses`);
    const relevantConsoleErrors = consoleErrors.filter(
      (message) =>
        !message.includes("Failed to load resource") &&
        !message.includes("telegram.org"),
    );
    assert.deepEqual(relevantConsoleErrors, [], `${label}: console errors`);
  };
}

async function apiJson(page, path, options = {}) {
  return page.evaluate(
    async ({ url, requestOptions }) => {
      const response = await fetch(url, {
        credentials: "include",
        ...requestOptions,
        headers: {
          "Content-Type": "application/json",
          ...(requestOptions.headers || {}),
        },
      });
      const text = await response.text();
      let body;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      return { status: response.status, body };
    },
    { url: `${apiBase}${path}`, requestOptions: options },
  );
}

async function login(page, { phone, role, auditAuth = false }) {
  const nextPath = "/app-venues.html";
  await page.goto(
    `${frontendBase}/auth.html?next=${encodeURIComponent(nextPath)}`,
    {
      waitUntil: "domcontentloaded",
    },
  );
  const authQuality = auditAuth
    ? await assertPageQuality(page, "auth", `${role.toLowerCase()}-auth`)
    : null;
  await page.locator("#loginPhoneInput").fill(phone);
  await page.locator("#loginPasswordInput").fill(password);
  await page.locator("#btnPasswordLogin").click();
  await page.waitForURL((url) => url.pathname === nextPath, {
    timeout: 20_000,
  });

  const me = await apiJson(page, "/me");
  assert.equal(me.status, 200, `${role}: /me must succeed`);
  const venues = await apiJson(page, "/me/venues");
  assert.equal(venues.status, 200, `${role}: /me/venues must succeed`);
  assert.ok(
    Array.isArray(venues.body),
    `${role}: venues response must be an array`,
  );
  const venue = venues.body.find((item) => item?.name === venueName);
  assert.ok(venue, `${role}: seeded venue ${venueName} was not returned`);
  assert.equal(String(venue.my_role || "").toUpperCase(), role);
  return { venueId: Number(venue.id), authQuality };
}

async function assertNoHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  assert.ok(
    dimensions.scrollWidth <= dimensions.clientWidth + 1,
    `${label}: horizontal overflow ${dimensions.scrollWidth}px > ${dimensions.clientWidth}px`,
  );
  return dimensions;
}

async function settlePage(page) {
  await page
    .waitForLoadState("networkidle", { timeout: 10_000 })
    .catch(() => {});
  await page
    .waitForFunction(
      () => !document.documentElement.classList.contains("page-loading"),
      null,
      {
        timeout: 10_000,
      },
    )
    .catch(() => {});
}

async function assertAccessibility(page, label) {
  await page.addScriptTag({ content: axeSource });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
      },
      resultTypes: ["violations"],
    });
    return result.violations
      .filter((violation) => ["critical", "serious"].includes(violation.impact))
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.slice(0, 5).map((node) => node.target.join(" ")),
      }));
  });
  assert.deepEqual(
    violations,
    [],
    `${label}: critical or serious WCAG violations`,
  );
}

async function measurePerformance(page) {
  return page.evaluate(() => {
    const resources = performance.getEntriesByType("resource");
    return {
      readyMs: Math.round(performance.now()),
      requests: resources.length + 1,
      transferBytes: Math.round(
        resources.reduce(
          (total, entry) =>
            total + (entry.transferSize || entry.encodedBodySize || 0),
          0,
        ),
      ),
      domNodes: document.getElementsByTagName("*").length,
    };
  });
}

async function assertPageQuality(page, budgetName, label = budgetName) {
  const budget = performanceBudgets.pages[budgetName];
  assert.ok(budget, `Missing performance budget for ${budgetName}`);
  await settlePage(page);
  const performance = await measurePerformance(page);
  for (const [budgetKey, maximum] of Object.entries(budget)) {
    const metric = budgetKey.replace(/^max([A-Z])/, (_match, letter) =>
      letter.toLowerCase(),
    );
    assert.ok(
      performance[metric] <= maximum,
      `${label}: ${metric} ${performance[metric]} exceeds budget ${maximum}`,
    );
  }
  const dimensions = await assertNoHorizontalOverflow(page, label);
  await assertAccessibility(page, label);
  return { ...performance, dimensions };
}

async function ownerScenarios(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
  });
  const page = await context.newPage();
  const label = `${viewport.name} owner`;
  const assertDiagnostics = attachDiagnostics(page, label);
  const scenarios = [];
  try {
    const { venueId, authQuality } = await login(page, {
      phone: ownerPhone,
      role: "OWNER",
      auditAuth: true,
    });
    scenarios.push({ name: "owner-auth", quality: authQuality });

    await page.goto(`${frontendBase}/app-venues.html`, {
      waitUntil: "domcontentloaded",
    });
    await page.locator("#list").waitFor({ state: "visible", timeout: 20_000 });
    await page.waitForFunction(
      () => !document.querySelector("#list .skeleton"),
      null,
      { timeout: 20_000 },
    );
    scenarios.push({
      name: "owner-venues",
      quality: await assertPageQuality(page, "owner-venues", `${label} venues`),
    });

    await page.goto(`${frontendBase}/owner-summary.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => {
        const value = document.querySelector("#summaryRevenue");
        return (
          value &&
          !value.classList.contains("is-loading") &&
          value.textContent.trim() !== "Загрузка…"
        );
      },
      null,
      { timeout: 20_000 },
    );
    const state = await page.locator("#summaryState").evaluate((element) => ({
      hidden: element.classList.contains("hidden"),
      text: element.textContent.trim(),
    }));
    assert.ok(
      state.hidden,
      `owner: summary error state is visible: ${state.text}`,
    );
    scenarios.push({
      name: "owner-summary",
      quality: await assertPageQuality(
        page,
        "owner-summary",
        `${label} summary`,
      ),
    });

    await page.goto(`${frontendBase}/owner-expenses.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page
      .locator("#expensesState")
      .waitFor({ state: "visible", timeout: 20_000 });
    scenarios.push({
      name: "owner-expenses",
      quality: await assertPageQuality(
        page,
        "owner-expenses",
        `${label} expenses`,
      ),
    });

    await page.goto(`${frontendBase}/owner-payroll.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page
      .locator("#linesList")
      .waitFor({ state: "visible", timeout: 20_000 });
    await page.waitForFunction(
      () =>
        document.querySelector("#linesList")?.getAttribute("aria-busy") ===
        "false",
      null,
      {
        timeout: 20_000,
      },
    );
    scenarios.push({
      name: "owner-payroll",
      quality: await assertPageQuality(
        page,
        "owner-payroll",
        `${label} payroll`,
      ),
    });

    await page.goto(`${frontendBase}/settings.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page.locator("main").waitFor({ state: "visible", timeout: 20_000 });
    scenarios.push({
      name: "owner-settings",
      quality: await assertPageQuality(
        page,
        "owner-settings",
        `${label} settings`,
      ),
    });

    await page.goto(`${frontendBase}/positions.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page
      .locator("#root .topbar")
      .waitFor({ state: "visible", timeout: 20_000 });
    scenarios.push({
      name: "owner-positions",
      quality: await assertPageQuality(
        page,
        "owner-positions",
        `${label} positions`,
      ),
    });

    await page.goto(
      `${frontendBase}/owner-day-economics.html?venue_id=${venueId}`,
      {
        waitUntil: "domcontentloaded",
      },
    );
    await page
      .locator("#economicsContent")
      .waitFor({ state: "visible", timeout: 20_000 });
    await page.waitForFunction(
      () =>
        document
          .querySelector("#economicsContent")
          ?.getAttribute("aria-busy") === "false",
      null,
      { timeout: 20_000 },
    );
    scenarios.push({
      name: "owner-day-economics",
      quality: await assertPageQuality(
        page,
        "owner-day-economics",
        `${label} day economics`,
      ),
    });
    assertDiagnostics();
    return { venueId, scenarios };
  } finally {
    await context.close();
  }
}

async function staffScenarios(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
  });
  const page = await context.newPage();
  const label = `${viewport.name} staff`;
  const assertDiagnostics = attachDiagnostics(page, label);
  const scenarios = [];
  try {
    const { venueId, authQuality } = await login(page, {
      phone: staffPhone,
      role: "STAFF",
      auditAuth: true,
    });
    scenarios.push({ name: "staff-auth", quality: authQuality });
    await page.goto(`${frontendBase}/staff-shifts.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () =>
        document.querySelectorAll("#calGrid .cal-cell[data-date]").length ===
        42,
      null,
      { timeout: 20_000 },
    );
    const label = (await page.locator("#monthLabel").textContent())?.trim();
    assert.ok(label && label !== "…", "staff: month label must be rendered");
    scenarios.push({
      name: "staff-shifts",
      calendarCells: 42,
      quality: await assertPageQuality(page, "staff-shifts", `${label} shifts`),
    });

    await page.goto(`${frontendBase}/staff-salary.html?venue_id=${venueId}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => {
        const month = document.querySelector("#monthLabel");
        return (
          month && month.textContent.trim() && month.textContent.trim() !== "…"
        );
      },
      null,
      { timeout: 20_000 },
    );
    scenarios.push({
      name: "staff-salary",
      quality: await assertPageQuality(page, "staff-salary", `${label} salary`),
    });
    assertDiagnostics();
    return { venueId, scenarios };
  } finally {
    await context.close();
  }
}

async function demoScenarios(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
  });
  const page = await context.newPage();
  const label = `${viewport.name} public demo`;
  const assertDiagnostics = attachDiagnostics(page, label);
  try {
    await page.goto(`${apiBase}/auth/demo/start?persona=STAFF`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForURL(
      (url) =>
        url.origin === frontendBase && url.pathname === "/staff-shifts.html",
      {
        timeout: 20_000,
      },
    );
    await page
      .locator(".demo-banner")
      .waitFor({ state: "visible", timeout: 20_000 });
    await page
      .locator("#demoStaffIntro")
      .waitFor({ state: "visible", timeout: 20_000 });
    await page.waitForFunction(
      () =>
        document.querySelectorAll("#calGrid .cal-cell[data-date]").length ===
        42,
      null,
      { timeout: 20_000 },
    );

    const venueId = Number(new URL(page.url()).searchParams.get("venue_id"));
    assert.ok(
      Number.isInteger(venueId) && venueId > 0,
      "public demo: venue_id must be present",
    );
    const blockedMutation = await apiJson(page, `/venues/${venueId}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ name: "must-not-change" }),
    });
    assert.equal(
      blockedMutation.status,
      403,
      "public demo: mutations must remain read-only",
    );
    assert.equal(blockedMutation.body?.error_code, "DEMO_READONLY");

    const quality = await assertPageQuality(page, "public-demo", label);
    assertDiagnostics();
    return {
      venueId,
      scenarios: [
        {
          name: "public-demo-readonly",
          calendarCells: 42,
          mutationStatus: 403,
          quality,
        },
      ],
    };
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch({
  executablePath: browserExecutable(),
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

try {
  const matrix = {};
  for (const viewport of viewports) {
    const owner = await ownerScenarios(browser, viewport);
    const staff = await staffScenarios(browser, viewport);
    const demo = await demoScenarios(browser, viewport);
    const scenarios = [
      ...owner.scenarios,
      ...staff.scenarios,
      ...demo.scenarios,
    ];
    assert.deepEqual(
      scenarios.map((scenario) => scenario.name),
      expectedScenarios,
      `${viewport.name}: the complete 12-scenario suite must run`,
    );
    matrix[viewport.name] = {
      viewport: { width: viewport.width, height: viewport.height },
      ownerVenueId: owner.venueId,
      staffVenueId: staff.venueId,
      scenarios,
    };
  }
  console.log(JSON.stringify({ ok: true, scenarioCount: 12, matrix }, null, 2));
} finally {
  await browser.close();
}
