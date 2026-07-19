import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "staff-shifts.js");
const modulePath = path.join(frontendDir, "staff-shifts", "export-controller.js");
const htmlPath = path.join(frontendDir, "staff-shifts.html");
const mainSource = fs.readFileSync(mainPath, "utf8");
const moduleSource = fs.readFileSync(modulePath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");

assert.ok(mainSource.split("\n").length < 2_500, "staff-shifts.js should not contain export rendering details");
assert.ok(moduleSource.split("\n").length < 900, "schedule export controller is too large");
assert.match(mainSource, /\/staff-shifts\/export-controller\.js\?v=20260719-split1/);
assert.match(htmlSource, /staff-shifts\.js\?v=20260719-split1/);

const module = await import(pathToFileURL(modulePath));
assert.equal(typeof module.createStaffShiftExportController, "function");
const noop = () => undefined;
const context = new Proxy({}, {
  get(_target, key) {
    if (key === "runtime" || key === "el") return {};
    return noop;
  },
});
const controller = module.createStaffShiftExportController(context);
for (const methodName of ["openExportModal", "refreshExportPreview", "downloadExportImage"]) {
  assert.equal(typeof controller[methodName], "function", `${methodName} is not exposed`);
}

const mutableRuntimeFields = [
  "me",
  "calendarView",
  "curWeekStart",
  "curMonth",
  "selectedShiftSlot",
  "intervals",
  "selectedIntervalIds",
  "calendarScope",
  "showAllOnCalendar",
  "unstaffedOnly",
  "currentVenueName",
  "venueId",
  "shiftsByDate",
];
for (const field of mutableRuntimeFields) {
  assert.match(mainSource, new RegExp(`get ${field}\\(\\) \\{ return ${field}; \\}`));
  assert.ok(moduleSource.includes(`runtime.${field}`), `${field} is not read dynamically`);
}

for (const control of ["btnExportImage", "btnExportShare", "btnExportTelegram", "btnExportDownload"]) {
  assert.ok(moduleSource.includes(`el.${control}`), `${control} is no longer wired`);
}
assert.ok(moduleSource.includes("/shifts/export-metadata?"), "export metadata route was lost");
assert.match(mainSource, /\/\/ navigation \(month\/week\)[\s\S]+await loadContext\(\);/);

console.log(`staff shifts split contract: ${mutableRuntimeFields.length} live state fields`);
