import { applyTelegramTheme, mountCommonUI, ensureLogin, mountNav, getActiveVenueId,
  setActiveVenueId, getMyVenues, getMyVenuePermissions, api, toast, confirmModal } from "/app.js?v=20260820-i18nmetrika1";
import { hasPerm, permSetFromResponse, roleUpper } from "/permissions.js";

const $ = (id) => document.getElementById(id);
const weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const t = (text) => window.AxelioI18n?.t?.(text) || text;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const locale = () => window.AxelioI18n?.localeTag?.() || "ru-RU";
const money = (value) => value == null ? "—" : `${(value / 100).toLocaleString(locale(), { maximumFractionDigits: 2 })} ₽`;
const inputMoney = (value) => value == null ? "" : String(value / 100);
const achievement = (value) => value == null ? "—" : `${(value / 100).toLocaleString(locale(), { maximumFractionDigits: 2 })}%`;
const iso = (date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
const state = { venueId: null, canManage: false, data: null, busy: false, requestId: 0 };
const prefix = () => `/venues/${state.venueId}/department-plans`;
const selected = () => `${prefix()}/${$("departmentPick").value}`;

function parseMoney(value) {
  const raw = String(value).trim().replace(/\s/g, "").replace(",", ".");
  if (!raw) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(raw) || Number(raw) <= 0 || Number(raw) > 21474836.47) {
    throw new Error(t("Укажите положительную сумму, не более двух знаков после запятой"));
  }
  return Math.round(Number(raw) * 100);
}

function showError(error) {
  const detail = error?.data?.detail;
  toast(typeof detail === "string" ? detail : detail?.message || error.message || t("Сохранение планов не выполнено"), "err");
}

async function run(action) {
  if (state.busy || !state.canManage) return;
  state.busy = true;
  $("planContent").setAttribute("aria-busy", "true");
  document.querySelectorAll("#planContent button, #planContent input, #departmentPick, #monthPick").forEach((el) => { el.disabled = true; });
  try { await action(); } catch (error) { showError(error); }
  finally {
    state.busy = false;
    $("planContent").setAttribute("aria-busy", "false");
    document.querySelectorAll("#planContent button, #planContent input, #departmentPick, #monthPick").forEach((el) => { el.disabled = false; });
  }
}

function render() {
  const data = state.data;
  $("monthValue").value = inputMoney(data.revenue_plan_minor);
  $("monthActual").textContent = money(data.actual_minor);
  $("monthAchievement").textContent = achievement(data.revenue_achievement_bps);
  $("monthRemaining").textContent = money(data.remaining_minor);
  $("monthProgress").value = Math.min(100, (data.revenue_achievement_bps || 0) / 100);
  $("calendarRows").innerHTML = `<div class="dp-date-head"><span>${t("Дата")}</span><span>${t("План, ₽")}</span><span>${t("Факт")}</span><span>${t("Выполнение")}</span><span></span></div>` + data.days.map((day) => `
    <div class="dp-date-row ${day.revenue_achievement_bps >= 10000 ? "is-achieved" : ""}" data-date="${day.date}">
      <div class="dp-date"><b>${esc(new Date(`${day.date}T12:00:00`).toLocaleDateString(locale(), {day:"numeric", month:"short"}))}</b><span class="dp-day-name">${t(weekdays[day.weekday])}</span></div>
      <input inputmode="decimal" value="${inputMoney(day.revenue_plan_minor)}" placeholder="${t("Не установлен")}" aria-label="${t("План, ₽")} ${day.date}" ${state.canManage ? "" : "disabled"} />
      <span class="dp-actual" data-label="${t("Факт")}">${money(day.actual_minor)}</span><span class="dp-achievement" data-label="${t("Выполнение")}">${achievement(day.revenue_achievement_bps)}</span>
      <button type="button" class="btn ghost" ${state.canManage ? "" : "disabled"}>${t("Сохранить")}</button>
    </div>`).join("");
  if (!state.canManage) document.querySelectorAll("#monthForm input, #monthForm button, #weekForm input, #weekForm button").forEach((el) => { el.disabled = true; });
  $("pageStatus").textContent = state.canManage ? "" : t("Планы доступны только для просмотра");
}

async function load() {
  if (!$("departmentPick").value) return;
  const request = ++state.requestId;
  $("pageStatus").textContent = t("Загрузка…");
  $("planContent").classList.add("hidden");
  try {
    const data = await api(`${selected()}/calendar?month=${$("monthPick").value}`);
    if (request !== state.requestId) return;
    state.data = data;
    if (data.financial_values_hidden) { $("pageStatus").textContent = t("Финансовые показатели скрыты"); return; }
    render();
    $("planContent").classList.remove("hidden");
    const start = data.days[0].date, end = data.days.at(-1).date;
    $("rangeFrom").value = start; $("rangeTo").value = end;
    $("weekAnchor").min = start; $("weekAnchor").max = end;
    $("weekAnchor").value = iso(new Date()).startsWith(data.month) ? iso(new Date()) : start;
    $("bulkHint").textContent = "";
  } catch (error) { if (request === state.requestId) $("pageStatus").textContent = error.message; }
}

function setMode(days) {
  $("daysPanel").classList.toggle("hidden", !days); $("monthPanel").classList.toggle("hidden", days);
  for (const [id, active] of [["daysTab", days], ["monthTab", !days]]) {
    $(id).classList.toggle("active", active); $(id).setAttribute("aria-selected", String(active));
  }
}

async function applyRange(from, to) {
  return run(async () => {
    if (!from || !to || from > to) throw new Error(t("Проверьте диапазон дат"));
    const payload = { department_id: Number($("departmentPick").value), date_from: from, date_to: to,
      overwrite_existing: $("overwriteExisting").checked,
      weekdays: weekdays.map((_, weekday) => ({ weekday, revenue_plan_minor: parseMoney($(`weekday${weekday}`).value) })) };
    const preview = await api(`${prefix()}/days/bulk`, { method: "PUT", body: { ...payload, dry_run: true } });
    if (preview.overwritten_count && !await confirmModal({title: t("Перезаписать планы?"),
      text: `${t("Будут изменены планы для дат:")} ${preview.overwritten_count}. ${t("Продолжить?")}`, confirmText: t("Перезаписать") })) return;
    const result = await api(`${prefix()}/days/bulk`, { method: "PUT", body: { ...payload, preview_token: preview.preview_token } });
    await load();
    $("bulkHint").textContent = `${t("Изменено дат:")} ${result.changed_count} · ${t("Пропущено настроенных дат:")} ${result.skipped_count}`;
    toast(t("Планы сохранены"), "ok");
  });
}

async function clearRangePlans(from, to) {
  return run(async () => {
    if (!from || !to || from > to) throw new Error(t("Проверьте диапазон дат"));
    const payload = {
      department_id: Number($("departmentPick").value),
      date_from: from,
      date_to: to,
      overwrite_existing: true,
      clear_existing: true,
      weekdays: weekdays.map((_, weekday) => ({ weekday, revenue_plan_minor: null })),
    };
    const preview = await api(`${prefix()}/days/bulk`, { method: "PUT", body: { ...payload, dry_run: true } });
    if (!preview.deleted_count) {
      toast(t("В выбранном диапазоне нет установленных планов"), "ok");
      return;
    }
    const confirmed = await confirmModal({
      title: t("Удалить планы по дням?"),
      text: `${t("Будут удалены планы для дат:")} ${preview.deleted_count}. ${t("Зарплата за затронутые закрытые дни будет пересчитана автоматически.")}`,
      confirmText: t("Удалить планы"),
      danger: true,
    });
    if (!confirmed) return;
    const result = await api(`${prefix()}/days/bulk`, {
      method: "PUT",
      body: { ...payload, preview_token: preview.preview_token },
    });
    await load();
    $("bulkHint").textContent = `${t("Удалено планов:")} ${result.deleted_count}`;
    toast(t("Планы удалены"), "ok");
  });
}

async function boot() {
  applyTelegramTheme(); mountCommonUI("summary"); await ensureLogin();
  const params = new URLSearchParams(location.search);
  const venues = await getMyVenues();
  state.venueId = params.get("venue_id") || getActiveVenueId() || venues[0]?.id;
  if (!state.venueId) { $("pageStatus").textContent = t("Сначала создайте заведение"); return; }
  setActiveVenueId(state.venueId); await mountNav({ activeTab: "summary" });
  const [permissions, departments] = await Promise.all([getMyVenuePermissions(state.venueId), api(`/venues/${state.venueId}/departments`)]);
  state.canManage = ["OWNER", "VENUE_OWNER", "SUPER_ADMIN"].includes(roleUpper(permissions))
    || hasPerm(permSetFromResponse(permissions), "PAY_PROFILES_MANAGE");
  $("departmentPick").innerHTML = departments.filter((dep) => dep.is_active !== false).map((dep) => `<option value="${dep.id}">${esc(dep.title)}</option>`).join("");
  if (params.get("department_id") && Array.from($("departmentPick").options).some((opt) => opt.value === params.get("department_id"))) $("departmentPick").value = params.get("department_id");
  $("monthPick").value = /^\d{4}-\d{2}$/.test(params.get("month") || "") ? params.get("month") : iso(new Date()).slice(0,7);
  $("profilesLink").href = `/owner-pay-profiles.html?venue_id=${state.venueId}`;
  $("venuePlansLink").href = `/owner-economics-plans.html?venue_id=${state.venueId}`;
  $("weekInputs").innerHTML = weekdays.map((day, index) => `<label>${t(day)}<input id="weekday${index}" inputmode="decimal" placeholder="—" aria-label="${t(day)}, ₽" /></label>`).join("");
  $("departmentPick").onchange = load; $("monthPick").onchange = load;
  $("daysTab").onclick = () => setMode(true); $("monthTab").onclick = () => setMode(false);
  $("monthForm").onsubmit = (event) => { event.preventDefault(); run(async () => {
    await api(`${selected()}/month?month=${$("monthPick").value}`, {method:"PUT", body: {revenue_plan_minor: parseMoney($("monthValue").value)}});
    await load(); toast(t("План на месяц сохранён"), "ok");
  }); };
  $("weekForm").onsubmit = (event) => event.preventDefault();
  $("applyMonth").onclick = () => applyRange(state.data.days[0].date, state.data.days.at(-1).date);
  $("applyWeek").onclick = () => {
    const anchor = new Date(`${$("weekAnchor").value}T12:00:00`);
    anchor.setDate(anchor.getDate() - (anchor.getDay() + 6) % 7);
    const from = iso(anchor); anchor.setDate(anchor.getDate() + 6);
    applyRange(from < state.data.days[0].date ? state.data.days[0].date : from,
      iso(anchor) > state.data.days.at(-1).date ? state.data.days.at(-1).date : iso(anchor));
  };
  $("toggleRange").onclick = () => { const expanded = $("rangePanel").classList.toggle("hidden") === false; $("toggleRange").setAttribute("aria-expanded", String(expanded)); };
  $("applyRange").onclick = () => applyRange($("rangeFrom").value, $("rangeTo").value);
  $("clearRange").onclick = () => clearRangePlans($("rangeFrom").value, $("rangeTo").value);
  $("calendarRows").oninput = (event) => event.target.closest("[data-date]")?.classList.add("is-dirty");
  $("calendarRows").onclick = (event) => {
    if (!event.target.closest("button")) return;
    const row = event.target.closest("[data-date]");
    run(async () => {
      await api(`${selected()}/day?date=${row.dataset.date}`, {method:"PUT", body:{revenue_plan_minor:parseMoney(row.querySelector("input").value)}});
      await load(); toast(t("План сохранён"), "ok");
    });
  };
  setMode(params.get("mode") === "DAYS");
  if (!departments.length) $("pageStatus").textContent = t("Добавьте департамент в настройках заведения, чтобы задать план.");
  else await load();
}

document.addEventListener("DOMContentLoaded", () => { boot().catch(showError); });
