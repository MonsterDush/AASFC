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
const adminPhone = process.env.E2E_ADMIN_PHONE || "+79990000003";
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
      (message) => !message.includes("Failed to load resource"),
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
  await page.waitForLoadState("domcontentloaded");

  // getMe can reload the venue page once to apply the saved profile locale.
  // Wait for its authenticated content before evaluating API calls in the page.
  await page.locator("#list [data-open]").first().waitFor({ timeout: 20_000 });

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

async function loginAdmin(page) {
  const nextPath = "/admin-venues.html";
  await page.goto(
    `${frontendBase}/auth.html?next=${encodeURIComponent(nextPath)}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.locator("#loginPhoneInput").fill(adminPhone);
  await page.locator("#loginPasswordInput").fill(password);
  await page.locator("#btnPasswordLogin").click();
  await page.waitForURL((url) => url.pathname === nextPath, {
    timeout: 20_000,
  });
  await page.waitForLoadState("domcontentloaded");
  const me = await apiJson(page, "/me");
  assert.equal(me.status, 200, "SUPER_ADMIN: /me must succeed");
  assert.equal(
    String(me.body?.system_role || "").toUpperCase(),
    "SUPER_ADMIN",
    "SUPER_ADMIN: seeded system role must be returned",
  );
}

async function visitReadOnlySurfaces(page, paths, label) {
  const visited = [];
  for (const pagePath of paths) {
    await page.goto(`${frontendBase}${pagePath}`, {
      waitUntil: "domcontentloaded",
    });
    await page
      .waitForLoadState("networkidle", { timeout: 3_000 })
      .catch(() => {});
    await page.waitForTimeout(250);
    assert.ok(
      page.url().startsWith(frontendBase),
      `${label}: ${pagePath} left the frontend origin`,
    );
    visited.push(new URL(page.url()).pathname);
  }
  return visited;
}

async function expectApi(page, path, options, label, allowedStatuses = [200]) {
  const response = await apiJson(page, path, options);
  assert.ok(
    allowedStatuses.includes(response.status),
    `${label}: expected ${allowedStatuses.join("/")}, got ${response.status} ${JSON.stringify(response.body)}`,
  );
  return response.body;
}

function requireId(body, label) {
  const id = Number(body?.id ?? body?.invite_id ?? body?.item?.id);
  assert.ok(Number.isInteger(id) && id > 0, `${label}: response id is missing`);
  return id;
}

async function exerciseOwnerMutationSurface(page, venueId) {
  const prefix = `/venues/${venueId}`;
  const today = new Date().toISOString().slice(0, 10);
  const month = today.slice(0, 7);
  const calls = [];
  const mutate = async (path, method, body, label, statuses = [200]) => {
    const result = await expectApi(
      page,
      path,
      { method, body: body === undefined ? undefined : JSON.stringify(body) },
      label,
      statuses,
    );
    calls.push(`${method} ${path}`);
    return result;
  };

  const members = await expectApi(
    page,
    `${prefix}/members`,
    {},
    "owner mutation: members",
  );
  const memberItems = Array.isArray(members)
    ? members
    : members?.items || members?.members || [];
  const staffMember = memberItems.find(
    (item) => String(item?.venue_role || "").toUpperCase() === "STAFF",
  );
  const ownerMember = memberItems.find(
    (item) => String(item?.venue_role || "").toUpperCase() === "OWNER",
  );
  const staffUserId = Number(staffMember?.user_id);
  const ownerUserId = Number(ownerMember?.user_id);
  assert.ok(staffUserId > 0, "owner mutation: seeded staff member missing");
  assert.ok(ownerUserId > 0, "owner mutation: seeded owner member missing");

  for (const readPath of [
    `${prefix}/position-presets?include_inactive=true`,
    `${prefix}/payroll/payment-settings?month=${month}`,
    `${prefix}/payroll/recalculation-log?month=${month}&limit=5`,
    `${prefix}/finance/entries/analytics?month=${month}`,
    `${prefix}/finance/reconciliation?month=${month}`,
    `${prefix}/economics/plan-templates`,
    `${prefix}/shift-intervals?include_inactive=true`,
    `${prefix}/shift-swap-requests`,
    "/position-permission-templates?include_inactive=true",
  ]) {
    await expectApi(page, readPath, {}, `assurance read ${readPath}`);
    calls.push(`GET ${readPath}`);
  }

  const departmentId = requireId(
    await mutate(
      `${prefix}/departments`,
      "POST",
      {
        code: "e2e_coverage_department",
        title: "E2E Coverage Department",
        sort_order: 901,
      },
      "create department",
    ),
    "create department",
  );
  await mutate(
    `${prefix}/departments/${departmentId}`,
    "PATCH",
    { title: "E2E Coverage Department Updated", sort_order: 902 },
    "update department",
  );

  const paymentMethodId = requireId(
    await mutate(
      `${prefix}/payment-methods`,
      "POST",
      {
        code: "e2e_coverage_payment",
        title: "E2E Coverage Payment",
        sort_order: 901,
      },
      "create payment method",
    ),
    "create payment method",
  );
  await mutate(
    `${prefix}/payment-methods/${paymentMethodId}`,
    "PATCH",
    { title: "E2E Coverage Payment Updated" },
    "update payment method",
  );
  const paymentMethods = await expectApi(
    page,
    `${prefix}/payment-methods`,
    {},
    "list payment methods after create",
  );
  const otherPaymentMethodId = Number(
    paymentMethods.find((item) => Number(item?.id) !== paymentMethodId)?.id,
  );
  assert.ok(
    otherPaymentMethodId > 0,
    "owner mutation: second payment method missing",
  );

  const kpiMetricId = requireId(
    await mutate(
      `${prefix}/kpi-metrics`,
      "POST",
      {
        code: "e2e_coverage_kpi",
        title: "E2E Coverage KPI",
        unit: "QTY",
        sort_order: 901,
      },
      "create KPI metric",
    ),
    "create KPI metric",
  );
  await mutate(
    `${prefix}/kpi-metrics/${kpiMetricId}`,
    "PATCH",
    { title: "E2E Coverage KPI Updated", unit: "RUB" },
    "update KPI metric",
  );

  const categoryId = requireId(
    await mutate(
      `${prefix}/expense-categories`,
      "POST",
      {
        code: "e2e_coverage_expense",
        title: "E2E Coverage Expense",
        sort_order: 901,
      },
      "create expense category",
    ),
    "create expense category",
  );
  await mutate(
    `${prefix}/expense-categories/${categoryId}`,
    "PATCH",
    { title: "E2E Coverage Expense Updated" },
    "update expense category",
  );

  const supplierId = requireId(
    await mutate(
      `${prefix}/suppliers`,
      "POST",
      {
        title: "E2E Coverage Supplier",
        contact: "coverage@example.test",
        sort_order: 901,
      },
      "create supplier",
    ),
    "create supplier",
  );
  await mutate(
    `${prefix}/suppliers/${supplierId}`,
    "PATCH",
    { title: "E2E Coverage Supplier Updated", contact: null },
    "update supplier",
  );

  const profileId = requireId(
    await mutate(
      `${prefix}/pay-profiles`,
      "POST",
      {
        title: "E2E Coverage Pay Profile",
        description: "Created by the isolated mutation smoke",
      },
      "create pay profile",
    ),
    "create pay profile",
  );
  await mutate(
    `${prefix}/pay-profiles/${profileId}`,
    "PATCH",
    { title: "E2E Coverage Pay Profile Updated", description: null },
    "update pay profile",
  );
  const componentId = requireId(
    await mutate(
      `${prefix}/pay-profiles/${profileId}/components`,
      "POST",
      {
        component_type: "SALARY_HOURLY",
        title: "E2E Weekday Hourly Rate",
        rate_minor: 15000,
        weekday_rates: [
          { weekday: 0, rate_minor: 18000 },
          { weekday: 5, rate_minor: 22000 },
        ],
      },
      "create weekday pay component",
    ),
    "create weekday pay component",
  );
  await mutate(
    `${prefix}/pay-components/${componentId}`,
    "PATCH",
    {
      title: "E2E Weekday Hourly Rate Updated",
      weekday_rates: [{ weekday: 6, rate_minor: 25000 }],
    },
    "update weekday pay component",
  );
  const assignmentId = requireId(
    await mutate(
      `${prefix}/pay-profiles/${profileId}/assignments`,
      "POST",
      { member_user_id: staffUserId, start_date: "2035-01-01" },
      "create pay profile assignment",
    ),
    "create pay profile assignment",
  );
  await mutate(
    `${prefix}/pay-profile-assignments/${assignmentId}`,
    "PATCH",
    { end_date: "2035-12-31", is_active: false },
    "update pay profile assignment",
  );
  await expectApi(
    page,
    `${prefix}/pay-profiles/${profileId}`,
    {},
    "get pay profile detail",
  );

  const positionId = requireId(
    await mutate(
      `${prefix}/positions`,
      "POST",
      {
        title: "E2E Coverage Position",
        member_user_id: staffUserId,
        rate: 777,
        percent: 3,
        permission_codes: ["SHIFTS_VIEW"],
      },
      "create or update position",
    ),
    "create or update position",
  );
  await mutate(
    `${prefix}/positions/${positionId}`,
    "PATCH",
    { title: "E2E Coverage Position Updated", rate: 888 },
    "update position",
  );

  const expenseId = requireId(
    await mutate(
      `${prefix}/expenses`,
      "POST",
      {
        category_id: categoryId,
        supplier_id: supplierId,
        payment_method_id: paymentMethodId,
        amount_minor: 12345,
        expense_date: today,
        shift_slot: "DAY",
        status: "DRAFT",
        comment: "isolated E2E mutation smoke",
      },
      "create expense",
    ),
    "create expense",
  );
  await mutate(
    `${prefix}/expenses/${expenseId}`,
    "PATCH",
    { amount_minor: 23456, clear_supplier: true, comment: null },
    "update expense",
  );

  const adjustmentId = requireId(
    await mutate(
      `${prefix}/adjustments`,
      "POST",
      {
        type: "bonus",
        date: today,
        amount: 500,
        reason: "isolated E2E mutation smoke",
        member_user_id: staffUserId,
      },
      "create adjustment",
    ),
    "create adjustment",
  );
  await mutate(
    `${prefix}/adjustments/${adjustmentId}`,
    "PATCH",
    { amount: 600, reason: "updated isolated E2E mutation smoke" },
    "update adjustment",
  );

  const balanceAdjustmentId = requireId(
    await mutate(
      `${prefix}/balance-adjustments`,
      "POST",
      {
        payment_method_id: paymentMethodId,
        adjustment_date: today,
        delta_minor: 1111,
        status: "CONFIRMED",
        reason: "E2E coverage balance",
      },
      "create balance adjustment",
    ),
    "create balance adjustment",
  );
  await mutate(
    `${prefix}/balance-adjustments/${balanceAdjustmentId}`,
    "PATCH",
    { delta_minor: -2222, comment: "updated isolated E2E mutation smoke" },
    "update balance adjustment",
  );
  const transferId = requireId(
    await mutate(
      `${prefix}/payment-method-transfers`,
      "POST",
      {
        from_payment_method_id: otherPaymentMethodId,
        to_payment_method_id: paymentMethodId,
        transfer_date: today,
        amount_minor: 3333,
        status: "CONFIRMED",
        comment: "isolated E2E mutation smoke",
      },
      "create payment method transfer",
    ),
    "create payment method transfer",
  );
  await mutate(
    `${prefix}/payment-method-transfers/${transferId}`,
    "PATCH",
    { amount_minor: 4444, comment: "updated isolated E2E mutation smoke" },
    "update payment method transfer",
  );

  const recurringRuleId = requireId(
    await mutate(
      `${prefix}/recurring-expense-rules`,
      "POST",
      {
        title: "E2E Coverage Recurring Rule",
        category_id: categoryId,
        supplier_id: supplierId,
        payment_method_id: paymentMethodId,
        payment_method_ids: [paymentMethodId],
        start_date: `${month}-01`,
        frequency: "MONTHLY",
        day_of_month: 1,
        generation_mode: "FIXED",
        amount_minor: 34567,
        spread_months: 1,
      },
      "create recurring expense rule",
    ),
    "create recurring expense rule",
  );
  await mutate(
    `${prefix}/recurring-expense-rules/${recurringRuleId}`,
    "PATCH",
    {
      title: "E2E Coverage Recurring Rule Updated",
      clear_supplier: true,
      clear_payment_method: true,
      clear_end_date: true,
      payment_method_ids: [],
    },
    "update recurring expense rule",
  );
  await mutate(
    `${prefix}/recurring-expense-rules/generate?month=${month}&rule_id=${recurringRuleId}`,
    "POST",
    undefined,
    "generate recurring expense draft",
  );

  const intervalId = requireId(
    await mutate(
      `${prefix}/shift-intervals`,
      "POST",
      {
        title: "E2E Coverage Interval",
        start_time: "10:00:00",
        end_time: "18:00:00",
      },
      "create shift interval",
    ),
    "create shift interval",
  );
  await mutate(
    `${prefix}/shift-intervals/${intervalId}`,
    "PATCH",
    { title: "E2E Coverage Interval Updated", end_time: "19:00:00" },
    "update shift interval",
  );
  const templateId = requireId(
    await mutate(
      `${prefix}/shift-schedule-templates`,
      "POST",
      {
        title: "E2E Coverage Template",
        description: "isolated E2E mutation smoke",
        items: [{ weekday: 0, interval_id: intervalId, shift_slot: "DAY" }],
      },
      "create shift schedule template",
    ),
    "create shift schedule template",
  );
  await mutate(
    `${prefix}/shift-schedule-templates/${templateId}`,
    "PATCH",
    {
      title: "E2E Coverage Template Updated",
      items: [{ weekday: 1, interval_id: intervalId, shift_slot: "DAY" }],
    },
    "update shift schedule template",
  );
  await expectApi(
    page,
    `${prefix}/shift-schedule-templates/${templateId}`,
    {},
    "get shift schedule template",
  );

  const positions = await expectApi(
    page,
    `${prefix}/positions?include_inactive=true`,
    {},
    "list positions for shift mutation",
  );
  let ownerPositionId = Number(
    positions.find((item) => Number(item?.member?.user_id) === ownerUserId)?.id,
  );
  if (!(ownerPositionId > 0)) {
    ownerPositionId = requireId(
      await mutate(
        `${prefix}/positions`,
        "POST",
        {
          title: "E2E Coverage Owner Position",
          member_user_id: ownerUserId,
          rate: 0,
          percent: 0,
          permission_codes: ["SHIFTS_VIEW"],
        },
        "create owner position for shift",
      ),
      "create owner position for shift",
    );
  }
  const coverageShiftDate = "2035-01-08";
  const shiftId = requireId(
    await mutate(
      `${prefix}/shifts`,
      "POST",
      {
        date: coverageShiftDate,
        interval_id: intervalId,
        is_active: true,
        shift_slot: "DAY",
      },
      "create shift",
    ),
    "create shift",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}`,
    "PATCH",
    { is_active: false, shift_slot: "DAY" },
    "update shift inactive",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}`,
    "PATCH",
    { is_active: true },
    "update shift active",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}/assignments`,
    "POST",
    { venue_position_id: ownerPositionId },
    "assign owner to shift",
  );
  const staffUsername = String(staffMember?.tg_username || "").replace(
    /^@+/,
    "",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}/comments`,
    "POST",
    {
      text: staffUsername
        ? `Coverage note for @${staffUsername}`
        : "Coverage note without mention",
      mentioned_user_ids: staffUsername ? [staffUserId] : [],
    },
    "create shift comment",
  );
  await expectApi(
    page,
    `${prefix}/shifts/${shiftId}/comments`,
    {},
    "list shift comments",
  );
  await expectApi(
    page,
    `${prefix}/shifts/${shiftId}/mentionable-members`,
    {},
    "list mentionable shift members",
  );
  await expectApi(
    page,
    `${prefix}/shifts/${shiftId}/swap-candidates`,
    {},
    "list shift swap candidates",
  );
  const swapRequestId = requireId(
    await mutate(
      `${prefix}/shifts/${shiftId}/swap-requests`,
      "POST",
      {
        replacement_user_id: staffUserId,
        comment: "isolated E2E mutation smoke",
      },
      "create shift swap request",
    ),
    "create shift swap request",
  );
  await mutate(
    `${prefix}/shift-swap-requests/${swapRequestId}/cancel`,
    "POST",
    undefined,
    "cancel shift swap request",
  );
  await mutate(
    `${prefix}/shift-availability/${coverageShiftDate}/DAY`,
    "PUT",
    { status: "AVAILABLE", comment: "isolated E2E mutation smoke" },
    "set shift availability",
  );
  await mutate(
    `${prefix}/shift-availability/${coverageShiftDate}/DAY`,
    "DELETE",
    undefined,
    "delete shift availability",
  );

  await mutate(`${prefix}/setup/start`, "POST", undefined, "start setup");
  await mutate(
    `${prefix}/setup`,
    "PATCH",
    {
      current_step_key: "kpi",
      phase: "PREPARE",
      step_meta: { e2e_coverage: true },
    },
    "patch setup state",
  );
  await mutate(
    `${prefix}/setup/skip-step`,
    "POST",
    { step_key: "kpi" },
    "skip optional setup step",
  );
  await mutate(
    `${prefix}/setup/reset-step`,
    "POST",
    { step_key: "kpi" },
    "reset setup step",
  );
  await mutate(
    `${prefix}/setup/complete-step`,
    "POST",
    { step_key: "payment_methods" },
    "complete setup step",
  );

  for (const exportPath of [
    `${prefix}/revenue/export?month=${month}&mode=DEPARTMENTS&fmt=csv`,
    `${prefix}/revenue/export?month=${month}&mode=PAYMENTS&fmt=xlsx`,
    `${prefix}/expenses/export?month=${month}`,
    `${prefix}/summary/monthly/export?month=${month}`,
    `${prefix}/payroll/export?month=${month}`,
    `${prefix}/finance/entries/export?month=${month}`,
  ]) {
    await expectApi(page, exportPath, {}, `export smoke ${exportPath}`);
    calls.push(`GET ${exportPath}`);
  }

  const inviteId = requireId(
    await mutate(
      `${prefix}/invites`,
      "POST",
      {
        invite_channel: "PHONE",
        phone: "+79995550123",
        contact_label: "E2E Coverage Invite",
        venue_role: "STAFF",
      },
      "create invite",
    ),
    "create invite",
  );
  await mutate(
    `${prefix}/invites/${inviteId}/default_position`,
    "PATCH",
    {
      default_position: {
        title: "E2E Invite Position",
        rate: 900,
        percent: 4,
        permission_codes: ["SHIFTS_VIEW"],
      },
    },
    "update invite default position",
  );

  await mutate(
    `${prefix}/reports?shift_slot=DAY`,
    "POST",
    {
      date: today,
      cash: 10000,
      cashless: 20000,
      revenue_total: 30000,
      tips_total: 500,
      comment: "isolated E2E mutation smoke",
    },
    "upsert report",
  );
  await expectApi(
    page,
    `${prefix}/reports/${today}/audit?shift_slot=DAY`,
    {},
    "get report audit",
  );

  await mutate(
    `${prefix}/invites/${inviteId}`,
    "DELETE",
    undefined,
    "delete invite",
  );
  await mutate(
    `${prefix}/shift-schedule-templates/${templateId}`,
    "DELETE",
    undefined,
    "delete shift schedule template",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}/assignments/${ownerUserId}`,
    "DELETE",
    undefined,
    "delete shift assignment",
  );
  await mutate(
    `${prefix}/shifts/${shiftId}`,
    "DELETE",
    undefined,
    "delete shift",
  );
  await mutate(
    `${prefix}/shift-intervals/${intervalId}`,
    "DELETE",
    undefined,
    "protect shift interval referenced by archived shift",
    [409],
  );
  await mutate(
    `${prefix}/recurring-expense-rules/${recurringRuleId}`,
    "DELETE",
    undefined,
    "delete recurring expense rule",
  );
  await mutate(
    `${prefix}/adjustments/${adjustmentId}`,
    "DELETE",
    undefined,
    "delete adjustment",
  );
  await mutate(
    `${prefix}/balance-adjustments/${balanceAdjustmentId}`,
    "DELETE",
    undefined,
    "delete balance adjustment",
  );
  await mutate(
    `${prefix}/payment-method-transfers/${transferId}`,
    "DELETE",
    undefined,
    "delete payment method transfer",
  );
  await mutate(
    `${prefix}/expenses/${expenseId}`,
    "DELETE",
    undefined,
    "delete expense",
  );
  await mutate(
    `${prefix}/pay-profile-assignments/${assignmentId}`,
    "DELETE",
    undefined,
    "delete pay profile assignment",
  );
  await mutate(
    `${prefix}/pay-components/${componentId}`,
    "DELETE",
    undefined,
    "delete pay component",
  );
  await mutate(
    `${prefix}/pay-profiles/${profileId}`,
    "DELETE",
    undefined,
    "delete pay profile",
  );

  return calls;
}

async function exerciseAdminMutationSurface(page, venueId) {
  const calls = [];
  const promoCode = `E2E_COVERAGE_${Date.now()}`;
  const mutate = async (path, method, body, label, statuses = [200]) => {
    const result = await expectApi(
      page,
      path,
      { method, body: body === undefined ? undefined : JSON.stringify(body) },
      label,
      statuses,
    );
    calls.push(`${method} ${path}`);
    return result;
  };
  await expectApi(
    page,
    `/venues/${venueId}/delete-check`,
    {},
    "admin venue delete check",
  );
  calls.push(`GET /venues/${venueId}/delete-check`);
  const promoId = requireId(
    await mutate(
      "/admin/billing/promocodes",
      "POST",
      {
        code: promoCode,
        title: "E2E Coverage Promo",
        kind: "PERCENT",
        percent_value: 10,
        comment: "isolated E2E mutation smoke",
      },
      "create billing promo",
    ),
    "create billing promo",
  );
  await mutate(
    `/admin/billing/promocodes/${promoId}`,
    "PATCH",
    { title: "E2E Coverage Promo Updated", percent_value: 15 },
    "update billing promo",
  );
  await mutate(
    `/admin/billing/promocodes/${promoId}/archive`,
    "POST",
    undefined,
    "archive billing promo",
  );
  await mutate(
    `/admin/venues/${venueId}/billing/extend`,
    "POST",
    { days: 1, comment: "isolated E2E mutation smoke", amount_minor: 0 },
    "extend billing",
  );
  return calls;
}

async function exerciseReadOnlyCoverageSurfaces(browser) {
  const ownerContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const ownerPage = await ownerContext.newPage();
  const assertOwnerDiagnostics = attachDiagnostics(
    ownerPage,
    "desktop owner read-only surface coverage",
  );
  let ownerVenueId;
  let ownerPages;
  let ownerMutations;
  try {
    ({ venueId: ownerVenueId } = await login(ownerPage, {
      phone: ownerPhone,
      role: "OWNER",
    }));
    const venueQuery = `?venue_id=${ownerVenueId}`;
    ownerPages = await visitReadOnlySurfaces(
      ownerPage,
      [
        `/app-dashboard.html${venueQuery}`,
        `/app-venue.html${venueQuery}`,
        `/app-adjustments.html${venueQuery}`,
        `/owner-departments.html${venueQuery}`,
        `/owner-economics-plans.html${venueQuery}`,
        `/owner-economics-rules.html${venueQuery}`,
        `/owner-expense-categories.html${venueQuery}`,
        `/owner-finance-ledger.html${venueQuery}`,
        `/owner-integrations.html${venueQuery}`,
        `/owner-kpi.html${venueQuery}`,
        `/owner-pay-profiles.html${venueQuery}`,
        `/owner-payment-methods.html${venueQuery}`,
        `/owner-quickresto.html${venueQuery}`,
        `/owner-recurring-expenses.html${venueQuery}`,
        `/owner-revenue.html${venueQuery}`,
        `/owner-setup.html${venueQuery}`,
        `/owner-subscription.html${venueQuery}`,
        `/owner-suppliers.html${venueQuery}`,
        `/owner-tip-settings.html${venueQuery}`,
        `/owner-turnover.html${venueQuery}`,
        `/shift-intervals.html${venueQuery}`,
        `/shift-schedule-templates.html${venueQuery}`,
        `/invites.html${venueQuery}`,
        `/profile.html${venueQuery}`,
      ],
      "owner surface coverage",
    );
    ownerMutations = await exerciseOwnerMutationSurface(
      ownerPage,
      ownerVenueId,
    );
    assertOwnerDiagnostics();
  } finally {
    await ownerContext.close();
  }

  const adminContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const adminPage = await adminContext.newPage();
  const assertAdminDiagnostics = attachDiagnostics(
    adminPage,
    "desktop admin read-only surface coverage",
  );
  let adminPages;
  let adminMutations;
  try {
    await loginAdmin(adminPage);
    adminPages = await visitReadOnlySurfaces(
      adminPage,
      [
        "/admin-venues.html",
        "/admin-billing.html",
        "/admin-demo.html",
        "/admin-demo-analytics.html",
        "/admin-invites.html",
        "/admin-position-templates.html",
      ],
      "admin surface coverage",
    );
    adminMutations = await exerciseAdminMutationSurface(
      adminPage,
      ownerVenueId,
    );
    assertAdminDiagnostics();
  } finally {
    await adminContext.close();
  }

  return {
    ownerVenueId,
    ownerPages,
    ownerMutations,
    adminPages,
    adminMutations,
  };
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

async function verifyNamesAndIntervalScopes(page, venueId, viewport) {
  const prefix = `/venues/${venueId}`;
  const suffix = `${viewport.name}-${Date.now()}`;
  const me = await expectApi(page, "/me", {}, "scope owner");
  const members = await expectApi(
    page,
    `${prefix}/members`,
    {},
    "scope members",
  );
  const employee = members.members.find(
    (member) => member.phone === staffPhone,
  );
  assert.ok(employee, "scope scenario needs the seeded employee");
  const mutate = (path, method, body) =>
    expectApi(
      page,
      path,
      {
        method,
        body: JSON.stringify(body),
      },
      `scope ${method} ${path}`,
    );
  await mutate(`${prefix}/members/${employee.user_id}/owner-note`, "PATCH", {
    owner_note: "Миша старший",
  });
  const titles = [`Бар ${suffix}`, `Зал ${suffix}`, `Менеджер ${suffix}`];
  const assignments = [];
  for (const [index, title] of titles.entries()) {
    assignments.push(
      await mutate(`${prefix}/positions`, "POST", {
        title,
        member_user_id: index === 2 ? me.id : employee.user_id,
        permission_codes: ["SHIFTS_VIEW"],
      }),
    );
  }
  const positions = await expectApi(
    page,
    `${prefix}/positions`,
    {},
    "linked roles",
  );
  const catalogIds = assignments.map(
    (assignment) =>
      positions.find((position) => position.id === assignment.id)
        .catalog_position_id,
  );
  assert.ok(catalogIds.every((id) => id > 0));
  const other = await mutate(`${prefix}/shift-intervals`, "POST", {
    title: `Только менеджер ${suffix}`,
    start_time: "10:00",
    end_time: "22:00",
    position_ids: [catalogIds[2]],
  });
  const universal = await mutate(`${prefix}/shift-intervals`, "POST", {
    title: `Все ${suffix}`,
    start_time: "11:00",
    end_time: "23:00",
    position_ids: [],
  });
  await page.goto(
    `${frontendBase}/shift-intervals.html?venue_id=${venueId}&lang=ru`,
  );
  await page.locator("#btnCreate").click();
  const intervalTitle = `Бар и зал ${suffix}`;
  await page.locator("#f_title").fill(intervalTitle);
  await page.locator("#f_start").fill("12:00");
  await page.locator("#f_end").fill("00:00");
  const group = page.locator("#f_position");
  assert.equal(await group.locator("[data-all]").isChecked(), true);
  for (const id of catalogIds.slice(0, 2))
    await group.locator(`[data-position-id="${id}"]`).check();
  assert.equal(await group.locator("[data-all]").isChecked(), false);
  const screenshotDir = path.join(repoRoot, "artifacts/names-intervals-qa");
  fs.mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({
    path: path.join(screenshotDir, `interval-editor-${viewport.name}.png`),
  });
  await page.locator("#btnSaveEdit").click();
  await page.locator("#editModal").waitFor({ state: "hidden" });
  const intervals = await expectApi(
    page,
    `${prefix}/shift-intervals`,
    {},
    "saved interval scopes",
  );
  const interval = intervals.find((item) => item.title === intervalTitle);
  assert.deepEqual(
    interval.position_ids,
    catalogIds.slice(0, 2).sort((a, b) => a - b),
  );
  const date = "2035-02-12";
  const rejected = await apiJson(page, `${prefix}/shifts`, {
    method: "POST",
    body: JSON.stringify({
      date,
      interval_id: other.id,
      venue_position_id: assignments[0].id,
    }),
  });
  assert.equal(rejected.status, 409);
  assert.equal(rejected.body.detail.code, "SHIFT_INTERVAL_POSITION_MISMATCH");
  await page.goto(
    `${frontendBase}/staff-shifts.html?venue_id=${venueId}&date=${date}&lang=ru`,
  );
  await page.locator(`.cal-cell[data-date="${date}"]`).click();
  await page.locator(`.cal-cell[data-date="${date}"]`).click();
  await page.locator("#btnAddShift").click();
  const employeeSelect = page.locator("#createShiftMember");
  await employeeSelect.selectOption(String(employee.user_id));
  assert.equal(
    await employeeSelect.locator("option:checked").textContent(),
    "Миша старший",
  );
  let visible = await page
    .locator("#intervalSelect option")
    .evaluateAll((options) => options.map((option) => Number(option.value)));
  assert.ok(visible.includes(interval.id));
  assert.ok(visible.includes(universal.id));
  assert.ok(!visible.includes(other.id));
  await employeeSelect.selectOption(String(me.id));
  visible = await page
    .locator("#intervalSelect option")
    .evaluateAll((options) => options.map((option) => Number(option.value)));
  assert.ok(!visible.includes(interval.id));
  assert.ok(visible.includes(other.id));
  await employeeSelect.selectOption(String(employee.user_id));
  await page.locator("#intervalSelect").selectOption(String(interval.id));
  const roleIds = await page
    .locator("#createShiftPosition option")
    .evaluateAll((options) => options.map((option) => Number(option.value)));
  assert.deepEqual(
    roleIds.sort((a, b) => a - b),
    assignments
      .slice(0, 2)
      .map((assignment) => assignment.id)
      .sort((a, b) => a - b),
  );
  await page
    .locator("#createShiftPosition")
    .selectOption(String(assignments[1].id));
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
    "schedule fits viewport",
  );
  await page.screenshot({
    path: path.join(screenshotDir, `create-shift-${viewport.name}.png`),
  });
  const saved = page.waitForResponse(
    (response) =>
      response.url() === `${apiBase}${prefix}/shifts` &&
      response.request().method() === "POST",
  );
  await page.locator("#createShiftBtn").click();
  const response = await saved;
  assert.equal(response.status(), 200);
  const shift = await response.json();
  let detail = await expectApi(
    page,
    `${prefix}/shifts/${shift.id}`,
    {},
    "new assigned shift",
  );
  assert.equal(detail.assignments[0].member.display_name, "Миша старший");
  assert.equal(detail.assignments[0].venue_position_id, assignments[1].id);
  await mutate(`${prefix}/shift-intervals/${interval.id}`, "PATCH", {
    position_ids: [catalogIds[2]],
  });
  detail = await expectApi(
    page,
    `${prefix}/shifts/${shift.id}`,
    {},
    "preserved assignment after scope change",
  );
  assert.equal(detail.assignments[0].venue_position_id, assignments[1].id);
  await mutate(`${prefix}/shifts/${shift.id}`, "PATCH", {
    interval_id: other.id,
  });
  detail = await expectApi(
    page,
    `${prefix}/shifts/${shift.id}`,
    {},
    "preserved assignment after interval change",
  );
  assert.equal(detail.assignments[0].venue_position_id, assignments[1].id);
  await page.goto(
    `${frontendBase}/shift-intervals.html?venue_id=${venueId}&lang=en`,
  );
  await page.locator("#btnCreate").click();
  await page.getByRole("group", { name: "Available for roles" }).waitFor();
  await page.locator("#f_position [data-position-id]").first().check();
  await page.locator("#f_position [data-all]").check();
  assert.equal(
    await page.locator("#f_position [data-position-id]:checked").count(),
    0,
  );
  await mutate(`${prefix}/members/${employee.user_id}/owner-note`, "PATCH", {
    owner_note: employee.owner_note,
  });
  console.log(
    `${viewport.name}: names, multiple roles, employee filtering and existing assignments passed`,
  );
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
    await verifyNamesAndIntervalScopes(page, venueId, viewport);
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
  const readOnlyCoverageSurfaces =
    await exerciseReadOnlyCoverageSurfaces(browser);
  console.log(
    JSON.stringify(
      {
        ok: true,
        scenarioCount: 12,
        matrix,
        readOnlyCoverageSurfaces,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
