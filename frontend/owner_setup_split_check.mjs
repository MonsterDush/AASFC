import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "owner-setup.js");
const htmlPath = path.join(frontendDir, "owner-setup.html");
const mainSource = fs.readFileSync(mainPath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");

const controllers = [
  ["catalog-editor.js", "createCatalogSetupController", ["mountWelcomeEditor", "mountCatalogEditor"]],
  ["pay-profile-editor.js", "createPayProfileSetupController", ["mountPayProfilesEditor", "loadInlinePayProfiles"]],
  ["position-editor.js", "createPositionSetupController", ["mountPositionsEditor"]],
  ["invite-editor.js", "createInviteSetupController", ["mountInvitesEditor"]],
  ["shift-interval-editor.js", "createShiftIntervalSetupController", ["mountShiftIntervalsEditor"]],
  ["supplier-editor.js", "createSupplierSetupController", ["mountSuppliersEditor"]],
  ["recurring-expense-editor.js", "createRecurringExpenseSetupController", ["mountRecurringExpensesEditor"]],
];

assert.ok(mainSource.split("\n").length < 1_600, "owner-setup.js must remain an orchestration module");
assert.match(htmlSource, /owner-setup\.js\?v=20260720-unified10/);
assert.doesNotMatch(htmlSource, /(?:<style\b|\sstyle\s*=|\.style\b)/i);
assert.doesNotMatch(mainSource, /(?:<style\b|\sstyle\s*=|\.style\b)/i);
assert.match(mainSource, /<progress class="setup-progressbar"/);

const inertContext = new Proxy({}, { get: () => () => undefined });
for (const [fileName, factoryName, methodNames] of controllers) {
  const filePath = path.join(frontendDir, "owner-setup", fileName);
  const source = fs.readFileSync(filePath, "utf8");
  assert.ok(source.split("\n").length < 500, `${fileName} is too large`);
  assert.match(mainSource, new RegExp(`/owner-setup/${fileName.replace(".", "\\.")}\\?v=20260720-unified10`));
  assert.doesNotMatch(source, /(?:<style\b|\sstyle\s*=|\.style\b)/i, `${fileName} regained inline CSS`);

  const module = await import(pathToFileURL(filePath));
  assert.equal(typeof module[factoryName], "function", `${factoryName} is not exported`);
  const controller = module[factoryName](inertContext);
  for (const methodName of methodNames) {
    assert.equal(typeof controller[methodName], "function", `${methodName} is not exposed by ${factoryName}`);
  }
}

const stepDispatch = new Map([
  ["welcome", "mountWelcomeEditor"],
  ["pay_profiles", "mountPayProfilesEditor"],
  ["positions", "mountPositionsEditor"],
  ["invites", "mountInvitesEditor"],
  ["shift_intervals", "mountShiftIntervalsEditor"],
  ["suppliers", "mountSuppliersEditor"],
  ["recurring_expenses", "mountRecurringExpensesEditor"],
]);
for (const [stepKey, methodName] of stepDispatch) {
  assert.match(mainSource, new RegExp(`currentStep\\.key === ["']${stepKey}["'][\\s\\S]{0,160}${methodName}\\(`));
}
assert.match(mainSource, /await mountCatalogEditor\(getStepByKey\(currentStep\.key\) \|\| currentStep\)/);

const payProfileFactory = mainSource.indexOf("createPayProfileSetupController(editorContext)");
const crossDependency = mainSource.indexOf("editorContext.loadInlinePayProfiles = loadInlinePayProfiles");
const positionFactory = mainSource.indexOf("createPositionSetupController(editorContext)");
assert.ok(payProfileFactory >= 0 && payProfileFactory < crossDependency && crossDependency < positionFactory);

const routeOwnership = new Map([
  ["invite-editor.js", ["/invites", "/setup/complete-step", "/setup/skip-step"]],
  ["shift-interval-editor.js", ["/shift-intervals", "/setup/complete-step"]],
  ["supplier-editor.js", ["/suppliers", "/setup/complete-step", "/setup/skip-step"]],
  ["recurring-expense-editor.js", ["/recurring-expense-rules", "/expense-categories", "/suppliers", "/setup/skip-step"]],
]);
for (const [fileName, routeFragments] of routeOwnership) {
  const source = fs.readFileSync(path.join(frontendDir, "owner-setup", fileName), "utf8");
  for (const fragment of routeFragments) assert.ok(source.includes(fragment), `${fragment} was lost from ${fileName}`);
}

const recurringSource = fs.readFileSync(path.join(frontendDir, "owner-setup", "recurring-expense-editor.js"), "utf8");
assert.match(recurringSource, /const \{[^}]*getPaymentMethods[^}]*\} = context;/);
assert.match(mainSource, /const editorContext = \{[\s\S]*?getPaymentMethods,[\s\S]*?\};/);

console.log(`owner setup split contract: ${controllers.length} controllers, ${stepDispatch.size} dedicated steps`);
