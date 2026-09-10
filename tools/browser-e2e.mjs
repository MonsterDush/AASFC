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
  "owner-department-plans",
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
  const coverageToken = `${Date.now().toString(36)}_${process.pid}`;
  const coverageTitle = (title) => `${title} ${coverageToken}`;
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
        code: `e2e_coverage_department_${coverageToken}`,
        title: coverageTitle("E2E Coverage Department"),
        sort_order: 901,
      },
      "create department",
    ),
    "create department",
  );
  await mutate(
    `${prefix}/departments/${departmentId}`,
    "PATCH",
    {
      title: coverageTitle("E2E Coverage Department Updated"),
      sort_order: 902,
    },
    "update department",
  );

  const paymentMethodId = requireId(
    await mutate(
      `${prefix}/payment-methods`,
      "POST",
      {
        code: `e2e_coverage_payment_${coverageToken}`,
        title: coverageTitle("E2E Coverage Payment"),
        sort_order: 901,
      },
      "create payment method",
    ),
    "create payment method",
  );
  await mutate(
    `${prefix}/payment-methods/${paymentMethodId}`,
    "PATCH",
    { title: coverageTitle("E2E Coverage Payment Updated") },
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
        code: `e2e_coverage_kpi_${coverageToken}`,
        title: coverageTitle("E2E Coverage KPI"),
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
    { title: coverageTitle("E2E Coverage KPI Updated"), unit: "RUB" },
    "update KPI metric",
  );

  const categoryId = requireId(
    await mutate(
      `${prefix}/expense-categories`,
      "POST",
      {
        code: `e2e_coverage_expense_${coverageToken}`,
        title: coverageTitle("E2E Coverage Expense"),
        sort_order: 901,
      },
      "create expense category",
    ),
    "create expense category",
  );
  await mutate(
    `${prefix}/expense-categories/${categoryId}`,
    "PATCH",
    { title: coverageTitle("E2E Coverage Expense Updated") },
    "update expense category",
  );

  const supplierId = requireId(
    await mutate(
      `${prefix}/suppliers`,
      "POST",
      {
        title: coverageTitle("E2E Coverage Supplier"),
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
    { title: coverageTitle("E2E Coverage Supplier Updated"), contact: null },
    "update supplier",
  );

  const profileId = requireId(
    await mutate(
      `${prefix}/pay-profiles`,
      "POST",
      {
        title: coverageTitle("E2E Coverage Pay Profile"),
        description: "Created by the isolated mutation smoke",
      },
      "create pay profile",
    ),
    "create pay profile",
  );
  await mutate(
    `${prefix}/pay-profiles/${profileId}`,
    "PATCH",
    {
      title: coverageTitle("E2E Coverage Pay Profile Updated"),
      description: null,
    },
    "update pay profile",
  );
  const componentId = requireId(
    await mutate(
      `${prefix}/pay-profiles/${profileId}/components`,
      "POST",
      {
        component_type: "SALARY_HOURLY",
        title: coverageTitle("E2E Weekday Hourly Rate"),
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
      title: coverageTitle("E2E Weekday Hourly Rate Updated"),
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
        title: coverageTitle("E2E Coverage Position"),
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
    { title: coverageTitle("E2E Coverage Position Updated"), rate: 888 },
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
        title: coverageTitle("E2E Coverage Recurring Rule"),
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
      title: coverageTitle("E2E Coverage Recurring Rule Updated"),
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
        title: coverageTitle("E2E Coverage Interval"),
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
    {
      title: coverageTitle("E2E Coverage Interval Updated"),
      end_time: "19:00:00",
    },
    "update shift interval",
  );
  const templateId = requireId(
    await mutate(
      `${prefix}/shift-schedule-templates`,
      "POST",
      {
        title: coverageTitle("E2E Coverage Template"),
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
      title: coverageTitle("E2E Coverage Template Updated"),
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
          title: coverageTitle("E2E Coverage Owner Position"),
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
        contact_label: coverageTitle("E2E Coverage Invite"),
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
        title: coverageTitle("E2E Invite Position"),
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

async function verifyDepartmentPlansAndPercentTiers(page, venueId, viewport) {
  const prefix = `/venues/${venueId}`;
  const month = "2035-03";
  const screenshotDir = path.join(repoRoot, "artifacts/plans-percent-tiers-qa");
  fs.mkdirSync(screenshotDir, { recursive: true });
  const departments = await expectApi(
    page,
    `${prefix}/departments`,
    {},
    "department plans departments",
  );
  const department = departments.find((item) => item.is_active !== false);
  assert.ok(
    department?.id,
    "department plans scenario needs an active department",
  );

  await page.goto(
    `${frontendBase}/owner-economics-plans.html?venue_id=${venueId}&month=${month}&lang=ru`,
    { waitUntil: "domcontentloaded" },
  );
  await page.locator("#departmentPlansLink").waitFor({ state: "visible" });
  const departmentEntry = await page
    .locator("#departmentPlansLink")
    .evaluate((entry) => {
      const toolbar = document.querySelector(".finance-toolbar");
      const style = getComputedStyle(entry);
      const rect = entry.getBoundingClientRect();
      return {
        beforeToolbar: Boolean(
          toolbar &&
          entry.compareDocumentPosition(toolbar) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ),
        textDecoration: style.textDecorationLine,
        left: rect.left,
        right: rect.right,
        viewportWidth: document.documentElement.clientWidth,
      };
    });
  assert.equal(
    departmentEntry.beforeToolbar,
    true,
    "department plans entry must be above the venue plans toolbar",
  );
  assert.equal(
    departmentEntry.textDecoration,
    "none",
    "department plans entry must render as a navigation card",
  );
  assert.ok(
    departmentEntry.left >= 0 &&
      departmentEntry.right <= departmentEntry.viewportWidth + 0.5,
    "department plans entry must fit the viewport",
  );
  await assertNoHorizontalOverflow(
    page,
    `${viewport.name} venue plans navigation`,
  );
  await page.screenshot({
    path: path.join(
      screenshotDir,
      `venue-plans-navigation-${viewport.name}.png`,
    ),
    fullPage: true,
  });

  await page.goto(
    `${frontendBase}/owner-department-plans.html?venue_id=${venueId}&department_id=${department.id}&month=${month}&mode=DAYS&lang=ru`,
    { waitUntil: "domcontentloaded" },
  );
  await page.locator("#planContent").waitFor({
    state: "visible",
    timeout: 20_000,
  });
  await page.locator("#daysPanel").waitFor({ state: "visible" });
  assert.equal(await page.locator("#calendarRows [data-date]").count(), 31);
  const assertFilterFitsViewport = async (label) => {
    const geometry = await page.locator("#monthPick").evaluate((monthPick) => {
      const filter = monthPick.closest(".dp-filters");
      const inputRect = monthPick.getBoundingClientRect();
      const filterRect = filter?.getBoundingClientRect();
      return {
        inputLeft: inputRect.left,
        inputRight: inputRect.right,
        filterLeft: filterRect?.left,
        filterRight: filterRect?.right,
        viewportWidth: document.documentElement.clientWidth,
      };
    });
    assert.ok(
      geometry.inputLeft >= 0 &&
        geometry.inputRight <= geometry.viewportWidth + 0.5 &&
        geometry.filterLeft >= 0 &&
        geometry.filterRight <= geometry.viewportWidth + 0.5,
      `${label}: department month filter must fit the viewport`,
    );
    await assertNoHorizontalOverflow(page, label);
  };
  await assertFilterFitsViewport(
    `${viewport.name} owner department plans filters`,
  );
  if (viewport.name === "mobile") {
    await page.setViewportSize({ width: 320, height: viewport.height });
    await assertFilterFitsViewport("320px owner department plans filters");
    await page.screenshot({
      path: path.join(screenshotDir, "department-plans-mobile-320.png"),
      fullPage: true,
    });
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
  }
  const quality = await assertPageQuality(
    page,
    "owner-department-plans",
    `${viewport.name} owner department plans`,
  );

  const weeklyRub = [50_000, 50_000, 60_000, 60_000, 100_000, 130_000, 80_000];
  for (const [weekday, value] of weeklyRub.entries()) {
    await page.locator(`#weekday${weekday}`).fill(String(value));
  }
  const bulkPreviewed = page.waitForResponse(
    (response) =>
      response.url() === `${apiBase}${prefix}/department-plans/days/bulk` &&
      response.request().method() === "PUT" &&
      response.status() === 200 &&
      response.request().postDataJSON()?.dry_run,
  );
  const bulkSaved = page.waitForResponse(
    (response) =>
      response.url() === `${apiBase}${prefix}/department-plans/days/bulk` &&
      response.request().method() === "PUT" &&
      response.status() === 200 &&
      !response.request().postDataJSON()?.dry_run,
  );
  await page.locator("#applyMonth").click();
  const preview = await (await bulkPreviewed).json();
  if (preview.overwritten_count) {
    const confirmOverwrite = page.locator(
      "#modal.open .modal__body .btn.primary",
    );
    await confirmOverwrite.waitFor({ state: "visible" });
    await confirmOverwrite.click();
  }
  const bulkResult = await (await bulkSaved).json();
  await page.waitForFunction(
    (changedCount) =>
      document
        .querySelector("#bulkHint")
        ?.textContent.includes(`Изменено дат: ${changedCount}`),
    bulkResult.changed_count,
    { timeout: 20_000 },
  );

  const overrideDate = "2035-03-09";
  const overrideRow = page.locator(`[data-date="${overrideDate}"]`);
  await overrideRow.locator("input").fill("155000");
  const daySaved = page.waitForResponse(
    (response) =>
      response.url() ===
        `${apiBase}${prefix}/department-plans/${department.id}/day?date=${overrideDate}` &&
      response.request().method() === "PUT" &&
      response.status() === 200,
  );
  await overrideRow.locator("button").click();
  await daySaved;
  const calendar = await expectApi(
    page,
    `${prefix}/department-plans/${department.id}/calendar?month=${month}`,
    {},
    "department plans calendar after bulk and override",
  );
  assert.equal(calendar.revenue_plan_minor, null);
  assert.equal(
    calendar.days.find((item) => item.date === overrideDate)
      ?.revenue_plan_minor,
    15_500_000,
  );

  await page.screenshot({
    path: path.join(screenshotDir, `department-plans-${viewport.name}.png`),
    fullPage: true,
  });

  const suffix = `${viewport.name}-${Date.now()}`;
  const profile = await expectApi(
    page,
    `${prefix}/pay-profiles`,
    {
      method: "POST",
      body: JSON.stringify({
        title: `E2E Percent Tiers ${suffix}`,
        description: "Temporary browser verification profile",
      }),
    },
    "create percent tiers profile",
  );
  const componentTitle = `Бар: многоступенчатый процент ${suffix}`;
  const component = await expectApi(
    page,
    `${prefix}/pay-profiles/${profile.id}/components`,
    {
      method: "POST",
      body: JSON.stringify({
        component_type: "PERCENT_DEPARTMENT_REVENUE",
        title: componentTitle,
        percent_bps: 300,
        department_id: department.id,
        department_ids: [department.id],
        base_scope: "FULL_PERIOD",
        boost_enabled: true,
        boost_source_type: "DEPARTMENT_MONTH_PLAN",
        boost_recalc_mode: "REPLACE_ALL",
        boost_department_id: department.id,
        boost_department_ids: [department.id],
        percent_tiers: [
          { threshold_value: 100, percent_bps: 400 },
          { threshold_value: 110, percent_bps: 500 },
          { threshold_value: 120, percent_bps: 600 },
        ],
      }),
    },
    "create percent tiers component",
  );

  try {
    await page.goto(
      `${frontendBase}/owner-pay-profile.html?venue_id=${venueId}&profile_id=${profile.id}&lang=ru`,
      { waitUntil: "domcontentloaded" },
    );
    await page.locator("#componentsList .listrow").waitFor({
      state: "visible",
      timeout: 20_000,
    });
    const componentRow = page
      .locator("#componentsList .listrow")
      .filter({ hasText: componentTitle });
    await componentRow.locator("button").first().click();
    await page.locator("#editModal.open").waitFor({ state: "visible" });
    assert.equal(
      await page.locator("#f_tier_rows [data-percent-tier]").count(),
      3,
    );
    assert.match(
      await page.locator("#f_tier_preview").textContent(),
      /120%.*6%/,
    );
    const finalRate = page
      .locator("#f_tier_rows [data-percent-tier]")
      .last()
      .locator("[data-tier-percent]");
    await finalRate.fill("6.5");
    assert.match(
      await page.locator("#f_tier_preview").textContent(),
      /120%.*6\.5%/,
    );
    await assertNoHorizontalOverflow(
      page,
      `${viewport.name} percent tier editor`,
    );
    await page.locator("#editModal .modal__panel").evaluate((panel) => {
      panel.scrollTop = 0;
    });
    await page.screenshot({
      path: path.join(
        screenshotDir,
        `percent-tier-editor-${viewport.name}.png`,
      ),
    });
    const componentSaved = page.waitForResponse(
      (response) =>
        response.url() ===
          `${apiBase}${prefix}/pay-components/${component.id}` &&
        response.request().method() === "PATCH" &&
        response.status() === 200,
    );
    await page.locator("#btnSave").click();
    await componentSaved;
    await page.locator("#editModal").waitFor({ state: "hidden" });
    const detail = await expectApi(
      page,
      `${prefix}/pay-profiles/${profile.id}`,
      {},
      "percent tiers profile after editor save",
    );
    const savedComponent = detail.components.find(
      (item) => item.id === component.id,
    );
    assert.deepEqual(
      savedComponent.percent_tiers.map((tier) => [
        Number(tier.threshold_value),
        tier.percent_bps,
      ]),
      [
        [100, 400],
        [110, 500],
        [120, 650],
      ],
    );
  } finally {
    await expectApi(
      page,
      `${prefix}/pay-components/${component.id}`,
      { method: "DELETE" },
      "delete temporary percent tiers component",
    );
    await expectApi(
      page,
      `${prefix}/pay-profiles/${profile.id}`,
      { method: "DELETE" },
      "delete temporary percent tiers profile",
    );
  }
  console.log(`${viewport.name}: department plans and percent tiers passed`);
  return quality;
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
    scenarios.push({
      name: "owner-department-plans",
      quality: await verifyDepartmentPlansAndPercentTiers(
        page,
        venueId,
        viewport,
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
      `${viewport.name}: the complete ${expectedScenarios.length}-scenario suite must run`,
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
        scenarioCount: expectedScenarios.length,
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
