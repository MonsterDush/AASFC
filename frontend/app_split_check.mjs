import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "app.js");
const mainSource = fs.readFileSync(mainPath, "utf8");

const EXPECTED_EXPORTS = `
API_BASE AUTH_PAGE api applyDemoReadonlyCaps applyTelegramTheme applyTheme bootPage buildAuthUrl
cacheSystemRole calculatePayroll can changePassword clearDemoUiState closeModal coerceDemoDate
coerceDemoMonth coerceDemoRange confirmModal confirmPasswordReset createDepartment createKpiMetric
createPayComponent createPayProfile createPayProfileAssignment createPaymentMethod createSelfServiceVenue
createVenuePosition deletePayComponent deletePayProfile deletePayProfileAssignment deleteVenuePosition
downloadFile ensureLogin ensureTelegramWebAppLoaded finalizeTelegramBrowserLink finalizeTelegramBrowserLogin
getActiveVenueId getCachedSystemRole getDemoMonthLabel getDepartments getKpiMetrics getLang getMe
getMyVenuePermissions getMyVenues getPasswordState getPayProfile getPayProfiles getPaymentMethods getPayroll
getPhoneAuthConfig getPhoneCallStatus getStoredDemoUiState getTelegramBrowserLinkStatus
getTelegramBrowserLoginStatus getThemePref getVenueById getVenueMembers getVenuePositionPresets
getVenuePositions getVenueSettings isAuthPage isDemoReadonlyUi isDemoUiMode isSuperAdminCached leaveVenue
linkTelegramAccount loginWithPassword loginWithTelegramWidget logout looksLikeTelegramWebApp mountCommonUI
mountDemoPageTour mountLogo mountNav mountVenueMenu mountVenueSwitcher openModal patchInviteDefaultPosition
readStoredDemoUiState redirectToAuth renderVenueSwitcher reopenDemoTour requestLinkPhoneCall
requestLinkPhoneCode requestPasswordResetCall requestPasswordResetCode requestPhoneCall requestPhoneCode
resetDemoTour setActiveVenueId setLang setPasswordAfterPhoneVerify setThemePref startTelegramBrowserLink
startTelegramBrowserLogin storeDemoUiState t toast trackDemoEvent updateDepartment updateKpiMetric
updatePayComponent updatePayProfile updatePayProfileAssignment updatePaymentMethod updateVenuePosition
updateVenueSettings verifyLinkPhoneCode verifyPhoneCode wa waitForTelegramInitData
`.trim().split(/\s+/).sort();

function exportedNames(source) {
  const names = [];
  for (const match of source.matchAll(/^export\s+(?:async\s+)?function\s+([\w$]+)|^export\s+const\s+(?:\{([^}]+)\}|([\w$]+))/gm)) {
    if (match[1]) names.push(match[1]);
    else if (match[3]) names.push(match[3]);
    else names.push(...match[2].split(",").map((name) => name.trim()).filter(Boolean));
  }
  return names.sort();
}

assert.deepEqual(exportedNames(mainSource), EXPECTED_EXPORTS);
assert.ok(mainSource.split("\n").length < 1_800, "app.js must remain a compatibility facade");

const moduleContracts = [
  ["auth-actions.js", "createAuthActions", ["loginWithTelegramWidget", "verifyPhoneCode", "logout", "linkTelegramAccount"]],
  ["venue-api.js", "createVenueApi", ["getActiveVenueId", "getMe", "getDepartments", "calculatePayroll", "bootPage"]],
  ["navigation.js", "createNavigation", ["renderVenueSwitcher", "getVenueById", "can", "mountNav", "mountVenueMenu"]],
  ["ui-preferences.js", "createUiPreferences", ["getLang", "wa", "applyTheme", "applyTelegramTheme"]],
];
const importedModules = {};
const facadeSources = [mainSource];
for (const [fileName, factoryName] of moduleContracts) {
  const filePath = path.join(frontendDir, "app", fileName);
  const source = fs.readFileSync(filePath, "utf8");
  facadeSources.push(source);
  assert.ok(source.split("\n").length < 500, `${fileName} is too large`);
  const cacheKey = fileName === "navigation.js"
    ? "20260726-navmore1"
    : (fileName === "ui-preferences.js" ? "20260813-assurance2" : "20260719-split1");
  assert.match(mainSource, new RegExp(`/app/${fileName.replace(".", "\\.")}\\?v=${cacheKey}`));
  importedModules[fileName] = await import(pathToFileURL(filePath));
  assert.equal(typeof importedModules[fileName][factoryName], "function");
}

const apiCallManifest = Array.from(
  facadeSources.join("\n").matchAll(/\bapi\(\s*(`[^`]+`|"[^"]+"|'[^']+')/g),
  (match) => match[1],
).sort();
assert.equal(apiCallManifest.length, 71);
assert.equal(
  crypto.createHash("sha256").update(JSON.stringify(apiCallManifest)).digest("hex"),
  "730e3df884e8c91c60f11cea3827462192303fd73f2e6cb04b95bbceec9da097",
);

const authCalls = [];
const auth = importedModules["auth-actions.js"].createAuthActions({
  wa: () => ({ initData: "telegram-init" }),
  api: async (requestPath, options = {}) => { authCalls.push([requestPath, options]); return { ok: true }; },
});
for (const methodName of moduleContracts[0][2]) assert.equal(typeof auth[methodName], "function");
await auth.verifyPhoneCode("+79990000000", "1234", 7);
assert.deepEqual(authCalls.at(-1), ["/auth/phone/verify-code", {
  method: "POST",
  body: { phone: "+79990000000", code: "1234", challenge_id: 7 },
  handle401: false,
}]);
await auth.linkTelegramAccount();
assert.equal(authCalls.at(-1)[1].body.initData, "telegram-init");

const storage = new Map();
globalThis.localStorage = {
  getItem: (key) => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
};
const venueCalls = [];
const venueApi = importedModules["venue-api.js"].createVenueApi({
  api: async (requestPath, options = {}) => {
    venueCalls.push([requestPath, options]);
    if (requestPath === "/me") return { id: 17 };
    return [];
  },
  ensureLogin: async () => ({ ok: true }),
  storeDemoUiState: () => null,
  removeDemoBanner: () => undefined,
  mountDemoBanner: () => undefined,
  maybeTrackDemoPageView: () => undefined,
});
for (const methodName of moduleContracts[1][2]) assert.equal(typeof venueApi[methodName], "function");
venueApi.setActiveVenueId(9);
assert.equal(venueApi.getActiveVenueId(), "9");
await venueApi.getDepartments(9, { includeArchived: true });
assert.equal(venueCalls.at(-1)[0], "/venues/9/departments?include_archived=true");
await venueApi.calculatePayroll(9, "2026-07");
assert.deepEqual(venueCalls.at(-1), ["/venues/9/payroll/calculate", { method: "POST", body: { month: "2026-07" } }]);

const navigation = importedModules["navigation.js"].createNavigation({
  normalizePermList: (value) => Array.isArray(value) ? value : [],
  permSetFromResponse: () => new Set(),
  roleUpper: () => "",
  hasAnyPerm: () => false,
  hasPermPrefix: () => false,
  hasStaffDashboardExtras: () => false,
  t: (key) => key,
  cacheSystemRole: () => undefined,
  applyTheme: () => undefined,
  api: async () => [{ id: 2, name: "Venue" }],
  ensureLogin: async () => ({ ok: true }),
  getActiveVenueId: () => "2",
  setActiveVenueId: () => undefined,
  getMe: async () => ({ id: 17 }),
  getMyVenues: async () => [{ id: 2, name: "Venue" }],
  getMyVenuePermissions: async () => ({ permissions: [] }),
});
for (const methodName of moduleContracts[2][2]) assert.equal(typeof navigation[methodName], "function");
assert.equal(navigation.can("REPORTS_VIEW", { permissions: ["REPORTS_VIEW"] }), true);
assert.deepEqual(await navigation.getVenueById(2), { id: 2, name: "Venue" });
const navigationSource = fs.readFileSync(path.join(frontendDir, "app/navigation.js"), "utf8");
for (const mobileMoreContract of [
  "const mobilePrimaryLinkCount = 3",
  "const overflowLinks = links.slice(mobilePrimaryLinkCount)",
  'button.textContent = t("more")',
  'button.setAttribute("aria-haspopup", "menu")',
  'if (event.key === "Escape" && !menu.hidden)',
]) {
  assert.ok(navigationSource.includes(mobileMoreContract), `navigation lost ${mobileMoreContract}`);
}

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(fullPath);
    return /\.(?:js|mjs|html)$/.test(entry.name) ? [fullPath] : [];
  });
}
let consumerCount = 0;
for (const filePath of sourceFiles(frontendDir)) {
  const source = fs.readFileSync(filePath, "utf8");
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*["']\/app\.js\?v=20260820-i18nmetrika1["']/g)) {
    consumerCount += 1;
    const imported = match[1].split(",").map((entry) => entry.trim().split(/\s+as\s+/)[0]).filter(Boolean);
    for (const name of imported) assert.ok(EXPECTED_EXPORTS.includes(name), `${path.basename(filePath)} imports missing ${name}`);
  }
}
assert.equal(consumerCount, 54);

console.log(`app facade contract: ${EXPECTED_EXPORTS.length} exports, ${consumerCount} consumers`);
