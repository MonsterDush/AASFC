import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "owner-pay-profile.js");
const htmlPath = path.join(frontendDir, "owner-pay-profile.html");
const moduleDir = path.join(frontendDir, "owner-pay-profile");
const moduleFiles = [
  "component-support.js",
  "component-form.js",
  "component-controller.js",
  "component-list.js",
  "assignment-controller.js",
];
const mainSource = fs.readFileSync(mainPath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");
const moduleSources = Object.fromEntries(
  moduleFiles.map((fileName) => [fileName, fs.readFileSync(path.join(moduleDir, fileName), "utf8")]),
);
const combinedSource = [mainSource, ...Object.values(moduleSources)].join("\n");
const manifestHash = (values) => crypto.createHash("sha256").update(JSON.stringify(values)).digest("hex");

const appCalls = [
  "applyTelegramTheme",
  "ensureLogin",
  "mountNav",
  "mountCommonUI",
  "setActiveVenueId",
  "getMe",
  "getMyVenuePermissions",
  "getVenueMembers",
  "getDepartments",
  "getKpiMetrics",
  "getPayProfile",
  "updatePayProfile",
  "createPayProfileAssignment",
  "updatePayProfileAssignment",
  "deletePayProfileAssignment",
  "createPayComponent",
  "updatePayComponent",
  "deletePayComponent",
  "applyDemoReadonlyCaps",
];
const apiCallManifest = appCalls.flatMap((name) => (
  Array.from(combinedSource.matchAll(new RegExp(`\\b${name}\\s*\\(`, "g")), () => name)
)).sort();
const domBindingManifest = Array.from(
  combinedSource.matchAll(/getElementById\(\s*["']([^"']+)["']\s*\)/g),
  (match) => match[1],
).sort();
const listenerManifest = Array.from(
  combinedSource.matchAll(/addEventListener\(\s*["']([^"']+)["']/g),
  (match) => match[1],
).sort();

assert.equal(apiCallManifest.length, 20);
assert.equal(manifestHash(apiCallManifest), "740b80bd7e581f6142f8e4a9eeb14d332016a8f1ef3c1d10773d4a9d6ccfa98f");
assert.equal(domBindingManifest.length, 165);
assert.equal(manifestHash(domBindingManifest), "9404da1e4dace6750e7aa26001c824071e135d37cb4d608bc8c00bb5523c07df");
assert.equal(listenerManifest.length, 26);
assert.equal(manifestHash(listenerManifest), "92cedc960ff5c6e5d8f9b52b179c1850c27fc11e4772e9ef585b171ea7bc67f6");

assert.ok(mainSource.split("\n").length < 450, "owner-pay-profile.js should remain an orchestration module");
const sizeLimits = {
  "component-support.js": 550,
  "component-form.js": 350,
  "component-controller.js": 650,
  "component-list.js": 180,
  "assignment-controller.js": 220,
};
for (const [fileName, limit] of Object.entries(sizeLimits)) {
  assert.ok(moduleSources[fileName].split("\n").length < limit, `${fileName} is too large`);
  const cacheKey = fileName === "assignment-controller.js" ? "20260723-functional1" : "20260720-unified7";
  assert.match(mainSource, new RegExp(`/owner-pay-profile/${fileName.replace(".", "\\.")}\\?v=${cacheKey}`));
}
assert.match(htmlSource, /owner-pay-profile\.js\?v=20260726-navmore1/);

const state = {
  can: { view: true, manage: true },
  venueId: "7",
  profileId: "11",
  profile: { components: [], assignments: [] },
  departments: [{ id: 1, title: "Бар" }, { id: 2, title: "Кухня" }],
  kpiMetrics: [{ id: 5, title: "Отзывы", unit: "QTY" }],
  members: [],
};
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
const noop = () => undefined;
const asyncNoop = async () => undefined;

const supportModule = await import(pathToFileURL(path.join(moduleDir, "component-support.js")));
assert.equal(typeof supportModule.createPayComponentSupport, "function");
const support = supportModule.createPayComponentSupport({ state, esc });
assert.equal(support.parseMoneyRubToMinor("1 234,56"), 123456);
assert.equal(support.parseMoneyRubToMinor("-1"), null);
assert.equal(support.parsePercentInputToBps("7,5"), 750);
assert.deepEqual(
  support.selectedDepartmentIdsFor({ department_id: 1, department_ids: [2, 2, 0] }),
  [1, 2],
);
assert.match(
  support.formatPercentConfig({
    component_type: "PERCENT_DEPARTMENT_REVENUE",
    percent_bps: 500,
    department_ids: [2],
    boost_enabled: false,
  }),
  /5,00%.*по отработанным дням/,
);

const formModule = await import(pathToFileURL(path.join(moduleDir, "component-form.js")));
const { componentForm } = formModule.createPayComponentFormRenderer({ state, esc, support });
const formHtml = componentForm({
  mode: "edit",
  item: { component_type: "PERCENT_DEPARTMENT_REVENUE", department_ids: [2], percent_bps: 750, is_active: true },
});
for (const fieldId of [
  "f_component_type",
  "f_department_id",
  "f_base_scope",
  "f_boost_enabled",
  "f_kpi_metric_id",
  "f_steps_rows",
  "btnSave",
]) {
  assert.ok(formHtml.includes(`id="${fieldId}"`), `${fieldId} is missing from the component form`);
}
assert.match(formHtml, /option value="2" selected>Кухня<\/option>/);

const componentControllerModule = await import(pathToFileURL(path.join(moduleDir, "component-controller.js")));
const componentController = componentControllerModule.createPayComponentController({
  state,
  esc,
  support,
  componentForm,
  openEditModal: noop,
  closeEditModal: noop,
  toast: noop,
  createPayComponent: asyncNoop,
  updatePayComponent: asyncNoop,
  load: asyncNoop,
});
assert.equal(typeof componentController.openComponentEditor, "function");

const componentListModule = await import(pathToFileURL(path.join(moduleDir, "component-list.js")));
const componentList = componentListModule.createPayComponentList({
  state,
  esc,
  support,
  openComponentEditor: noop,
  updatePayComponent: asyncNoop,
  deletePayComponent: asyncNoop,
  toast: noop,
  confirmModal: async () => true,
  load: asyncNoop,
});
assert.equal(typeof componentList.renderComponents, "function");

const assignmentModule = await import(pathToFileURL(path.join(moduleDir, "assignment-controller.js")));
const assignmentController = assignmentModule.createPayAssignmentController({
  state,
  esc,
  memberName: () => "Сотрудник",
  openEditModal: noop,
  closeEditModal: noop,
  toast: noop,
  confirmModal: async () => true,
  createPayProfileAssignment: asyncNoop,
  updatePayProfileAssignment: asyncNoop,
  deletePayProfileAssignment: asyncNoop,
  load: asyncNoop,
});
assert.equal(typeof assignmentController.renderAssignments, "function");
assert.equal(typeof assignmentController.openAssignmentEditor, "function");
state.members = [{ user_id: 17, phone: "+79990000999", display_name: "+79990000999" }];
assert.deepEqual(
  assignmentController.resolveAssignmentMember({
    member_user_id: 17,
    member: { user_id: 17, short_name: null, full_name: null, tg_username: null },
  }),
  {
    user_id: 17,
    short_name: null,
    full_name: null,
    tg_username: null,
    phone: "+79990000999",
    display_name: "+79990000999",
  },
);

console.log(`owner pay profile split contract: ${moduleFiles.length} modules, ${apiCallManifest.length} API calls, ${domBindingManifest.length} DOM bindings`);
