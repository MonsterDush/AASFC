import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const mainPath = path.join(frontendDir, "staff-shifts.js");
const modulePath = path.join(frontendDir, "staff-shifts", "export-controller.js");
const calendarModulePath = path.join(frontendDir, "staff-shifts", "calendar-controller.js");
const htmlPath = path.join(frontendDir, "staff-shifts.html");
const mainSource = fs.readFileSync(mainPath, "utf8");
const moduleSource = fs.readFileSync(modulePath, "utf8");
const calendarModuleSource = fs.readFileSync(calendarModulePath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");
const combinedSource = [mainSource, calendarModuleSource, moduleSource].join("\n");

const apiCallManifest = Array.from(
  combinedSource.matchAll(/\b(?:api|startupApi)\(\s*(`[^`]+`|"[^"]+"|'[^']+')/g),
  (match) => match[1].replaceAll("runtime.venueId", "venueId"),
).sort();
const domBindingManifest = Array.from(
  combinedSource.matchAll(/getElementById\(\s*["']([^"']+)["']\s*\)/g),
  (match) => match[1],
).sort();
const manifestHash = (values) => crypto.createHash("sha256").update(JSON.stringify(values)).digest("hex");
assert.equal(apiCallManifest.length, 14);
assert.equal(manifestHash(apiCallManifest), "8661950b26b516eaac23a617404e792adb96ae03dbae35de9d1078afe3c3f869");
assert.equal(domBindingManifest.length, 55);
assert.equal(manifestHash(domBindingManifest), "ac35bc61a168dd228accbecf9a0424425cb15abe9a88eeecfb44671f68ab101a");

assert.ok(mainSource.split("\n").length < 1_800, "staff-shifts.js should remain an orchestration module");
assert.ok(moduleSource.split("\n").length < 900, "schedule export controller is too large");
assert.ok(calendarModuleSource.split("\n").length < 850, "calendar controller is too large");
assert.match(mainSource, /\/staff-shifts\/export-controller\.js\?v=20260719-split1/);
assert.match(mainSource, /\/staff-shifts\/calendar-controller\.js\?v=20260720-unified6/);
assert.match(htmlSource, /staff-shifts\.js\?v=20260722-dynamic1/);

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

globalThis.window = { addEventListener: () => undefined };
const calendarModule = await import(pathToFileURL(calendarModulePath));
assert.equal(typeof calendarModule.createStaffShiftCalendarController, "function");
const calendarRuntime = {
  selectedDate: null,
  shiftsByDate: new Map(),
  salaryByDate: new Map(),
  calendarScope: "venue",
  globalShifts: [],
  shifts: [
    { id: 2, date: "2031-07-03", start_time: "12:00", assignments: [{ member_user_id: 17 }, { member_user_id: 18 }] },
    { id: 1, date: "2031-07-03", start_time: "09:00", assignments: [{ member_user_id: 17 }] },
  ],
  curMonth: new Date(2031, 6, 1),
  me: { id: 17 },
  canEdit: true,
  showAllOnCalendar: true,
  nightShiftsEnabled: false,
  selectedShiftSlot: "DAY",
};
const calendarController = calendarModule.createStaffShiftCalendarController({
  runtime: calendarRuntime,
  toast: noop,
  DEMO_MODE: false,
  shouldShowDemoSalaryValue: (value) => Number.isFinite(Number(value)),
  el: {},
  toHHMM: (value) => String(value || "").slice(0, 5),
  pad2: (value) => String(value).padStart(2, "0"),
  ym: (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`,
  ymd: (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
  addDays: (date, days) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days),
  WEEKDAYS: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
  isPastDay: () => false,
  colorForInterval: () => "#000000",
  escapeHtml: (value) => String(value ?? ""),
  pickShortName: () => "Сотрудник",
  displayPerson: () => "Сотрудник",
  shiftSlotLabel: (value) => value,
  shiftIntervalId: (shift) => shift.interval_id || 0,
  shiftStartHHMM: (shift) => shift.start_time || "",
  sortShiftsForBadges: (items) => items.slice().sort((a, b) => String(a.start_time).localeCompare(String(b.start_time))),
  shiftDonePrefix: () => "",
  formatGlobalLine: () => "",
  canEditDay: () => true,
  openDay: noop,
});
const calendarMethods = [
  "renderWeek",
  "buildIndex",
  "defaultSelectedDateForMonth",
  "selectDate",
  "monthTitle",
  "formatDateRuNoG",
  "filterForCalendar",
  "shiftIsClosed",
  "renderMonth",
];
for (const methodName of calendarMethods) {
  assert.equal(typeof calendarController[methodName], "function", `${methodName} is not exposed by calendar controller`);
  assert.match(mainSource, new RegExp(`\\b${methodName}\\b`));
}

const calendarMutableFields = [
  "selectedDate",
  "shiftsByDate",
  "salaryByDate",
  "calendarScope",
  "globalShifts",
  "shifts",
  "curMonth",
  "me",
  "canEdit",
  "showAllOnCalendar",
  "nightShiftsEnabled",
  "selectedShiftSlot",
];
for (const field of calendarMutableFields) {
  assert.match(mainSource, new RegExp(`get ${field}\\(\\) \\{ return ${field}; \\}`));
  assert.match(mainSource, new RegExp(`set ${field}\\(value\\) \\{ ${field} = value; \\}`));
  assert.ok(calendarModuleSource.includes(`runtime.${field}`), `${field} is not synchronized with the calendar`);
}

calendarController.buildIndex();
assert.deepEqual(Array.from(calendarRuntime.shiftsByDate.keys()), ["2031-07-03"]);
assert.deepEqual(calendarRuntime.shiftsByDate.get("2031-07-03").map((shift) => shift.id), [1, 2]);
assert.equal(calendarController.defaultSelectedDateForMonth(), "2031-07-03");
assert.equal(calendarController.formatDateRuNoG("2031-07-03"), "03.07.2031");
assert.equal(calendarController.shiftIsClosed({ report_status: "CLOSED" }), true);
assert.equal(calendarController.filterForCalendar(calendarRuntime.shifts, "2031-07-03").length, 2);
calendarRuntime.canEdit = false;
calendarRuntime.showAllOnCalendar = false;
const staffOnly = calendarController.filterForCalendar(calendarRuntime.shifts, "2031-07-03");
assert.equal(staffOnly.length, 2);
assert.deepEqual(staffOnly.map((shift) => shift.assignments.length), [1, 1]);

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

console.log(`staff shifts split contract: ${calendarMethods.length} calendar methods, ${calendarMutableFields.length} synchronized fields`);
