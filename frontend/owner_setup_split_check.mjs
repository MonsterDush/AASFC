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
  ["catalog-editor.js", "20260720-unified10", "createCatalogSetupController", ["mountWelcomeEditor", "mountCatalogEditor"]],
  ["pay-profile-editor.js", "20260729-payroll1", "createPayProfileSetupController", ["mountPayProfilesEditor", "loadInlinePayProfiles"]],
  ["position-editor.js", "20260720-unified10", "createPositionSetupController", ["mountPositionsEditor"]],
  ["invite-editor.js", "20260720-unified10", "createInviteSetupController", ["mountInvitesEditor"]],
  ["shift-interval-editor.js", "20260729-overnight1", "createShiftIntervalSetupController", ["mountShiftIntervalsEditor"]],
  ["supplier-editor.js", "20260720-unified10", "createSupplierSetupController", ["mountSuppliersEditor"]],
  ["recurring-expense-editor.js", "20260729-slotecon1", "createRecurringExpenseSetupController", ["mountRecurringExpensesEditor"]],
];

assert.ok(mainSource.split("\n").length < 1_600, "owner-setup.js must remain an orchestration module");
assert.match(htmlSource, /owner-setup\.js\?v=20260729-payroll1/);
assert.match(mainSource, /position-template-ui\.js\?v=20260726-navmore1/);
assert.doesNotMatch(htmlSource, /(?:<style\b|\sstyle\s*=|\.style\b)/i);
assert.doesNotMatch(mainSource, /(?:<style\b|\sstyle\s*=|\.style\b)/i);
assert.match(mainSource, /<progress class="setup-progressbar"/);
assert.match(mainSource, /isSetupDone\(state\.setup\) \? "Настройка завершена"/);
const resumeHelperSource = mainSource.slice(
  mainSource.indexOf("function getPhaseResumeStep"),
  mainSource.indexOf("function renderOverview"),
);
assert.doesNotMatch(resumeHelperSource, /visible\.find\(\(\{ ui \}\) => !ui\.locked\)/);

const inertContext = new Proxy({}, { get: () => () => undefined });
for (const [fileName, cacheKey, factoryName, methodNames] of controllers) {
  const filePath = path.join(frontendDir, "owner-setup", fileName);
  const source = fs.readFileSync(filePath, "utf8");
  assert.ok(source.split("\n").length < 500, `${fileName} is too large`);
  assert.match(mainSource, new RegExp(`/owner-setup/${fileName.replace(".", "\\.")}\\?v=${cacheKey}`));
  assert.doesNotMatch(source, /(?:<style\b|\sstyle\s*=|\.style\b)/i, `${fileName} regained inline CSS`);

  const module = fileName === "shift-interval-editor.js"
    ? await import(`data:text/javascript,${encodeURIComponent(source.replace(
      /^import\s+\{\s*formatShiftIntervalRange\s*\}\s+from\s+["'][^"']+["'];?\s*/,
      'const formatShiftIntervalRange = (start, end) => `${start || ""} — ${end || ""}`;\n',
    ))}`)
    : await import(pathToFileURL(filePath));
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
