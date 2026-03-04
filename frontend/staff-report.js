import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  API_BASE,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
  getDepartments,
  getPaymentMethods,
  getKpiMetrics,
  getVenueSettings,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("report");

await ensureLogin({ silent: true });
await mountNav({ activeTab: "report" });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
};

// Month summary (DayPanel) removed earlier — keep compatible if exists
if (el.dayPanel) {
  try { el.dayPanel.remove(); } catch {}
  el.dayPanel = null;
}

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");

// ---- Photo viewer (attachments) ----
const photoModal = document.getElementById("photoModal");
const phTitle = document.getElementById("photoTitle");
const phSubtitle = document.getElementById("photoSubtitle");
const phImg = document.getElementById("phImg");
const phPrev = document.getElementById("phPrev");
const phNext = document.getElementById("phNext");
const phCounter = document.getElementById("phCounter");
const phDownload = document.getElementById("phDownload");
const phDelete = document.getElementById("phDelete");
let phItems = [];
let phIndex = 0;
let phDayISO = "";

function closePhotoModal() { photoModal?.classList.remove("open"); }
photoModal?.querySelectorAll("[data-close-ph]")?.forEach((b) => b.addEventListener("click", closePhotoModal));
photoModal?.querySelector(".modal__backdrop")?.addEventListener("click", closePhotoModal);

function esc(s){
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function numOr0(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function fmtRub(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("ru-RU") + " ₽";
}

function fmtNum(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("ru-RU");
}

function ymd(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function ym(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}
function monthTitle(d) {
  const dt = new Date(d);
  const m = dt.toLocaleString("ru-RU", { month: "long" });
  const y = dt.getFullYear();
  return `${m.charAt(0).toUpperCase()}${m.slice(1)} ${y}`;
}

function formatDateRuNoG(iso) {
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function fmtDtRu(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm}.${yyyy} ${hh}:${mi}`;
}

function attachmentHref(rawUrl) {
  const raw = String(rawUrl || "");
  const path = raw.startsWith("/api/") ? raw.slice(4) : raw;
  if (path.startsWith("/")) return API_BASE + path;
  return raw;
}

function canDeleteAttachments() {
  return canMake();
}

function showPhotoAt(idx) {
  if (!phItems.length) return;
  phIndex = Math.max(0, Math.min(idx, phItems.length - 1));
  const a = phItems[phIndex];
  const url = attachmentHref(a.url);
  if (phTitle) phTitle.textContent = a.file_name || "Фото";
  if (phSubtitle) phSubtitle.textContent = formatDateRuNoG(phDayISO);
  if (phImg) phImg.src = url;
  if (phCounter) phCounter.textContent = `${phIndex + 1} / ${phItems.length}`;
  if (phDownload) {
    phDownload.href = url;
    phDownload.setAttribute("download", a.file_name || "photo");
  }
  if (phDelete) phDelete.style.display = canDeleteAttachments() ? "" : "none";
}

phPrev?.addEventListener("click", () => showPhotoAt(phIndex - 1));
phNext?.addEventListener("click", () => showPhotoAt(phIndex + 1));

async function deleteCurrentPhoto() {
  if (!canDeleteAttachments()) return;
  const a = phItems[phIndex];
  if (!a) return;
  if (!confirm("Удалить файл?")) return;
  try {
    await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(phDayISO)}/attachments/${encodeURIComponent(a.id)}`, { method: "DELETE" });
    phItems.splice(phIndex, 1);
    if (!phItems.length) {
      closePhotoModal();
      await openDay(phDayISO);
      return;
    }
    showPhotoAt(Math.min(phIndex, phItems.length - 1));
    await openDay(phDayISO);
  } catch (e) {
    toast("Не удалось удалить: " + (e?.data?.detail || e?.message || "ошибка"), "err");
  }
}
phDelete?.addEventListener("click", deleteCurrentPhoto);

function openPhotoModal(items, startIdx, dayISO) {
  phItems = Array.isArray(items) ? items.slice() : [];
  phDayISO = dayISO;
  photoModal?.classList.add("open");
  showPhotoAt(startIdx || 0);
}

// ---- Main modal helpers ----
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);

function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Отчёт";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function withTimeout(p, ms, label) {
  const timeoutMs = Number(ms) || 0;
  if (!timeoutMs) return p;
  let t;
  const tp = new Promise((_, rej) => {
    t = setTimeout(() => rej(new Error(`Timeout${label ? ': ' + label : ''}`)), timeoutMs);
  });
  return Promise.race([
    Promise.resolve(p).finally(() => clearTimeout(t)),
    tp,
  ]);
}

// ---- Calendar ----
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
let curMonth = new Date();
curMonth.setDate(1);

let reportsByDate = new Map(); // dateISO -> report
let perms = { role: "", permissions: [], flags: {} };
let selectedDayISO = "";

function hasPerm(code) {
  const arr = perms?.permissions;
  return Array.isArray(arr) && arr.includes(code);
}

function isOwnerOrAdmin() {
  const r = String(perms?.role || "").toUpperCase();
  return r === "OWNER" || r === "SUPER_ADMIN" || r === "MODERATOR";
}

function canMake() {
  return (
    isOwnerOrAdmin() ||
    hasPerm("SHIFT_REPORT_CLOSE") ||
    hasPerm("SHIFT_REPORT_EDIT") ||
    perms.flags?.can_make_reports === true
  );
}


function canView() {
  return (
    isOwnerOrAdmin() ||
    perms.flags?.can_view_reports === true ||
    perms.flags?.can_make_reports === true ||
    hasPerm("SHIFT_REPORT_VIEW") ||
    hasPerm("SHIFT_REPORT_CLOSE") ||
    hasPerm("SHIFT_REPORT_EDIT") ||
    hasPerm("SHIFT_REPORT_REOPEN")
  );
}


function canSeeMoney() {
  return (
    isOwnerOrAdmin() ||
    perms.flags?.can_view_revenue === true ||
    perms.flags?.can_make_reports === true ||
    hasPerm("SHIFT_REPORT_VIEW") ||
    hasPerm("SHIFT_REPORT_CLOSE") ||
    hasPerm("SHIFT_REPORT_EDIT")
  );
}


function canClose() {
  return (
    isOwnerOrAdmin() ||
    hasPerm("SHIFT_REPORT_CLOSE") ||
    hasPerm("SHIFT_REPORT_EDIT") ||
    perms.flags?.can_make_reports === true
  );
}


function canReopen() {
  return isOwnerOrAdmin() || hasPerm("SHIFT_REPORT_REOPEN");
}

function canEditClosed() {
  // Backend additionally requires SHIFT_REPORT_EDIT for CLOSED edits.
  return canMake() && (hasPerm("SHIFT_REPORT_EDIT") || String(perms?.role || "").toUpperCase() === "SUPER_ADMIN");
}

async function loadPerms() {
  perms = { role: "", permissions: [], flags: {} };
  if (!venueId) return;
  try {
    const p = await getMyVenuePermissions(venueId);
    perms.role = p?.role || "";
    perms.permissions = p?.permissions || [];
    perms.flags = p?.position_flags || {};
  } catch {
    perms = { role: "", permissions: [], flags: {} };
  }
}

async function loadMonthReports() {
  reportsByDate = new Map();
  if (!venueId) return;
  if (!canView()) return;
  const m = ym(curMonth);
  try {
    const list = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(m)}`);
    (list || []).forEach((r) => {
      if (r?.date) reportsByDate.set(r.date, r);
    });
  } catch {
    reportsByDate = new Map();
  }
}

function renderNoVenue() {
  el.grid.innerHTML = `
    <div class="itemcard">
      <b>Не выбрано заведение</b>
      <div class="muted" style="margin-top:6px">
        Открой страницу с параметром <span class="mono">?venue_id=...</span>.
      </div>
    </div>
  `;
}

function renderMonth() {
  if (!el.grid || !el.monthLabel) return;

  el.monthLabel.textContent = monthTitle(curMonth);
  el.grid.innerHTML = "";

  if (!venueId) {
    renderNoVenue();
    return;
  }

  if (!canView()) {
    el.grid.innerHTML = `
      <div class="itemcard">
        <b>Нет доступа</b>
        <div class="muted" style="margin-top:6px">У вас нет прав на просмотр отчётов.</div>
      </div>
    `;
    return;
  }

  const head = document.createElement("div");
  head.className = "cal-head";
  for (const wd of WEEKDAYS) {
    const c = document.createElement("div");
    c.className = "cal-hcell";
    c.textContent = wd;
    head.appendChild(c);
  }
  el.grid.appendChild(head);

  const body = document.createElement("div");
  body.className = "cal-body";

  const first = new Date(curMonth);
  const jsDow = first.getDay();
  const mondayBased = (jsDow + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const todayStr = ymd(new Date());
  const monthStr = ym(curMonth);

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const dStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";

    const rep = reportsByDate.get(dStr) || null;
    const hasRep = !!rep;
    const status = String(rep?.status || "").toUpperCase();

    const badgeHtml = hasRep
      ? `<span class="badge ${status === "CLOSED" ? "badge--closed" : "badge--draft"}">${status === "CLOSED" ? "закрыто" : "черновик"}</span>`
      : ``;

    cell.innerHTML = `
      <div class="cal-daynum">${d.getDate()}</div>
      <div class="cal-badges">${badgeHtml}</div>
    `;

    if (ym(d) !== monthStr) cell.classList.add("cal-cell--out");
    if (dStr === todayStr) cell.classList.add("cal-cell--today");
    if (dStr === selectedDayISO) cell.classList.add("cal-cell--selected");
    if (hasRep && status === "CLOSED") cell.classList.add("cal-cell--closed");
    if (hasRep && status !== "CLOSED") cell.classList.add("cal-cell--draft");

    cell.onclick = () => {
      selectedDayISO = dStr;
      renderMonth();
      openDay(dStr).catch((e) => {
        console.error(e);
        toast("Ошибка: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
      });
    };

    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

// ---- API calls for report ----
async function fetchReport(dayISO) {
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}`);
  } catch (e) {
    throw e;
  }
}

async function fetchAttachments(dayISO) {
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/attachments`);
  } catch {
    return { items: [] };
  }
}

async function uploadAttachments(dayISO, files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  return api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/attachments`, {
    method: "POST",
    body: fd,
  });
}

async function fetchAudit(dayISO) {
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/audit`);
  } catch {
    return [];
  }
}

async function closeReport(dayISO, comment) {
  return api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/close`, {
    method: "POST",
    body: { comment: comment ?? null },
  });
}

async function reopenReport(dayISO) {
  return api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/reopen`, {
    method: "POST",
  });
}

function buildEmptyReportFromCatalogs(dayISO, catalogs) {
  const pm = Array.isArray(catalogs?.payments) ? catalogs.payments : [];
  const dep = Array.isArray(catalogs?.departments) ? catalogs.departments : [];
  const kpi = Array.isArray(catalogs?.kpis) ? catalogs.kpis : [];

  return {
    id: null,
    date: dayISO,
    status: "DRAFT",
    closed_at: null,
    closed_by_user_id: null,
    comment: "",
    cash: 0,
    cashless: 0,
    revenue_total: 0,
    tips_total: 0,
    payments: pm.map((x) => ({ ...x, value: 0 })),
    departments: dep.map((x) => ({ ...x, value: 0 })),
    kpis: kpi.map((x) => ({ ...x, value: 0 })),
    payments_total: 0,
    departments_total: 0,
    discrepancy: 0,
  };
}

function unitLabel(unit) {
  const u = String(unit || "").toUpperCase();
  if (u === "RUB" || u === "RUR" || u === "R") return "₽";
  if (u === "QTY" || u === "PCS" || u === "COUNT") return "шт";
  if (u === "MIN" || u === "MINUTES") return "мин";
  if (u === "H" || u === "HOURS") return "ч";
  return unit ? String(unit) : "";
}

function calcTotalsFromDom({ hasDepartments }) {
  const inputs = modalBody?.querySelectorAll("input[data-kind]") || [];
  const totals = { payments: 0, departments: 0, kpis: 0, revenue_total: 0, tips: 0 };

  inputs.forEach((inp) => {
    const kind = String(inp.getAttribute("data-kind") || "");
    const v = Math.max(0, numOr0(inp.value));
    if (kind === "PAYMENT") totals.payments += v;
    else if (kind === "DEPT") totals.departments += v;
    else if (kind === "KPI") totals.kpis += v;
  });

  const rev = modalBody?.querySelector("#repRevenueTotal");
  totals.revenue_total = Math.max(0, numOr0(rev?.value));

  const tips = modalBody?.querySelector("#repTips");
  totals.tips = Math.max(0, numOr0(tips?.value));

  const baseTotal = hasDepartments ? totals.departments : totals.revenue_total;
  const discrepancy = totals.payments - baseTotal;

  return { ...totals, baseTotal, discrepancy };
}

function renderAuditSection(audit, maps) {
  if (!Array.isArray(audit) || !audit.length) {
    return `<div class="muted">Пока нет правок закрытого отчёта</div>`;
  }

  const maxCommentLen = 120;
  const cut = (s) => {
    const t = String(s ?? "").trim();
    if (!t) return "";
    return t.length > maxCommentLen ? t.slice(0, maxCommentLen - 1) + "…" : t;
  };

  const mapArrToObj = (arr) => {
    const m = new Map();
    (Array.isArray(arr) ? arr : []).forEach((x) => {
      const id = Number(x?.ref_id);
      if (!Number.isFinite(id) || id <= 0) return;
      m.set(id, numOr0(x?.value));
    });
    return m;
  };

  const diffLines = (diff) => {
    const before = diff?.before || {};
    const after = diff?.after || {};
    const out = [];

    const bc = String(before.comment ?? "");
    const ac = String(after.comment ?? "");
    if (bc !== ac) {
      out.push(`Комментарий: “${esc(cut(bc))}” → “${esc(cut(ac))}”`);
    }

    const bt = before.totals || {};
    const at = after.totals || {};
    const keys = [
      ["payments_total", "Оплаты (итого)", "rub"],
      ["departments_total", "Департаменты (итого)", "rub"],
      ["base_total", "База сравнения", "rub"],
      ["discrepancy", "Расхождение", "rub"],
    ];
    for (const [k, label, mode] of keys) {
      const v1 = numOr0(bt?.[k]);
      const v2 = numOr0(at?.[k]);
      if (v1 !== v2) {
        const a = mode === "rub" ? fmtRub(v1) : fmtNum(v1);
        const b = mode === "rub" ? fmtRub(v2) : fmtNum(v2);
        out.push(`${label}: ${esc(a)} → ${esc(b)}`);
      }
    }

    const groups = [
      ["payments", "Оплата", maps?.paymentsTitleById, (v) => fmtRub(v)],
      ["departments", "Департамент", maps?.departmentsTitleById, (v) => fmtRub(v)],
      ["kpis", "KPI", maps?.kpisTitleById, (v, id) => {
        const unit = maps?.kpiUnitById?.[id] || "";
        const u = String(unit || "").toUpperCase();
        if (u === "RUB" || u === "RUR" || u === "R") return fmtRub(v);
        const uLbl = unitLabel(unit);
        return `${fmtNum(v)}${uLbl ? " " + uLbl : ""}`;
      }],
    ];

    for (const [key, label, titleById, fmt] of groups) {
      const m1 = mapArrToObj(before?.[key]);
      const m2 = mapArrToObj(after?.[key]);
      const allIds = new Set([...m1.keys(), ...m2.keys()]);
      const ids = Array.from(allIds).sort((a, b) => a - b);
      for (const id of ids) {
        const v1 = numOr0(m1.get(id) || 0);
        const v2 = numOr0(m2.get(id) || 0);
        if (v1 === v2) continue;
        const title = titleById?.[id] || `#${id}`;
        const a = fmt(v1, id);
        const b = fmt(v2, id);
        out.push(`${label}: ${esc(title)} — ${esc(a)} → ${esc(b)}`);
      }
    }

    return out;
  };

  return audit
    .map((a) => {
      const who = a?.user_tg_username ? `@${a.user_tg_username}` : (a?.user_id ? `user#${a.user_id}` : "—");
      const when = fmtDtRu(a?.changed_at);
      const lines = diffLines(a?.diff);
      const inner = lines.length
        ? `<ul class="audit-list">${lines.map((x) => `<li>${x}</li>`).join("")}</ul>`
        : `<div class="muted">Нет различий</div>`;

      return `
        <details class="audit-item">
          <summary>
            <span class="audit-when">${esc(when)}</span>
            <span class="audit-who muted">${esc(who)}</span>
          </summary>
          <div class="audit-body">${inner}</div>
        </details>
      `;
    })
    .join("");
}

function reportStatusBadge(status) {
  const s = String(status || "DRAFT").toUpperCase();
  if (s === "CLOSED") return `<span class="rep-badge rep-badge--closed">CLOSED</span>`;
  return `<span class="rep-badge rep-badge--draft">DRAFT</span>`;
}

function renderReportModal({ dayISO, rep, catalogs, attachments, audit, mode, tipsEnabled }) {
  const status = String(rep?.status || "DRAFT").toUpperCase();
  const showMoney = canSeeMoney();
  const hasDepartments = Array.isArray(rep?.departments) && rep.departments.length > 0;
  const tipsOn = tipsEnabled !== false;

  const isDraft = status !== "CLOSED";
  const canEditDraft = isDraft && canMake() && showMoney;
  const canEditClosedNow = status === "CLOSED" && canEditClosed() && showMoney;

  const editEnabled = mode === "edit" ? (isDraft ? canEditDraft : canEditClosedNow) : false;

  const subtitle = isDraft
    ? (canMake() ? "Черновик" : "Просмотр")
    : "Закрыто" + (rep?.closed_at ? ` · ${fmtDtRu(rep.closed_at)}` : "");

  const topMeta = `
    <div class="rep-topmeta">
      <div class="rep-topmeta__left">
        ${reportStatusBadge(status)}
        ${rep?.closed_at ? `<span class="muted small">Закрыто: ${esc(fmtDtRu(rep.closed_at))}</span>` : ``}
      </div>
      <div class="rep-topmeta__right">
        ${status === "CLOSED" && canReopen() ? `<button class="btn sm" id="btnReopen">Переоткрыть</button>` : ``}
        ${status === "CLOSED" && canEditClosedNow && !editEnabled ? `<button class="btn sm primary" id="btnEnableEdit">Редактировать</button>` : ``}
      </div>
    </div>
  `;

  const section = (title, bodyHtml, hint) => `
    <div class="rep-sec">
      <div class="rep-sec__head">
        <b>${esc(title)}</b>
        ${hint ? `<div class="muted small" style="margin-top:4px">${esc(hint)}</div>` : ``}
      </div>
      <div class="rep-sec__body">${bodyHtml}</div>
    </div>
  `;

  const inputRow = (kind, it, opts = {}) => {
    const v = showMoney ? (Number.isFinite(Number(it?.value)) ? Number(it.value) : 0) : "";
    const disabled = (!editEnabled) || (!showMoney);
    const unit = opts.unit || "";
    const unitHtml = unit ? `<span class="muted small">${esc(unit)}</span>` : ``;
    return `
      <label class="rep-field">
        <div class="rep-field__label">
          <span>${esc(it?.title || "—")}</span>
          ${it?.is_active === false ? `<span class="badge">архив</span>` : ``}
          ${unitHtml}
        </div>
        <input
          type="number"
          min="0"
          inputmode="numeric"
          data-kind="${esc(kind)}"
          data-ref="${esc(it?.id)}"
          value="${esc(v)}"
          ${disabled ? "disabled" : ""}
          placeholder="${showMoney ? "0" : "нет доступа"}"
        />
      </label>
    `;
  };

  const payments = Array.isArray(rep?.payments) ? rep.payments : [];
  const departments = Array.isArray(rep?.departments) ? rep.departments : [];
  const kpis = Array.isArray(rep?.kpis) ? rep.kpis : [];

  const paymentsHtml = payments.length
    ? `<div class="rep-grid">${payments.map((it) => inputRow("PAYMENT", it)).join("")}</div>`
    : `<div class="muted">Способы оплат не настроены</div>`;

  const deptsHtml = hasDepartments
    ? `<div class="rep-grid">${departments.map((it) => inputRow("DEPT", it)).join("")}</div>`
    : `
      <div class="rep-grid rep-grid--single">
        <label class="rep-field">
          <div class="rep-field__label"><span>Выручка (итого)</span></div>
          <input id="repRevenueTotal" type="number" min="0" inputmode="numeric" value="${esc(showMoney ? (rep?.revenue_total ?? 0) : "")}" ${(!editEnabled || !showMoney) ? "disabled" : ""} placeholder="${showMoney ? "0" : "нет доступа"}" />
        </label>
      </div>
      <div class="muted small" style="margin-top:6px">Департаменты не настроены — вводим общую выручку.</div>
    `;

  const kpisHtml = kpis.length
    ? `<div class="rep-grid">${kpis.map((it) => inputRow("KPI", it, { unit: unitLabel(it?.unit) })).join("")}</div>`
    : `<div class="muted">KPI пока не настроены</div>`;

  const tipsDisabled = (!editEnabled) || (!showMoney);
  const tipsHtml = !tipsOn ? `` : `
    <div class="rep-grid rep-grid--single">
      <label class="rep-field">
        <div class="rep-field__label"><span>Чаевые (общая сумма)</span></div>
        <input id="repTips" type="number" min="0" inputmode="numeric" value="${esc(showMoney ? (rep?.tips_total ?? 0) : "")}" ${tipsDisabled ? "disabled" : ""} placeholder="${showMoney ? "0" : "нет доступа"}" />
      </label>
    </div>
  `;

  const comment = String(rep?.comment ?? "");
  const commentDisabled = !editEnabled; // comment also locked when view-only

  const totals = {
    payments_total: showMoney ? (rep?.payments_total ?? null) : null,
    departments_total: showMoney ? (rep?.departments_total ?? null) : null,
    discrepancy: showMoney ? (rep?.discrepancy ?? null) : null,
  };

  const totalsHtml = `
    <div class="rep-totals">
      <div class="rep-total">
        <div class="muted small">Оплаты (итого)</div>
        <div class="rep-total__v" id="t_payments_total">${totals.payments_total === null ? "—" : esc(fmtRub(totals.payments_total))}</div>
      </div>
      <div class="rep-total">
        <div class="muted small">${hasDepartments ? "Департаменты (итого)" : "Выручка (база)"}</div>
        <div class="rep-total__v" id="t_base_total">${totals.discrepancy === null ? "—" : esc(fmtRub((hasDepartments ? (totals.departments_total ?? 0) : (rep?.revenue_total ?? 0))))}</div>
      </div>
      <div class="rep-total rep-total--discr" id="t_discr_box">
        <div class="muted small">Расхождение</div>
        <div class="rep-total__v" id="t_discrepancy">${totals.discrepancy === null ? "—" : esc(fmtRub(totals.discrepancy))}</div>
        <div class="rep-total__hint muted small" id="t_discr_hint" style="display:none">Для закрытия нужен комментарий</div>
      </div>
    </div>
  `;

  const commentHtml = `
    <div style="margin-top:10px">
      <div class="muted small" style="margin-bottom:6px">Комментарий (обязателен при расхождении)</div>
      <textarea id="repComment" class="rep-comment" ${commentDisabled ? "disabled" : ""} placeholder="Например: расхождение из-за возврата / перевод между кассами / ...">${esc(comment)}</textarea>
    </div>
  `;

  const actionsHtml = (() => {
    if (!showMoney) {
      return `<div class="muted" style="margin-top:10px">Суммы скрыты из-за прав доступа.</div>`;
    }

    if (status === "CLOSED") {
      if (!canEditClosedNow) return ``;
      if (!editEnabled) return ``;
      return `
        <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px; flex-wrap:wrap">
          <button class="btn primary" id="btnSaveClosed" type="button">Сохранить изменения</button>
        </div>
      `;
    }

    // DRAFT
    if (!canMake()) return ``;

    return `
      <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px; flex-wrap:wrap">
        <button class="btn" id="btnSaveDraft" type="button">Сохранить черновик</button>
        ${canClose() ? `<button class="btn primary" id="btnCloseShift" type="button">Закрыть смену</button>` : ``}
      </div>
    `;
  })();

  const attItems = Array.isArray(attachments) ? attachments : [];
  const attHtml = attItems.length
    ? attItems
        .map(
          (a) => `
          <div class="row" style="justify-content:space-between; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); align-items:center">
            <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:55%">${esc(a.file_name || "file")}</div>
            <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap">
              <button class="btn" data-ph-open="${esc(a.id)}">Открыть</button>
              <a class="btn" href="${esc(attachmentHref(a.url))}" download style="text-decoration:none">Скачать</a>
              ${canMake() ? `<button class="btn danger" data-att-del="${esc(a.id)}">Удалить</button>` : ``}
            </div>
          </div>
        `
        )
        .join("")
    : `<div class="muted">Файлов нет</div>`;

  const uploadHtml = canMake()
    ? `
      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:10px; flex-wrap:wrap">
        <input id="repFiles" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,image/jpeg,image/png,image/webp,image/heic" multiple />
        <button class="btn" id="btnUpload" type="button">Загрузить</button>
      </div>
    `
    : `<div class="muted" style="margin-top:10px">Нет прав на загрузку файлов</div>`;

  const maps = {
    paymentsTitleById: Object.fromEntries((catalogs?.payments || []).map((x) => [Number(x.id), x.title || `#${x.id}`])),
    departmentsTitleById: Object.fromEntries((catalogs?.departments || []).map((x) => [Number(x.id), x.title || `#${x.id}`])),
    kpisTitleById: Object.fromEntries((catalogs?.kpis || []).map((x) => [Number(x.id), x.title || `#${x.id}`])),
    kpiUnitById: Object.fromEntries((catalogs?.kpis || []).map((x) => [Number(x.id), x.unit || ""])),
  };

  const auditHtml = (canSeeMoney() || isOwnerOrAdmin())
    ? renderAuditSection(audit, maps)
    : `<div class="muted">История скрыта из-за прав доступа</div>`;

  const body = `
    ${topMeta}
    ${section("Сумма оплат", paymentsHtml)}
    ${section(hasDepartments ? "Выручка по департаментам" : "Выручка", deptsHtml)}
    ${section("KPI / доп. продажи", kpisHtml)}
    ${section("Итоги", tipsHtml + totalsHtml + commentHtml)}
    ${actionsHtml}

    <div class="rep-divider"></div>
    ${section("Фото/файлы", `<div style="margin-top:6px">${attHtml}</div>${uploadHtml}`, "Можно прикрепить несколько фотографий")}

    <div class="rep-divider"></div>
    ${section("История изменений", auditHtml, status === "CLOSED" ? "Правки закрытого отчёта логируются" : "Аудит появляется после правок закрытого отчёта")}
  `;

  return { title: formatDateRuNoG(dayISO), subtitle, body, hasDepartments, editEnabled };
}

function collectPayloadFromDom({ dayISO, hasDepartments, tipsEnabled }) {
  const showMoney = canSeeMoney();

  const payload = {
    date: dayISO,
    cash: 0,
    cashless: 0,
    revenue_total: 0,
    tips_total: 0,
    payments: [],
    // IMPORTANT: departments must be omitted when there are no departments configured
    // otherwise backend will overwrite revenue_total with 0.
    departments: hasDepartments ? [] : null,
    kpis: [],
    comment: null,
  };

  if (!showMoney) return payload;

  const inputs = modalBody?.querySelectorAll("input[data-kind]") || [];
  const payments = [];
  const departments = [];
  const kpis = [];

  inputs.forEach((inp) => {
    const kind = String(inp.getAttribute("data-kind") || "");
    const refId = Number(inp.getAttribute("data-ref"));
    if (!Number.isFinite(refId) || refId <= 0) return;
    const v = Math.max(0, numOr0(inp.value));

    if (kind === "PAYMENT") payments.push({ ref_id: refId, value: Math.round(v) });
    else if (kind === "DEPT") departments.push({ ref_id: refId, value: Math.round(v) });
    else if (kind === "KPI") kpis.push({ ref_id: refId, value: Math.round(v) });
  });

  const rev = modalBody?.querySelector("#repRevenueTotal");
  const tips = modalBody?.querySelector("#repTips");
  const comment = modalBody?.querySelector("#repComment");

  payload.revenue_total = Math.round(Math.max(0, numOr0(rev?.value)));
  payload.tips_total = tipsEnabled === false ? 0 : Math.round(Math.max(0, numOr0(tips?.value)));
  payload.comment = String(comment?.value ?? "").trim() || null;

  payload.payments = payments;
  payload.kpis = kpis;

  if (hasDepartments) {
    payload.departments = departments;
    // revenue_total will be computed on backend from departments
    payload.revenue_total = 0;
  }

  // legacy sync for cash/cashless — backend also syncs using payment codes, but we keep compatibility
  // if inputs contain codes 'cash'/'cashless' we can't easily map here (no code in dom),
  // so rely on backend sync. Keep zeros.

  return payload;
}

function wireTotalsLive({ hasDepartments }) {
  const showMoney = canSeeMoney();
  if (!showMoney) return null;

  const update = () => {
    const t = calcTotalsFromDom({ hasDepartments });

    const elPay = modalBody?.querySelector("#t_payments_total");
    const elBase = modalBody?.querySelector("#t_base_total");
    const elDis = modalBody?.querySelector("#t_discrepancy");
    const box = modalBody?.querySelector("#t_discr_box");
    const hint = modalBody?.querySelector("#t_discr_hint");
    const ta = modalBody?.querySelector("#repComment");

    if (elPay) elPay.textContent = fmtRub(t.payments);
    if (elBase) elBase.textContent = fmtRub(t.baseTotal);
    if (elDis) elDis.textContent = fmtRub(t.discrepancy);

    const needComment = t.discrepancy !== 0;
    if (box) {
      box.classList.toggle("is-ok", !needComment);
      box.classList.toggle("is-bad", needComment);
    }
    if (hint) hint.style.display = needComment ? "" : "none";

    if (ta) {
      const empty = !String(ta.value || "").trim();
      ta.classList.toggle("is-required", needComment && empty);
    }

    return t;
  };

  // wire inputs
  modalBody?.querySelectorAll("input[data-kind]")?.forEach((inp) => inp.addEventListener("input", update));
  modalBody?.querySelectorAll("#repRevenueTotal,#repTips,#repComment")?.forEach((x) => x.addEventListener("input", update));

  // initial
  return update();
}

async function wireAttachmentsHandlers({ dayISO, attItems }) {
  // open attachments inside the app (photo viewer)
  modalBody?.querySelectorAll("[data-ph-open]")?.forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-ph-open"));
      const idx = attItems.findIndex((x) => Number(x.id) === id);
      openPhotoModal(attItems, idx >= 0 ? idx : 0, dayISO);
    });
  });

  // delete attachment
  modalBody?.querySelectorAll("[data-att-del]")?.forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!canMake()) return;
      const id = Number(btn.getAttribute("data-att-del"));
      if (!id) return;
      if (!confirm("Удалить файл?")) return;
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/attachments/${encodeURIComponent(id)}`, { method: "DELETE" });
        toast("Удалено", "ok");
        await openDay(dayISO);
      } catch (e) {
        toast("Не удалось удалить: " + (e?.data?.detail || e?.message || "ошибка"), "err");
      }
    });
  });

  // upload
  modalBody?.querySelector("#btnUpload")?.addEventListener("click", async () => {
    if (!canMake()) return;
    const inp = modalBody?.querySelector("#repFiles");
    const files = inp?.files ? Array.from(inp.files) : [];
    if (!files.length) {
      toast("Выбери файлы", "err");
      return;
    }

    const allowed = new Set(["jpg", "jpeg", "png", "webp", "heic"]);
    const bad = files.filter((f) => {
      const name = String(f?.name || "").toLowerCase();
      const ext = name.includes(".") ? name.split(".").pop() : "";
      return !allowed.has(ext);
    });
    if (bad.length) {
      toast("Можно загрузить только: jpg, jpeg, png, webp, heic", "err");
      return;
    }

    try {
      await uploadAttachments(dayISO, files);
      toast("Загружено", "ok");
      await openDay(dayISO);
    } catch (e) {
      const detail = e?.data?.detail ? `: ${e.data.detail}` : (e?.message ? `: ${e.message}` : "");
      toast("Ошибка загрузки" + detail, "err");
    }
  });
}

async function upsertReportFromDom({ dayISO, hasDepartments, tipsEnabled }) {
  const payload = collectPayloadFromDom({ dayISO, hasDepartments, tipsEnabled });
  return api(`/venues/${encodeURIComponent(venueId)}/reports`, {
    method: "POST",
    body: payload,
  });
}

async function openDay(dayISO) {
  if (!venueId) return;
  if (!canView()) return;

  selectedDayISO = dayISO;
  renderMonth();

  // Open modal immediately for instant feedback
  openModal(formatDateRuNoG(dayISO), "Загрузка…", `<div class="skeleton" style="height:120px"></div>`);

  // Load catalogs (active only)
  let catalogs = { payments: [], departments: [], kpis: [] };
  try {
    const [payments, departments, kpis] = await Promise.all([
      withTimeout(getPaymentMethods(venueId, { includeArchived: false }), 8000, "payment methods").catch(() => []),
      withTimeout(getDepartments(venueId, { includeArchived: false }), 8000, "departments").catch(() => []),
      withTimeout(getKpiMetrics(venueId, { includeArchived: false }), 8000, "kpis").catch(() => []),
    ]);
    catalogs = {
      payments: Array.isArray(payments) ? payments : [],
      departments: Array.isArray(departments) ? departments : [],
      kpis: Array.isArray(kpis) ? kpis : [],
    };
  } catch {
    catalogs = { payments: [], departments: [], kpis: [] };
  }

  // Load venue settings (tips)
  let tipsEnabledForVenue = true;
  try {
    const s = await withTimeout(getVenueSettings(venueId), 8000, "venue settings");
    tipsEnabledForVenue = s?.tips_enabled !== false;
  } catch {
    // If settings cannot be loaded, default to showing tips field (backend will still ignore when disabled).
    tipsEnabledForVenue = true;
  }

  // Load report (may not exist)
  let rep = null;
  try {
    rep = await withTimeout(fetchReport(dayISO), 8000, "report");
  } catch (e) {
    if (e?.status === 404 || e?.data?.detail === "Report not found") {
      rep = buildEmptyReportFromCatalogs(dayISO, catalogs);
    } else {
      toast("Ошибка загрузки отчёта: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
      rep = buildEmptyReportFromCatalogs(dayISO, catalogs);
    }
  }

  const att = await withTimeout(fetchAttachments(dayISO), 8000, "attachments").catch(() => ({ items: [] }));
  const attItems = att?.items || [];

  // Audit only makes sense when report exists and CLOSED (or has logs)
  const status = String(rep?.status || "DRAFT").toUpperCase();
  const audit = (status === "CLOSED" || canEditClosed()) ? await withTimeout(fetchAudit(dayISO), 8000, "audit").catch(() => []) : [];

  const st = String(rep?.status || "DRAFT").toUpperCase();
  const isDraft = st !== "CLOSED";
  const initMode = (isDraft && canMake() && canSeeMoney()) ? "edit" : "view";

  const state = { dayISO, rep, catalogs, attachments: attItems, audit, mode: initMode, tipsEnabled: tipsEnabledForVenue };
  let view;
  try {
    view = renderReportModal(state);
  } catch (e) {
    toast("Не удалось отрисовать отчёт: " + (e?.message || "ошибка"), "err");
    openModal(formatDateRuNoG(dayISO), "", `<div class="muted">Не удалось отрисовать отчёт.</div>`);
    return;
  }
  openModal(view.title, view.subtitle, view.body);

  // Live totals only when editing is enabled (draft or enabled closed edit)
  const hasDepartments = view.hasDepartments;
  wireTotalsLive({ hasDepartments });

  await wireAttachmentsHandlers({ dayISO, attItems });

  // Reopen
  modalBody?.querySelector("#btnReopen")?.addEventListener("click", async () => {
    if (!canReopen()) return;
    if (!confirm("Переоткрыть отчёт? Он станет DRAFT.")) return;
    try {
      await reopenReport(dayISO);
      toast("Переоткрыто", "ok");
      await loadMonthReports();
      renderMonth();
      await openDay(dayISO);
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
    }
  });

  // Enable edit for CLOSED
  modalBody?.querySelector("#btnEnableEdit")?.addEventListener("click", async () => {
    if (!canEditClosed()) return;
    const st2 = { ...state, mode: "edit" };
    const v2 = renderReportModal(st2);
    openModal(v2.title, v2.subtitle, v2.body);
    wireTotalsLive({ hasDepartments: v2.hasDepartments });
    await wireAttachmentsHandlers({ dayISO, attItems });

    // Save closed
    modalBody?.querySelector("#btnSaveClosed")?.addEventListener("click", async () => {
      try {
        await upsertReportFromDom({ dayISO, hasDepartments: v2.hasDepartments, tipsEnabled: tipsEnabledForVenue });
        toast("Сохранено (аудит записан)", "ok");
        await loadMonthReports();
        renderMonth();
        await openDay(dayISO);
      } catch (e) {
        toast("Ошибка сохранения: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
      }
    });

    // Reopen handler again
    modalBody?.querySelector("#btnReopen")?.addEventListener("click", async () => {
      if (!canReopen()) return;
      if (!confirm("Переоткрыть отчёт? Он станет DRAFT.")) return;
      try {
        await reopenReport(dayISO);
        toast("Переоткрыто", "ok");
        await loadMonthReports();
        renderMonth();
        await openDay(dayISO);
      } catch (e) {
        toast("Ошибка: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
      }
    });
  });

  // Save draft
  modalBody?.querySelector("#btnSaveDraft")?.addEventListener("click", async () => {
    if (!canMake()) return;
    try {
      await upsertReportFromDom({ dayISO, hasDepartments, tipsEnabled: tipsEnabledForVenue });
      toast("Черновик сохранён", "ok");
      await loadMonthReports();
      renderMonth();
      await openDay(dayISO);
    } catch (e) {
      toast("Ошибка сохранения: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
    }
  });

  // Close shift
  modalBody?.querySelector("#btnCloseShift")?.addEventListener("click", async () => {
    if (!canClose()) return;

    const totals = calcTotalsFromDom({ hasDepartments });
    const comment = String(modalBody?.querySelector("#repComment")?.value || "").trim();

    if (totals.discrepancy !== 0 && !comment) {
      toast("При расхождении нужен комментарий", "err");
      modalBody?.querySelector("#repComment")?.focus();
      return;
    }

    try {
      // 1) save current values
      await upsertReportFromDom({ dayISO, hasDepartments, tipsEnabled: tipsEnabledForVenue });
      // 2) close
      await closeReport(dayISO, comment || null);
      toast("Смена закрыта", "ok");
      await loadMonthReports();
      renderMonth();
      await openDay(dayISO);
    } catch (e) {
      toast("Ошибка закрытия: " + (e?.data?.detail || e?.message || "неизвестно"), "err");
    }
  });
}

// ---- Boot ----
if (el.prev) {
  el.prev.addEventListener("click", async () => {
    curMonth.setMonth(curMonth.getMonth() - 1);
    await loadMonthReports();
    renderMonth();
  });
}
if (el.next) {
  el.next.addEventListener("click", async () => {
    curMonth.setMonth(curMonth.getMonth() + 1);
    await loadMonthReports();
    renderMonth();
  });
}

await loadPerms();
await loadMonthReports();
renderMonth();
