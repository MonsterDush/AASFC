import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const stylesPath = path.join(frontendDir, "styles.css");
const globalStyleCacheKey = "20260722-split1";
const coreStyleFiles = [
  "tokens.css",
  "base-layout.css",
  "controls.css",
  "cards-lists.css",
  "calendar-core.css",
  "utilities.css",
  "calendar-reports.css",
  "finance-components.css",
  "shared-layout.css",
  "overlays-documents.css",
];
const coreStylesDir = path.join(frontendDir, "styles", "core");
const appPath = path.join(frontendDir, "app.js");
const pageLoaderPath = path.join(frontendDir, "page-loader.js");
const htmlPageFiles = fs.readdirSync(frontendDir)
  .filter((fileName) => fileName.endsWith(".html"))
  .sort();
const publicDocumentFiles = [
  "axelio-about.html",
  "axelio-contacts.html",
  "axelio-offer.html",
  "axelio-privacy.html",
  "axelio-subscription.html",
];
const unifiedCatalogFiles = [
  "owner-departments.js",
  "owner-expense-categories.js",
  "owner-kpi.js",
  "owner-pay-profiles.js",
  "owner-payment-methods.js",
  "owner-suppliers.js",
];
const extractedPageStyles = new Map([
  ["admin-billing.html", "styles/pages/admin-billing.css"],
  ["admin-demo-analytics.html", "styles/pages/admin-demo-analytics.css"],
  ["admin-demo.html", "styles/pages/admin-demo.css"],
  ["admin-invites.html", "styles/pages/invites.css"],
  ["admin-position-templates.html", "styles/pages/admin-position-templates.css"],
  ["app-adjustments.html", "styles/pages/app-adjustments.css"],
  ["app-venue.html", "styles/pages/app-venue.css"],
  ["app-venues.html", "styles/pages/app-venues.css"],
  ["auth.html", "styles/pages/auth.css"],
  ["invite-accept.html", "styles/pages/invites.css"],
  ["invites.html", "styles/pages/invites.css"],
  ["owner-economics-plans.html", "styles/pages/finance-pages.css"],
  ["owner-expenses.html", "styles/pages/finance-pages.css"],
  ["owner-finance-ledger.html", "styles/pages/finance-pages.css"],
  ["owner-pay-profile.html", "styles/pages/owner-pay-profile.css"],
  ["owner-payroll.html", "styles/pages/finance-pages.css"],
  ["owner-recurring-expenses.html", "styles/pages/finance-pages.css"],
  ["owner-subscription.html", "styles/pages/owner-subscription.css"],
  ["owner-summary.html", "styles/pages/finance-pages.css"],
  ["owner-setup.html", "styles/pages/owner-setup.css"],
  ["owner-tip-settings.html", "styles/pages/owner-tip-settings.css"],
  ["owner-turnover.html", "styles/pages/finance-pages.css"],
  ["positions.html", "styles/pages/positions.css"],
  ["profile.html", "styles/pages/profile.css"],
  ["shift-schedule-templates.html", "styles/pages/shift-schedule-templates.css"],
  ["staff-adjustments.html", "styles/pages/staff-adjustments.css"],
  ["staff-report.html", "styles/pages/staff-report.css"],
  ["staff-salary.html", "styles/pages/staff-salary.css"],
  ["staff-shifts.html", "styles/pages/staff-shifts.css"],
]);
const pageStyleCacheKeyOverrides = new Map([
  ["admin-demo-analytics.html", "20260722-dynamic1"],
  ["admin-position-templates.html", "20260720-unified8"],
  ["owner-economics-plans.html", "20260720-unified9"],
  ["owner-expenses.html", "20260720-unified9"],
  ["owner-finance-ledger.html", "20260720-unified9"],
  ["owner-payroll.html", "20260720-unified9"],
  ["owner-recurring-expenses.html", "20260720-unified9"],
  ["owner-setup.html", "20260720-unified10"],
  ["owner-summary.html", "20260720-unified9"],
  ["owner-turnover.html", "20260720-unified9"],
  ["staff-adjustments.html", "20260720-unified8"],
]);
const inlineFreePages = [
  "admin-position-templates.html",
  "app-venue.html",
  "app-venues.html",
  "owner-economics-plans.html",
  "owner-expenses.html",
  "owner-finance-ledger.html",
  "owner-payroll.html",
  "owner-recurring-expenses.html",
  "owner-setup.html",
  "owner-summary.html",
  "owner-turnover.html",
  "shift-intervals.html",
  "staff-adjustments.html",
];
const inlineFreeEntrypoints = new Map([
  ["admin-position-templates.html", "/admin-position-templates.js?v=20260720-unified8"],
  ["owner-economics-plans.html", "/owner-economics-plans.js?v=20260720-unified9"],
  ["owner-expenses.html", "/owner-expenses.js?v=20260720-unified9"],
  ["owner-finance-ledger.html", "/owner-finance-ledger.js?v=20260720-unified9"],
  ["owner-payroll.html", "/owner-payroll.js?v=20260720-unified9"],
  ["owner-recurring-expenses.html", "/owner-recurring-expenses.js?v=20260720-unified9"],
  ["owner-setup.html", "/owner-setup.js?v=20260722-dynamic1"],
  ["owner-summary.html", "/owner-summary.js?v=20260720-unified9"],
  ["owner-turnover.html", "/owner-turnover.js?v=20260720-unified9"],
  ["shift-intervals.html", "/shift-intervals.js?v=20260720-unified8"],
  ["staff-adjustments.html", "/staff-adjustments.js?v=20260720-unified8"],
]);
const inlineFreeModules = [
  "admin-position-templates.js",
  "app-adjustments.js",
  "owner-economics-plans.js",
  "owner-expenses.js",
  "owner-finance-ledger.js",
  "owner-pay-profile.js",
  "owner-pay-profile/assignment-controller.js",
  "owner-pay-profile/component-controller.js",
  "owner-pay-profile/component-form.js",
  "owner-pay-profile/component-list.js",
  "owner-pay-profile/component-support.js",
  "owner-payroll.js",
  "owner-recurring-expenses.js",
  "owner-setup.js",
  "owner-setup/catalog-editor.js",
  "owner-setup/invite-editor.js",
  "owner-setup/pay-profile-editor.js",
  "owner-setup/position-editor.js",
  "owner-setup/recurring-expense-editor.js",
  "owner-setup/shift-interval-editor.js",
  "owner-setup/supplier-editor.js",
  "owner-summary.js",
  "owner-turnover.js",
  "positions.js",
  "positions/invite-controller.js",
  "positions/permission-controller.js",
  "positions/position-domain.js",
  "positions/position-editor.js",
  "positions/position-list.js",
  "shift-schedule-templates.js",
  "shift-intervals.js",
  "staff-adjustments.js",
  "staff-report.js",
];
const allowedInlineStyleAttributes = new Map([
  ["admin-demo-analytics.html", [' style="--fill-width:${fillPercent(row?.[valueKey], max)}%"']],
  ["staff-salary.js", [' style="--h:${h}%;--barColor:${barColor}"']],
  ["staff-shifts.js", [
    ' style="--interval-color:${escapeHtml(c)}"',
    ' style="--interval-color:${escapeHtml(intColor)}"',
  ]],
  ["staff-shifts/calendar-controller.js", [
    ' style="--left:${it.leftPct}%;--w:${it.widthPct}%;--line-rgb:${it.rgb}"',
  ]],
]);
const allowedStyleSetProperties = new Map([
  ["staff-shifts.js", [
    "--filter-menu-width",
    "--filter-menu-max-width",
    "--filter-menu-left",
    "--filter-menu-top",
  ]],
  ["staff-shifts/calendar-controller.js", ["--line-rgb", "--dot"]],
]);
const stylesManifestSource = fs.readFileSync(stylesPath, "utf8");
const coreStyleSources = new Map(coreStyleFiles.map((fileName) => [
  fileName,
  fs.readFileSync(path.join(coreStylesDir, fileName), "utf8"),
]));
const stylesSource = Array.from(coreStyleSources.values()).join("");
const appSource = fs.readFileSync(appPath, "utf8");
const pageLoaderSource = fs.readFileSync(pageLoaderPath, "utf8");

function countRule(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return Array.from(source.matchAll(new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{`, "g"))).length;
}

function countTopLevelRule(source, selector) {
  let count = 0;
  let depth = 0;
  let preludeStart = 0;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") {
      const prelude = source.slice(preludeStart, index).replace(/\/\*[\s\S]*?\*\//g, "").trim();
      if (depth === 0 && prelude === selector) count += 1;
      depth += 1;
      preludeStart = index + 1;
    } else if (char === "}") {
      depth -= 1;
      preludeStart = index + 1;
    }
  }
  return count;
}

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(fullPath);
    return /\.(?:html|js)$/.test(entry.name) ? [fullPath] : [];
  });
}

const manifestImports = Array.from(
  stylesManifestSource.matchAll(/@import url\("([^"]+)"\);/g),
  (match) => match[1],
);
assert.deepEqual(
  fs.readdirSync(coreStylesDir).filter((fileName) => fileName.endsWith(".css")).sort(),
  [...coreStyleFiles].sort(),
  "styles/core contains an unregistered module",
);
assert.deepEqual(
  manifestImports,
  coreStyleFiles.map((fileName) => `/styles/core/${fileName}?v=${globalStyleCacheKey}`),
  "styles.css core import order or cache key changed",
);
assert.equal(
  stylesManifestSource
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/@import url\("[^"]+"\);/g, "")
    .trim(),
  "",
  "styles.css must remain an import-only manifest",
);
for (const [fileName, source] of coreStyleSources) {
  assert.equal(
    Array.from(source).filter((char) => char === "{").length,
    Array.from(source).filter((char) => char === "}").length,
    `styles/core/${fileName} has unbalanced braces`,
  );
  assert.ok(source.split("\n").length < 500, `styles/core/${fileName} unexpectedly grew`);
  assert.doesNotMatch(source, /@import\b/, `styles/core/${fileName} must not import another module`);
}
for (const pageStylePath of new Set(extractedPageStyles.values())) {
  const source = fs.readFileSync(path.join(frontendDir, pageStylePath), "utf8");
  assert.equal(
    Array.from(source).filter((char) => char === "{").length,
    Array.from(source).filter((char) => char === "}").length,
    `${pageStylePath} has unbalanced braces`,
  );
}
assert.ok(stylesSource.split("\n").length < 1_850, "global style modules unexpectedly grew");
assert.ok(stylesManifestSource.split("\n").length < 30, "styles.css manifest unexpectedly grew");
assert.ok(appSource.split("\n").length < 1_600, "app.js regained runtime style payloads");
assert.ok(pageLoaderSource.split("\n").length < 180, "page-loader.js unexpectedly grew");

assert.equal(htmlPageFiles.length, 50, "every frontend HTML page must use the global loader");
for (const fileName of htmlPageFiles) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.ok(
    source.includes('<script src="/page-loader.js?v=20260720-loader1"></script>'),
    `${fileName} page loader cache key is stale`,
  );
  assert.ok(
    source.includes(`href="/styles.css?v=${globalStyleCacheKey}"`),
    `${fileName} global stylesheet cache key is stale`,
  );
}
for (const contract of [
  "window.fetch = function",
  "MutationObserver",
  "HARD_TIMEOUT_MS",
  "axelio:page-ready",
  "prefers-reduced-motion",
]) {
  const contractSource = contract === "prefers-reduced-motion" ? stylesSource : pageLoaderSource;
  assert.ok(contractSource.includes(contract), `page loader lost ${contract}`);
}
assert.doesNotMatch(pageLoaderSource, /(?:\sstyle\s*=|\.style\b)/i, "page loader must use shared CSS classes");

assert.doesNotMatch(appSource, /ensureDemoTourStyles|demoTourRuntimeStyles/);
assert.doesNotMatch(appSource, /\.demo-tour-overlay\s*\{/);
assert.equal(countRule(stylesSource, ".demo-tour-overlay"), 2);

const demoTourStart = stylesSource.indexOf(".demo-tour-overlay{");
const demoTourEnd = stylesSource.indexOf(".badge.as-link", demoTourStart);
assert.ok(demoTourStart >= 0 && demoTourEnd > demoTourStart, "demo tour CSS block is missing");
const normalizedDemoTourCss = stylesSource.slice(demoTourStart, demoTourEnd).replace(/\s+/g, "");
assert.equal(
  crypto.createHash("sha256").update(normalizedDemoTourCss).digest("hex"),
  "7d3fe0071ca4246b83ab7320cc68c13df723eec1ce331dcee40d5994f4f75f7f",
);

for (const selector of [
  "a.link",
  ".btn",
  ".card",
  ".row",
  ".stack",
  ".modal",
  ".modal__panel",
  ".modal__head",
  ".modal__title",
  ".hidden",
  ".page-loader",
  ".page-loader.is-visible",
  ".page-loader.is-leaving",
  ".page-loader__panel",
  ".page-loader__spinner",
  ".page-loader__title",
  ".page-loader__hint",
  ".flex-none",
  ".mt-4",
  ".mt-6",
  ".mt-8",
  ".mt-10",
  ".mt-12",
  ".mb-4",
  ".mb-6",
  ".gap-8",
  ".gap-6",
  ".gap-10",
  ".gap-12",
  ".ai-start",
  ".row--between",
  ".row--end",
  ".payroll-breakdown",
  ".summary-list-row",
  ".summary-list-value",
  ".screen-hero__actions .economics-date-picker",
]) {
  assert.equal(countTopLevelRule(stylesSource, selector), 1, `${selector} must have one canonical rule`);
}

for (const selector of [
  ".doc-wrap",
  ".doc-card",
  ".doc-head",
  ".doc-actions",
  ".doc-meta",
  ".doc-kv",
  ".doc-note",
  ".admin-venues-page .toolbar",
  ".admin-venues-page .card",
  ".admin-venues-page .row",
  ".admin-venues-page .tag",
]) {
  assert.equal(countRule(stylesSource, selector), 1, `${selector} must have one shared rule`);
}

for (const fileName of publicDocumentFiles) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.doesNotMatch(source, /<style\b/i, `${fileName} must use shared document styles`);
}

const adminVenuesSource = fs.readFileSync(path.join(frontendDir, "admin-venues.html"), "utf8");
assert.match(adminVenuesSource, /<body class="admin-venues-page">/);
assert.doesNotMatch(adminVenuesSource, /<style\b/i);

const ownerSetupSource = fs.readFileSync(path.join(frontendDir, "owner-setup.html"), "utf8");
assert.doesNotMatch(ownerSetupSource, /var\(--line\b/, "owner setup must use the shared border token");

for (const [htmlFileName, pageStylePath] of extractedPageStyles) {
  const htmlSource = fs.readFileSync(path.join(frontendDir, htmlFileName), "utf8");
  assert.doesNotMatch(htmlSource, /<style\b/i, `${htmlFileName} must not contain embedded CSS`);
  const inlineAttributes = Array.from(
    htmlSource.matchAll(/\sstyle\s*=\s*["'][^"']*["']/gi),
    (match) => match[0],
  );
  assert.deepEqual(
    inlineAttributes,
    allowedInlineStyleAttributes.get(htmlFileName) || [],
    `${htmlFileName} contains an unapproved inline style`,
  );
  const pageStyleCacheKey = pageStyleCacheKeyOverrides.get(htmlFileName) || "20260720-unified7";
  assert.ok(
    htmlSource.includes(`href="/${pageStylePath}?v=${pageStyleCacheKey}"`),
    `${htmlFileName} page stylesheet cache key is stale`,
  );
}

for (const fileName of inlineFreePages) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.doesNotMatch(source, /(?:<style\b|\sstyle\s*=|\.style\b)/i, `${fileName} regained inline CSS`);
}

for (const [htmlFileName, entrypoint] of inlineFreeEntrypoints) {
  const source = fs.readFileSync(path.join(frontendDir, htmlFileName), "utf8");
  assert.ok(source.includes(`src="${entrypoint}"`), `${htmlFileName} entrypoint cache key is stale`);
}

for (const fileName of inlineFreeModules) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.doesNotMatch(source, /(?:<style\b|\sstyle\s*=|\.style\b)/i, `${fileName} regained inline CSS`);
}

const staffSalarySource = fs.readFileSync(path.join(frontendDir, "staff-salary.js"), "utf8");
assert.deepEqual(
  Array.from(staffSalarySource.matchAll(/\sstyle\s*=\s*["'][^"']*["']/gi), (match) => match[0]),
  allowedInlineStyleAttributes.get("staff-salary.js"),
  "staff-salary.js may only keep runtime chart variables",
);
assert.doesNotMatch(staffSalarySource, /\.style\b/, "staff-salary.js must use classes for visibility and layout");

const staffShiftsSource = fs.readFileSync(path.join(frontendDir, "staff-shifts.js"), "utf8");
assert.deepEqual(
  Array.from(staffShiftsSource.matchAll(/\sstyle\s*=\s*["'][^"']*["']/gi), (match) => match[0]),
  allowedInlineStyleAttributes.get("staff-shifts.js"),
  "staff-shifts.js may only keep runtime interval colors",
);
assert.deepEqual(
  Array.from(staffShiftsSource.matchAll(/\.style\.setProperty\(\s*["']([^"']+)/g), (match) => match[1]),
  allowedStyleSetProperties.get("staff-shifts.js"),
  "staff-shifts.js may only set approved filter-menu variables",
);

const staffCalendarSource = fs.readFileSync(path.join(frontendDir, "staff-shifts/calendar-controller.js"), "utf8");
assert.deepEqual(
  Array.from(staffCalendarSource.matchAll(/\sstyle\s*=\s*["'][^"']*["']/gi), (match) => match[0]),
  allowedInlineStyleAttributes.get("staff-shifts/calendar-controller.js"),
  "calendar-controller.js may only keep runtime timeline geometry and color",
);
assert.deepEqual(
  Array.from(staffCalendarSource.matchAll(/\.style\.setProperty\(\s*["']([^"']+)/g), (match) => match[1]),
  allowedStyleSetProperties.get("staff-shifts/calendar-controller.js"),
  "calendar-controller.js may only set runtime CSS variables",
);

for (const runtimeCssContract of [
  "background:var(--interval-color,var(--muted))",
  "top:var(--filter-menu-top,0)",
  "left:var(--filter-menu-left,0)",
  "width:var(--filter-menu-width",
  "max-width:var(--filter-menu-max-width",
  "left:var(--left)",
  "width:var(--w)",
  "height:var(--h,0%)",
  "background:var(--barColor,var(--accent))",
  "border:2px solid var(--dot, var(--muted))",
]) {
  assert.ok(stylesSource.includes(runtimeCssContract), `styles.css lost ${runtimeCssContract}`);
}
const analyticsStyles = fs.readFileSync(path.join(frontendDir, "styles/pages/admin-demo-analytics.css"), "utf8");
assert.ok(analyticsStyles.includes("width:var(--fill-width,0)"), "analytics bars lost their runtime width variable");

for (const fileName of unifiedCatalogFiles) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.doesNotMatch(source, /(?:\sstyle\s*=|\.style\s*=)/, `${fileName} regained inline layout styles`);
  const htmlSource = fs.readFileSync(path.join(frontendDir, fileName.replace(/\.js$/, ".html")), "utf8");
  assert.ok(
    htmlSource.includes(`src="/${fileName}?v=20260722-dynamic1"`),
    `${fileName} cache key is stale`,
  );
}

for (const token of [
  "--statusWarningBg",
  "--statusWarningBorder",
  "--statusErrorBg",
  "--statusErrorBorder",
  "--statusSuccessBg",
  "--statusSuccessBorder",
  "--surfaceTint",
  "--surfaceTintSoft",
  "--surfaceTintStrong",
]) {
  assert.ok(stylesSource.includes(`${token}:`), `${token} is missing`);
}

for (const selector of [
  ".notif-state-banner--warn",
  ".notif-badge--err",
  ".notif-badge--wait",
  ".notif-history-error",
  ".payroll-chip--warn",
]) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = stylesSource.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
  assert.ok(rule, `${selector} is missing`);
  assert.match(rule[1], /var\(--status/);
}

let inlineStyleCount = 0;
let embeddedStyleBlockCount = 0;
let embeddedStyleLineCount = 0;
const cssHrefVariants = new Set();

for (const filePath of sourceFiles(frontendDir)) {
  const source = fs.readFileSync(filePath, "utf8");
  const relativePath = path.relative(frontendDir, filePath).split(path.sep).join("/");
  const inlineStyleAttributes = Array.from(
    source.matchAll(/\sstyle\s*=\s*["'][^"']*["']/gi),
    (match) => match[0],
  );
  inlineStyleCount += inlineStyleAttributes.length;
  assert.deepEqual(
    inlineStyleAttributes,
    allowedInlineStyleAttributes.get(relativePath) || [],
    `${relativePath} contains an unapproved inline style`,
  );

  const setProperties = Array.from(
    source.matchAll(/\.style\.setProperty\(\s*["']([^"']+)/g),
    (match) => match[1],
  );
  assert.deepEqual(
    setProperties,
    allowedStyleSetProperties.get(relativePath) || [],
    `${relativePath} sets an unapproved runtime style property`,
  );
  const directStyleProperties = Array.from(
    source.matchAll(/\.style\.([A-Za-z_$][\w$]*)/g),
    (match) => match[1],
  ).filter((property) => property !== "setProperty");
  assert.deepEqual(directStyleProperties, [], `${relativePath} must use classes or approved CSS variables`);
  assert.doesNotMatch(
    source,
    /(?:\.style\s*\[|\.cssText\b|setAttribute\(\s*["']style["'])/,
    `${relativePath} bypasses the runtime style allowlist`,
  );

  if (filePath.endsWith(".html")) {
    for (const match of source.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) {
      embeddedStyleBlockCount += 1;
      embeddedStyleLineCount += match[1].split("\n").length;
    }
    for (const match of source.matchAll(/href=["'](\/styles\.css[^"']*)["']/g)) {
      cssHrefVariants.add(match[1]);
    }
  }
}

const approvedInlineStyleCount = Array.from(allowedInlineStyleAttributes.values())
  .reduce((total, attributes) => total + attributes.length, 0);
assert.equal(inlineStyleCount, approvedInlineStyleCount, "dynamic inline style count changed");
assert.equal(embeddedStyleBlockCount, 0, "embedded style blocks are forbidden");
assert.equal(embeddedStyleLineCount, 0, "embedded style lines are forbidden");
assert.deepEqual([...cssHrefVariants], [`/styles.css?v=${globalStyleCacheKey}`]);

console.log(
  `style contract: ${stylesSource.split("\n").length - 1} CSS lines in ${coreStyleFiles.length} modules, `
  + `${inlineStyleCount} inline styles, ${embeddedStyleBlockCount} embedded blocks / `
  + `${embeddedStyleLineCount} lines, ${cssHrefVariants.size} cache variant`,
);
