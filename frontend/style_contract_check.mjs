import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const stylesPath = path.join(frontendDir, "styles.css");
const appPath = path.join(frontendDir, "app.js");
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
const stylesSource = fs.readFileSync(stylesPath, "utf8");
const appSource = fs.readFileSync(appPath, "utf8");

function countRule(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return Array.from(source.matchAll(new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{`, "g"))).length;
}

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(fullPath);
    return /\.(?:html|js)$/.test(entry.name) ? [fullPath] : [];
  });
}

assert.equal(
  Array.from(stylesSource).filter((char) => char === "{").length,
  Array.from(stylesSource).filter((char) => char === "}").length,
  "styles.css has unbalanced braces",
);
assert.ok(stylesSource.split("\n").length < 1_850, "styles.css unexpectedly grew");
assert.ok(appSource.split("\n").length < 1_600, "app.js regained runtime style payloads");

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

for (const selector of ["a.link", ".mt-6", ".mt-8", ".mt-12", ".payroll-breakdown"]) {
  assert.equal(countRule(stylesSource, selector), 1, `${selector} must have one canonical rule`);
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

for (const fileName of unifiedCatalogFiles) {
  const source = fs.readFileSync(path.join(frontendDir, fileName), "utf8");
  assert.doesNotMatch(source, /(?:\sstyle\s*=|\.style\s*=)/, `${fileName} regained inline layout styles`);
  const htmlSource = fs.readFileSync(path.join(frontendDir, fileName.replace(/\.js$/, ".html")), "utf8");
  assert.ok(
    htmlSource.includes(`src="/${fileName}?v=20260720-unified4"`),
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
  inlineStyleCount += Array.from(source.matchAll(/style\s*=\s*["'][^"']*["']/gi)).length;

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

assert.ok(inlineStyleCount <= 409, `inline style budget exceeded: ${inlineStyleCount}`);
assert.ok(embeddedStyleBlockCount <= 14, `embedded style block budget exceeded: ${embeddedStyleBlockCount}`);
assert.ok(embeddedStyleLineCount <= 361, `embedded style line budget exceeded: ${embeddedStyleLineCount}`);
assert.deepEqual([...cssHrefVariants], ["/styles.css?v=20260720-unified4"]);

console.log(
  `style contract: ${stylesSource.split("\n").length - 1} CSS lines, `
  + `${inlineStyleCount} inline styles, ${embeddedStyleBlockCount} embedded blocks / `
  + `${embeddedStyleLineCount} lines, ${cssHrefVariants.size} cache variant`,
);
