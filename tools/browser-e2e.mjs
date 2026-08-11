import assert from "node:assert/strict";
import fs from "node:fs";
import { chromium } from "playwright-core";


const frontendBase = String(process.env.E2E_FRONTEND_BASE || "http://127.0.0.1:8765").replace(/\/+$/, "");
const apiBase = String(process.env.E2E_API_BASE || "http://127.0.0.1:9001").replace(/\/+$/, "");
const ownerPhone = process.env.E2E_OWNER_PHONE || "+79990000001";
const staffPhone = process.env.E2E_STAFF_PHONE || "+79990000002";
const password = process.env.E2E_PASSWORD || "AxelioE2E123!";
const venueName = process.env.E2E_VENUE_NAME || "Axelio E2E Lounge";


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
    throw new Error(`Chrome executable not found; checked: ${candidates.join(", ")}`);
  }
  return executable;
}


function attachDiagnostics(page, label) {
  const pageErrors = [];
  const consoleErrors = [];
  const serverErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error?.message || error)));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.url().startsWith(apiBase) && response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });
  return () => {
    assert.deepEqual(pageErrors, [], `${label}: uncaught page errors`);
    assert.deepEqual(serverErrors, [], `${label}: API 5xx responses`);
    const relevantConsoleErrors = consoleErrors.filter(
      (message) => !message.includes("Failed to load resource") && !message.includes("telegram.org"),
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
      let body = null;
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


async function login(page, { phone, role }) {
  const nextPath = "/app-venues.html";
  await page.goto(`${frontendBase}/auth.html?next=${encodeURIComponent(nextPath)}`, {
    waitUntil: "domcontentloaded",
  });
  await page.locator("#loginPhoneInput").fill(phone);
  await page.locator("#loginPasswordInput").fill(password);
  await page.locator("#btnPasswordLogin").click();
  await page.waitForURL((url) => url.pathname === nextPath, { timeout: 20_000 });

  const me = await apiJson(page, "/me");
  assert.equal(me.status, 200, `${role}: /me must succeed`);
  const venues = await apiJson(page, "/me/venues");
  assert.equal(venues.status, 200, `${role}: /me/venues must succeed`);
  assert.ok(Array.isArray(venues.body), `${role}: venues response must be an array`);
  const venue = venues.body.find((item) => item?.name === venueName);
  assert.ok(venue, `${role}: seeded venue ${venueName} was not returned`);
  assert.equal(String(venue.my_role || "").toUpperCase(), role);
  return Number(venue.id);
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


async function ownerScenario(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const assertDiagnostics = attachDiagnostics(page, "owner");
  try {
    const venueId = await login(page, { phone: ownerPhone, role: "OWNER" });
    await page.goto(`${frontendBase}/owner-summary.html?venue_id=${venueId}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => {
      const value = document.querySelector("#summaryRevenue");
      return value && !value.classList.contains("is-loading") && value.textContent.trim() !== "Загрузка…";
    }, null, { timeout: 20_000 });
    const state = await page.locator("#summaryState").evaluate((element) => ({
      hidden: element.classList.contains("hidden"),
      text: element.textContent.trim(),
    }));
    assert.ok(state.hidden, `owner: summary error state is visible: ${state.text}`);
    const dimensions = await assertNoHorizontalOverflow(page, "owner desktop");
    assertDiagnostics();
    return { venueId, dimensions };
  } finally {
    await context.close();
  }
}


async function staffScenario(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const assertDiagnostics = attachDiagnostics(page, "staff");
  try {
    const venueId = await login(page, { phone: staffPhone, role: "STAFF" });
    await page.goto(`${frontendBase}/staff-shifts.html?venue_id=${venueId}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      () => document.querySelectorAll("#calGrid .cal-cell[data-date]").length === 42,
      null,
      { timeout: 20_000 },
    );
    const label = (await page.locator("#monthLabel").textContent())?.trim();
    assert.ok(label && label !== "…", "staff: month label must be rendered");
    const dimensions = await assertNoHorizontalOverflow(page, "staff desktop");
    assertDiagnostics();
    return { venueId, calendarCells: 42, dimensions };
  } finally {
    await context.close();
  }
}


async function demoScenario(browser) {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  const assertDiagnostics = attachDiagnostics(page, "public demo");
  try {
    await page.goto(`${apiBase}/auth/demo/start?persona=STAFF`, { waitUntil: "domcontentloaded" });
    await page.waitForURL((url) => url.origin === frontendBase && url.pathname === "/staff-shifts.html", {
      timeout: 20_000,
    });
    await page.locator(".demo-banner").waitFor({ state: "visible", timeout: 20_000 });
    await page.locator("#demoStaffIntro").waitFor({ state: "visible", timeout: 20_000 });
    await page.waitForFunction(
      () => document.querySelectorAll("#calGrid .cal-cell[data-date]").length === 42,
      null,
      { timeout: 20_000 },
    );

    const venueId = Number(new URL(page.url()).searchParams.get("venue_id"));
    assert.ok(Number.isInteger(venueId) && venueId > 0, "public demo: venue_id must be present");
    const blockedMutation = await apiJson(page, `/venues/${venueId}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ name: "must-not-change" }),
    });
    assert.equal(blockedMutation.status, 403, "public demo: mutations must remain read-only");
    assert.equal(blockedMutation.body?.error_code, "DEMO_READONLY");

    const dimensions = await assertNoHorizontalOverflow(page, "public demo mobile");
    assertDiagnostics();
    return { venueId, calendarCells: 42, mutationStatus: 403, dimensions };
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
  const owner = await ownerScenario(browser);
  const staff = await staffScenario(browser);
  const demo = await demoScenario(browser);
  console.log(JSON.stringify({ ok: true, owner, staff, demo }, null, 2));
} finally {
  await browser.close();
}
