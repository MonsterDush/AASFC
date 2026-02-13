import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("salary");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (!venueId) toast("Сначала выбери заведение в «Настройках»", "warn");
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "salary", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  sumTotal: document.getElementById("sumTotal"),
  sumShifts: document.getElementById("sumShifts"),
  sumNoReport: document.getElementById("sumNoReport"),
  daysList: document.getElementById("daysList"),
};

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
function openModal(title, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Зарплата";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function monthTitle(d) {
  const m = d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  return m.charAt(0).toUpperCase() + m.slice(1);
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

let me = null;
let perms = null;
let canViewRevenue = false;

let curMonth = new Date();
curMonth.setDate(1);

async function loadContext() {
  me = await getMe().catch(() => null);
  perms = await getMyVenuePermissions(venueId).catch(() => null);
  const flags = perms?.position_flags || {};
  const posObj = perms?.position || {};
  const role = perms?.role || perms?.venue_role || perms?.my_role || null;

  canViewRevenue =
    role === "OWNER" ||
    role === "SUPER_ADMIN" ||
    flags.can_view_revenue === true ||
    flags.can_make_reports === true ||
    posObj.can_view_revenue === true ||
    posObj.can_make_reports === true;
}

function intervalLabel(s) {
  const i = s.interval || s.shift_interval || {};
  const t = i.title || s.interval_title || "Смена";
  const st = i.start_time || "";
  const et = i.end_time || "";
  return (st && et) ? `${t} (${st}-${et})` : t;
}

function groupByDate(shifts) {
  const by = new Map();
  for (const s of shifts) {
    const dateStr = s.date;
    if (!by.has(dateStr)) by.set(dateStr, []);
    by.get(dateStr).push(s);
  }
  // sort shifts within day by interval time if exists
  for (const [k, arr] of by.entries()) {
    arr.sort((a, b) => String(a.interval?.start_time || "").localeCompare(String(b.interval?.start_time || "")));
    by.set(k, arr);
  }
  return by;
}

async function loadMonth() {
  if (!venueId) return;

  el.monthLabel.textContent = monthTitle(curMonth);

  const m = ym(curMonth);
  let shifts = [];
  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m)}`);
    shifts = Array.isArray(out) ? out : (out?.shifts || out?.items || out?.data || []);
  } catch (e) {
    toast(e?.message || "Не удалось загрузить смены", "err");
    shifts = [];
  }

  // only my shifts
  const myId = me?.id ?? null;
  const myShifts = shifts.filter((s) => {
    const assigns = (s.assignments || s.shift_assignments || []);
    return assigns.some((a) => (a.member_user_id ?? a.user_id) === myId);
  });

  const byDate = groupByDate(myShifts);
  const days = Array.from(byDate.keys()).sort();

  // totals
  let total = 0;
  let shiftsCount = 0;
  let noReportDays = 0;

  const dayRows = [];
  for (const d of days) {
    const list = byDate.get(d) || [];
    shiftsCount += list.length;

    const reportExists = list.some((s) => !!s.report_exists);
    const salaries = list.map((s) => s.my_salary).filter((x) => x != null);
    const sum = salaries.reduce((acc, x) => acc + Number(x), 0);

    if (!reportExists) noReportDays += 1;
    total += sum;

    const revenueTotal = canViewRevenue ? (list.find((s) => s.revenue_total != null)?.revenue_total ?? null) : null;
    dayRows.push({ date: d, list, reportExists, sum, revenueTotal });
  }

  if (el.sumTotal) el.sumTotal.textContent = total.toLocaleString("ru-RU") + "₽";
  if (el.sumShifts) el.sumShifts.textContent = String(shiftsCount);
  if (el.sumNoReport) el.sumNoReport.textContent = String(noReportDays);

  renderDays(dayRows);
}

function renderDays(dayRows) {
  if (!el.daysList) return;
  el.daysList.innerHTML = "";

  if (!dayRows.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "В этом месяце у тебя нет смен.";
    el.daysList.appendChild(empty);
    return;
  }

  for (const r of dayRows) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "row";
    btn.style.width = "100%";
    btn.style.justifyContent = "space-between";
    btn.style.alignItems = "center";
    btn.style.gap = "10px";
    btn.style.padding = "10px";
    btn.style.borderRadius = "12px";
    btn.style.border = "1px solid rgba(255,255,255,.08)";
    btn.style.background = "transparent";
    btn.style.cursor = "pointer";

    const left = document.createElement("div");
    left.innerHTML = `<b>${escapeHtml(r.date)}</b><div class="muted" style="font-size:12px">Смен: ${r.list.length}</div>`;

    let rightText = "—";
    if (!r.reportExists) rightText = "нет отчёта";
    else rightText = (r.sum || 0).toLocaleString("ru-RU") + "₽";

    const right = document.createElement("div");
    right.style.textAlign = "right";
    right.innerHTML = `<b>${escapeHtml(rightText)}</b>` +
      (canViewRevenue && r.revenueTotal != null ? `<div class="muted" style="font-size:12px">Выручка: ${Number(r.revenueTotal).toLocaleString("ru-RU")}₽</div>` : "");

    btn.appendChild(left);
    btn.appendChild(right);
    btn.addEventListener("click", () => openDayModal(r));

    el.daysList.appendChild(btn);
  }
}

function openDayModal(r) {
  const lines = [];
  for (const s of r.list) {
    const label = intervalLabel(s);
    const sal = s.my_salary != null ? `${Number(s.my_salary).toLocaleString("ru-RU")}₽` : (s.report_exists ? "—" : "нет отчёта");
    lines.push(`<div class="row" style="justify-content:space-between;gap:10px"><div>${escapeHtml(label)}</div><b>${escapeHtml(sal)}</b></div>`);
  }

  const revenueLine = (canViewRevenue && r.revenueTotal != null)
    ? `<div class="row" style="justify-content:space-between;gap:10px;margin-top:8px"><div class="muted">Выручка за день</div><b>${Number(r.revenueTotal).toLocaleString("ru-RU")}₽</b></div>`
    : "";

  openModal(
    `День ${escapeHtml(r.date)}`,
    `<div style="display:flex;flex-direction:column;gap:10px">
       ${!r.reportExists ? `<div class="muted">Отчёта за день нет — зарплата не считается.</div>` : ""}
       <div style="display:flex;flex-direction:column;gap:8px">${lines.join("")}</div>
       ${revenueLine}
     </div>`
  );
}

// month navigation
el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
});

await loadContext();
await loadMonth();
