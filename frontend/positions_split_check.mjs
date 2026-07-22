import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "positions.js");
const htmlPath = path.join(frontendDir, "positions.html");
const moduleDir = path.join(frontendDir, "positions");
const moduleFiles = [
  "permission-controller.js",
  "position-domain.js",
  "position-editor.js",
  "position-list.js",
  "invite-controller.js",
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
  "bootPage",
  "mountNav",
  "mountCommonUI",
  "setActiveVenueId",
  "getMyVenuePermissions",
  "getVenueMembers",
  "getVenuePositions",
  "getVenuePositionPresets",
  "getPayProfiles",
  "createVenuePosition",
  "updateVenuePosition",
  "deleteVenuePosition",
  "patchInviteDefaultPosition",
  "isDemoUiMode",
];
const apiCallManifest = appCalls.flatMap((name) => (
  Array.from(combinedSource.matchAll(new RegExp(`\\b${name}\\s*\\(`, "g")), () => name)
));
apiCallManifest.push(...Array.from(
  combinedSource.matchAll(/\bapi\(\s*["']([^"']+)["']/g),
  (match) => `api:${match[1]}`,
));
apiCallManifest.sort();
const uniqueDomBindings = Array.from(new Set(Array.from(
  combinedSource.matchAll(/getElementById\(\s*["']([^"']+)["']\s*\)/g),
  (match) => match[1],
))).sort();
const uniqueListenerTypes = Array.from(new Set(Array.from(
  combinedSource.matchAll(/addEventListener\(\s*["']([^"']+)["']/g),
  (match) => match[1],
))).sort();

assert.equal(apiCallManifest.length, 20);
assert.equal(manifestHash(apiCallManifest), "b861a78fdff7f0e52e6fd27d9ab810987def1f881d161d797ab911089cd3fdb4");
assert.equal(uniqueDomBindings.length, 24);
assert.equal(manifestHash(uniqueDomBindings), "89418c6feadceb6630a4459fe539d97e8cbfc5b21284a7378cb9eb471b3d9f4b");
assert.deepEqual(uniqueListenerTypes, ["change", "click"]);

assert.ok(mainSource.split("\n").length < 420, "positions.js should remain an orchestration module");
const moduleContracts = {
  "permission-controller.js": ["createPositionPermissionController", 320],
  "position-domain.js": ["createPositionDomain", 240],
  "position-editor.js": ["createPositionEditor", 520],
  "position-list.js": ["createPositionList", 180],
  "invite-controller.js": ["createPositionInviteController", 150],
};
for (const [fileName, [factoryName, lineLimit]] of Object.entries(moduleContracts)) {
  assert.ok(moduleSources[fileName].split("\n").length < lineLimit, `${fileName} is too large`);
  assert.match(moduleSources[fileName], new RegExp(`export function ${factoryName}\\b`));
  const cacheKey = fileName === "permission-controller.js"
    ? "20260722-dynamic1"
    : (["position-editor.js", "position-list.js"].includes(fileName) ? "20260723-functional1" : "20260720-unified6");
  assert.match(mainSource, new RegExp(`/positions/${fileName.replace(".", "\\.")}\\?v=${cacheKey}`));
}
assert.match(htmlSource, /positions\.js\?v=20260723-functional1/);
assert.match(moduleSources["permission-controller.js"], /position-template-ui\.js\?v=20260722-dynamic1/);

const state = {
  venueId: "7",
  members: [{ user_id: 17, full_name: "Иванов Иван Иванович", tg_username: "ivan" }],
  positions: [],
  positionPresets: [],
  payProfiles: [{ id: 3, title: "Основной", components_count: 2, is_active: true }],
  permissionsCatalog: [{
    key: "shifts",
    title: "Смены",
    hint: "",
    items: [{ code: "SHIFTS_VIEW", title: "Просмотр", description: "" }],
  }],
  permissionTemplates: [],
};
const auth = {
  canManage: true,
  canManagePerms: true,
  canAssign: true,
};
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
const noop = () => undefined;
const asyncNoop = async () => undefined;

const domainModule = await import(pathToFileURL(path.join(moduleDir, "position-domain.js")));
const domain = domainModule.createPositionDomain({ state });
assert.deepEqual(domain.parsePermCodes('["SHIFTS_VIEW", "SHIFTS_MANAGE"]'), ["SHIFTS_VIEW", "SHIFTS_MANAGE"]);
assert.equal(domain.memberLabel(state.members[0]), "Иванов И.И. · @ivan");
assert.equal(domain.posReportsEnabled({ permission_codes: ["REPORTS_VIEW_DAILY"] }), true);
assert.equal(domain.posScheduleManage({ permission_codes: ["SHIFTS_VIEW"] }), false);
assert.deepEqual(
  domain.normalizePositions({ positions: [{ id: 9, pay_profile_id: "3", permission_codes: '["SHIFTS_VIEW"]' }] }),
  [{ id: 9, pay_profile_id: 3, permission_codes: ["SHIFTS_VIEW"] }],
);

const permissions = {
  buildDefaultPermissionsCatalog: () => state.permissionsCatalog,
  ensurePermissionsCatalog: async () => state.permissionsCatalog,
  ensurePermissionTemplates: async () => [],
  renderPermissionTemplateSelect: () => '<option value="">—</option>',
  renderTemplateSummaryBlock: () => "Шаблон не выбран",
  applyPermissionTemplateToModal: () => true,
};
let createdPosition = null;
let updatedPosition = null;
const editorModule = await import(pathToFileURL(path.join(moduleDir, "position-editor.js")));
const editor = editorModule.createPositionEditor({
  state,
  auth,
  esc,
  domain,
  permissions,
  openPosModal: noop,
  closePosModal: noop,
  toast: noop,
  confirmModal: async () => true,
  createVenuePosition: async (venueId, payload) => { createdPosition = { venueId, payload }; },
  updateVenuePosition: async (venueId, positionId, payload) => { updatedPosition = { venueId, positionId, payload }; },
  deleteVenuePosition: asyncNoop,
  load: asyncNoop,
});
const formHtml = editor.renderPositionForm({ mode: "create", position: { title: "Бармен", pay_profile_id: 3 } });
for (const fieldId of ["f_title", "f_member", "f_pay_profile", "f_perm_template", "btnSavePos"]) {
  assert.ok(formHtml.includes(`id="${fieldId}"`), `${fieldId} is missing from the position form`);
}
assert.match(formHtml, /value="Бармен"/);
assert.match(formHtml, /option value="3" selected>Основной · компонентов: 2<\/option>/);

await editor.callPositionApiWithPerms({
  kind: "create",
  payload: { title: "Бармен", member_user_id: 17, _perm_codes: ["SHIFTS_VIEW"] },
  permCodes: ["SHIFTS_VIEW"],
});
assert.deepEqual(createdPosition, {
  venueId: "7",
  payload: { title: "Бармен", member_user_id: 17, permission_codes: ["SHIFTS_VIEW"] },
});
await editor.callPositionApiWithPerms({
  kind: "update",
  positionId: 9,
  payload: { title: "Старший бармен", member_user_id: 17, _perm_codes: [] },
  permCodes: [],
});
assert.deepEqual(updatedPosition, {
  venueId: "7",
  positionId: 9,
  payload: { title: "Старший бармен", member_user_id: 17, permission_codes: [] },
});

const listModule = await import(pathToFileURL(path.join(moduleDir, "position-list.js")));
const list = listModule.createPositionList({
  state,
  auth,
  esc,
  domain,
  editor,
  toast: noop,
  confirmModal: async () => true,
  deleteVenuePosition: asyncNoop,
  load: asyncNoop,
});
assert.equal(typeof list.renderPositions, "function");
state.positionPresets = [{
  id: "setup-manager",
  title: "Менеджер настройки",
  pay_profile_id: 3,
  pay_profile_title: "Основной",
  permission_codes: ["SHIFTS_VIEW"],
  is_active: true,
}];
assert.deepEqual(
  list.buildPositionGroups().map((group) => ({
    title: group.title,
    count: group.positions.length,
    presetId: group.preset?.id || null,
  })),
  [{ title: "Менеджер настройки", count: 0, presetId: "setup-manager" }],
);
state.positions = [{ id: 9, title: "Менеджер настройки", member_user_id: 17, is_active: true }];
assert.deepEqual(
  list.buildPositionGroups().map((group) => ({ title: group.title, count: group.positions.length })),
  [{ title: "Менеджер настройки", count: 1 }],
);

const inviteModule = await import(pathToFileURL(path.join(moduleDir, "invite-controller.js")));
const invites = inviteModule.createPositionInviteController({
  state,
  auth,
  esc,
  domain,
  toast: noop,
  patchInviteDefaultPosition: asyncNoop,
});
assert.equal(typeof invites.renderInvites, "function");

console.log(`positions split contract: ${moduleFiles.length} modules, ${apiCallManifest.length} API calls, ${uniqueDomBindings.length} DOM controls`);
