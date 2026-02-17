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

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");

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

function canDeleteAttachments() { return canMake(); }

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
    // remove from local list
    phItems.splice(phIndex, 1);
    if (!phItems.length) { closePhotoModal(); await openDay(phDayISO); return; }
    showPhotoAt(Math.min(phIndex, phItems.length - 1));
    // refresh report modal list too
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
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Отчет";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function esc(s){
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let curMonth = new Date();
curMonth.setDate(1);

let reportsByDate = new Map(); // dateISO -> report
let perms = { role: "", flags: {} };

function canMake() {
  return perms.role === "OWNER" || perms.flags.can_make_reports === true;
}
function canView() {
  return perms.role === "OWNER" || perms.flags.can_view_reports === true || perms.flags.can_make_reports === true;
}
function canSeeMoney() {
  return perms.role === "OWNER" || perms.flags.can_view_revenue === true || perms.flags.can_make_reports === true;
}

async function loadPerms() {
  perms = { role: "", flags: {} };
  if (!venueId) return;
  try {
    const p = await getMyVenuePermissions(venueId);
    perms.role = p?.role || "";
    perms.flags = p?.position_flags || {};
  } catch {
    perms = { role: "", flags: {} };
  }
}

async function loadMonthReports() {
  reportsByDate = new Map();
  if (!venueId) return;
  if (!canView()) return; // не будем бомбить бэк, если явно нет права просмотра
  const m = ym(curMonth);
  try {
    const list = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(m)}`);
    (list || []).forEach((r) => {
      if (r?.date) reportsByDate.set(r.date, r);
    });
  } catch (e) {
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
  el.dayPanel.innerHTML = "";
}

function renderMonth() {
  if (!el.grid || !el.monthLabel) return;

  el.monthLabel.textContent = monthTitle(curMonth);
  el.grid.innerHTML = "";

  if (!canView()) {
    el.grid.innerHTML = `
      <div class="itemcard">
        <b>Нет доступа</b>
        <div class="muted" style="margin-top:6px">
          У вас нет прав на просмотр отчётов.
        </div>
      </div>
    `;
    el.dayPanel.innerHTML = "";
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
  const jsDow = first.getDay(); // 0 Sun..6 Sat
  const mondayBased = (jsDow + 6) % 7; // Mon=0..Sun=6
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

    const hasRep = reportsByDate.has(dStr);
    cell.innerHTML = `
      <div class="cal-num">${d.getDate()}</div>
      <div class="cal-sub muted" style="font-size:11px">${hasRep ? "есть отчёт" : ""}</div>
    `;

    if (ym(d) !== monthStr) cell.classList.add("is-out");
    if (dStr === todayStr) cell.classList.add("is-today");
    if (hasRep) cell.classList.add("has-report");

    cell.onclick = () => openDay(dStr);
    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

function numOr0(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

async function fetchReport(dayISO) {
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}`);
  } catch {
    return null;
  }
}

async function saveReport(dayISO) {
  const cash = Math.max(0, numOr0(document.getElementById("repCash")?.value));
  const cashless = Math.max(0, numOr0(document.getElementById("repCashless")?.value));
  const revenue_total = Math.max(0, numOr0(document.getElementById("repTotal")?.value));
  const tips_total = Math.max(0, numOr0(document.getElementById("repTips")?.value));

  return api(`/venues/${encodeURIComponent(venueId)}/reports`, {
    method: "POST",
    body: { date: dayISO, cash, cashless, revenue_total, tips_total },
  });
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

  // IMPORTANT: send to API_BASE (api-dev). Posting to app-dev (/api/...) can return 405.
  return api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}/attachments`, {
    method: "POST",
    body: fd,
  });
}

function formatDateRuNoG(iso) {
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function attachmentHref(rawUrl) {
  const raw = String(rawUrl || "");
  // backend may return "/api/venues/..." or "/venues/...". We need a working absolute URL to api-dev.
  const path = raw.startsWith("/api/") ? raw.slice(4) : raw;
  if (path.startsWith("/")) return API_BASE + path;
  return raw;
}
async function openDay(dayISO) {
  if (!venueId) return;
  if (!canView()) return;

  const d = new Date(dayISO);
  const title = formatDateRuNoG(d);

  // Открываем модалку сразу, чтобы была мгновенная реакция
  const subtitle = canMake() ? "Редактирование" : "Просмотр";

  let rep = null;
  try {
    rep = await fetchReport(dayISO);
  } catch (e) {
    // если 404 — это норм, отчёта нет
    if (e?.status !== 404 && e?.data?.detail !== "Report not found") {
      toast("Ошибка загрузки отчёта: " + (e?.message || "неизвестно"), "err");
    }
    rep = null;
  }

  const exists = !!rep;
  const canEdit = canMake();
  const showMoney = canSeeMoney();

  const cashVal = rep?.cash ?? "";
  const cashlessVal = rep?.cashless ?? "";
  const totalVal = rep?.revenue_total ?? "";
  const tipsVal = rep?.tips_total ?? "";

  const att = await fetchAttachments(dayISO);
  const attItems = att?.items || [];
  const attHtml = attItems.length
    ? attItems
        .map(
          (a) =>
            `<div class="row" style="justify-content:space-between; gap:10px; padding:8px 0; border-bottom:1px solid var(--border); align-items:center">
              <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:55%">${esc(a.file_name || "file")}</div>
              <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap">
                <button class="btn" data-ph-open="${esc(a.id)}">Открыть</button>
                <a class="btn" href="${esc(attachmentHref(a.url))}" download style="text-decoration:none">Скачать</a>
                ${canEdit ? `<button class="btn danger" data-att-del="${esc(a.id)}">Удалить</button>` : ``}
              </div>
            </div>`
        )
        .join("")
    : `<div class="muted">Файлов нет</div>`;

  const formHtml = `
    <div class="itemcard" style="margin-top: 12px;">
      <div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
          <div class="muted" style="margin-top:4px"><b>${exists ? "Отчёт найден" : "Отчёта нет"}</b></div>

        ${canEdit ? `<button class="btn primary" id="btnSaveRep">${exists ? "Сохранить" : "Создать"}</button>` : ""}
      </div>

      <div class="row" style="gap:10px;flex-wrap:wrap;margin-top:12px">
        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Наличные</div>
          <input id="repCash" type="number" min="0" value="${esc(cashVal)}"
            ${(!canEdit || !showMoney) ? "disabled" : ""}
            placeholder="${showMoney ? "0" : "нет доступа"}" />
        </label>

        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Безналичные</div>
          <input id="repCashless" type="number" min="0" value="${esc(cashlessVal)}"
            ${(!canEdit || !showMoney) ? "disabled" : ""}
            placeholder="${showMoney ? "0" : "нет доступа"}" />
        </label>

        <label style="min-width:220px;display:block">
          <div class="row" style="justify-content:space-between; align-items:center; gap:8px">
            <div class="muted" style="font-size:12px;margin-bottom:4px">Выручка (итого)</div>
              <button
                type="button"
                class="btn"
                id="btnSumTotal"
                style="padding:4px 10px; font-size:12px; line-height:1;"
                ${(!canEdit || !showMoney) ? "disabled" : ""}
                title="Суммировать наличка + безнал"
              >Σ</button></div>
          <input id="repTotal" type="number" min="0" value="${esc(totalVal)}"
            ${(!canEdit || !showMoney) ? "disabled" : ""}
            placeholder="${showMoney ? "0" : "нет доступа"}" />
        </label>

        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Чаевые (итого)</div>
          <input id="repTips" type="number" min="0" value="${esc(tipsVal)}"
            ${(!canEdit || !showMoney) ? "disabled" : ""}
            placeholder="${showMoney ? "0" : "нет доступа"}" />
        </label>
      </div>

      <div class="itemcard" style="margin-top:12px">
        <b>Фото/файлы к отчёту</b>
        <div class="muted" style="margin-top:6px">Можно прикрепить несколько фотографий</div>

        <div style="margin-top:10px">${attHtml}</div>

        ${canEdit ? `
          <div style="margin-top:12px">
            <input id="repFiles" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,image/jpeg,image/png,image/webp,image/heic" multiple />
            <div class="row" style="justify-content:flex-end; gap:8px; margin-top:10px">
              <button class="btn" id="btnUpload">Загрузить</button>
            </div>
          </div>
        ` : `<div class="muted" style="margin-top:10px">Нет прав на загрузку файлов</div>`}
      </div>

      <div class="muted" style="margin-top:10px;font-size:12px">
        ${canEdit ? "Можно сохранить изменения." : "Нет права на создание/редактирование отчётов."}
      </div>
    </div>
  `;

  openModal(title, subtitle, formHtml);

  // open attachments inside the app (photo viewer)
  modalBody?.querySelectorAll("[data-ph-open]")?.forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.getAttribute("data-ph-open"));
      const idx = attItems.findIndex((x) => Number(x.id) === id);
      openPhotoModal(attItems, idx >= 0 ? idx : 0, dayISO);
    });
  });

  // delete attachment from list
  modalBody?.querySelectorAll("[data-att-del]")?.forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!canEdit) return;
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

  if (canEdit) {
    document.getElementById("btnSaveRep")?.addEventListener("click", async () => {
      if (!showMoney) {
        toast("Нет доступа к суммам отчёта", "err");
        return;
      }
      try {
        await saveReport(dayISO);
        toast("Отчёт сохранён", "ok");
        await loadMonthReports();
        renderMonth();
    el.dayPanel.innerHTML = `<div class="muted" style="margin-top:8px">Выберите день в календаре, чтобы посмотреть или заполнить отчёт.</div>`;
        await openDay(dayISO);
      } catch (e) {
        toast("Ошибка сохранения: " + (e?.message || "неизвестно"), "err");
      }
    });
    document.getElementById("btnSumTotal")?.addEventListener("click", () => {
      const cash = Number(document.getElementById("repCash")?.value || 0);
      const cashless = Number(document.getElementById("repCashless")?.value || 0);
      const total = Math.max(0, cash + cashless);
      const repTotal = document.getElementById("repTotal");
      if (repTotal && !repTotal.disabled) repTotal.value = String(total);
    });

    document.getElementById("btnUpload")?.addEventListener("click", async () => {
      const inp = document.getElementById("repFiles");
      const files = inp?.files ? Array.from(inp.files) : [];
      if (!files.length) {
        toast("Выбери файлы", "err");
        return;
      }

      // client-side extension filter (backend validates too)
      const allowed = new Set(["jpg", "jpeg", "png", "webp", "heic"]);
      const bad = files.filter(f => {
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
}

async function boot() {
  if (!venueId) {
    renderNoVenue();
    return;
  }

  try {
    await loadPerms();
    await loadMonthReports();
    renderMonth();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || "неизвестно"), "err");
    renderMonth();
  }
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});

boot();
