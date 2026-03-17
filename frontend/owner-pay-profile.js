import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenueMembers,
  getDepartments,
  getKpiMetrics,
  getPayProfile,
  updatePayProfile,
  createPayProfileAssignment,
  updatePayProfileAssignment,
  deletePayProfileAssignment,
  createPayComponent,
  updatePayComponent,
  deletePayComponent,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseParams() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  const profileId = params.get("profile_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return { venueId, profileId };
}

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
  } catch {
    return value.toFixed(2) + "%";
  }
}

function percentInputFromBps(bps) {
  const value = Number(bps || 0) / 100;
  return Number.isFinite(value) ? String(value).replace(/\.0+$/, "") : "";
}

function moneyInputFromMinor(minor) {
  if (minor == null || minor === "") return "";
  const value = Number(minor) / 100;
  if (!Number.isFinite(value)) return "";
  return String(value).replace(/\.0+$/, "");
}

function parseMoneyRubToMinor(value) {
  const normalized = String(value || "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function parsePercentInputToBps(value) {
  const normalized = String(value || "").trim().replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function departmentTitleFor(item) {
  const direct = item?.department_title || item?.department?.title;
  if (direct) return direct;
  const depId = Number(item?.department_id || 0);
  if (!depId) return null;
  const found = (state.departments || []).find((d) => Number(d?.id) === depId);
  return found?.title || `ID ${depId}`;
}

function kpiMetricTitleFor(item) {
  const direct = item?.kpi_metric_title || item?.kpi_metric?.title;
  if (direct) return direct;
  const metricId = Number(item?.kpi_metric_id || 0);
  if (!metricId) return null;
  const found = (state.kpiMetrics || []).find((m) => Number(m?.id) === metricId);
  return found?.title || `KPI #${metricId}`;
}

function stepsTextareaValue(steps) {
  if (!Array.isArray(steps) || !steps.length) return "";
  try {
    const normalized = steps.map((step) => ({
      ...step,
      amount_rub: moneyInputFromMinor(step?.amount_minor),
    })).map(({ amount_minor, ...rest }) => rest);
    return JSON.stringify(normalized, null, 2);
  } catch {
    return "";
  }
}

function parseStepsInput(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  try {
    const value = JSON.parse(text);
    if (!Array.isArray(value)) return null;
    return value.map((step) => {
      if (!step || typeof step !== "object") return step;
      const next = { ...step };
      if (next.amount_minor == null && next.amount_rub != null) {
        const parsed = parseMoneyRubToMinor(next.amount_rub);
        if (parsed != null) next.amount_minor = parsed;
      }
      delete next.amount_rub;
      return next;
    });
  } catch {
    return false;
  }
}

function memberName(member) {
  if (!member) return "—";
  return member.display_name || member.short_name || member.full_name || (member.tg_username ? `@${member.tg_username}` : "—");
}

let state = {
  venueId: "",
  profileId: "",
  me: null,
  perms: null,
  can: { view: false, manage: false },
  profile: null,
  members: [],
  departments: [],
  kpiMetrics: [],
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Профиль зарплаты</b>
          <div class="muted" id="subtitle">компоненты и назначения</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="itemcard">
        <div class="section-head">
          <div class="section-title">
            <b id="profileTitle">—</b>
            <div class="muted mt-6" id="profileDescription">—</div>
          </div>
          <div class="section-actions">
            <button class="btn" id="btnEditProfile">Редактировать</button>
          </div>
        </div>
        <div class="mono mt-8" id="profileMeta">—</div>
      </div>

      <div class="grid grid2 mt-12">
        <div class="itemcard">
          <div class="section-head">
            <div class="section-title"><b>Компоненты</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddComponent">+ Добавить</button></div>
          </div>
          <div class="muted mt-6">Доступны: оклад, почасовая ставка, фикс за смену, проценты по выручке и KPI-бонусы по закрытым отчётам.</div>
          <div id="componentsList" class="mt-12"><div class="skeleton"></div></div>
        </div>

        <div class="itemcard">
          <div class="section-head">
            <div class="section-title"><b>Назначения</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddAssignment">+ Назначить</button></div>
          </div>
          <div class="muted mt-6">Назначения определяют, какой профиль действует у сотрудника в выбранный период.</div>
          <div id="assignmentsList" class="mt-12"><div class="skeleton"></div></div>
        </div>
      </div>

      <div class="row mt-12" style="justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <a class="link" id="backProfiles" href="#">← К списку профилей</a>
        <a class="link" id="openPayroll" href="#">Открыть начисления →</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">Подтверждение</div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body"></div>
      </div>
    </div>

    <div id="editModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Редактирование</b>
            <div class="muted" id="editHint" style="margin-top:4px; font-size:12px"></div>
          </div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function computeCaps(perms, me) {
  const role = roleUpper(perms);
  const pset = permSetFromResponse(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  const isAdmin = sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR";
  return {
    view: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_VIEW") || hasPerm(pset, "PAY_PROFILES_MANAGE"),
    manage: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_MANAGE"),
  };
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function openEditModal({ title, hint, bodyHtml }) {
  const modal = document.getElementById("editModal");
  const titleEl = document.getElementById("editTitle");
  const hintEl = document.getElementById("editHint");
  const bodyEl = document.getElementById("editBody");
  if (titleEl) titleEl.textContent = title || "Редактирование";
  if (hintEl) hintEl.textContent = hint || "";
  if (bodyEl) bodyEl.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeEditModal));
}

function renderHeader() {
  const p = state.profile;
  document.getElementById("title").textContent = p?.title || "Профиль зарплаты";
  document.getElementById("subtitle").textContent = p?.description || "компоненты и назначения";
  document.getElementById("profileTitle").textContent = p?.title || "—";
  document.getElementById("profileDescription").textContent = p?.description || "Без описания";
  document.getElementById("profileMeta").textContent = `Статус: ${p?.is_active ? "активен" : "неактивен"} · Компонентов: ${Number(p?.components?.length || 0)} · Назначений: ${Number(p?.assignments?.length || 0)}`;
  document.getElementById("backProfiles").href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("openPayroll").href = `/owner-payroll.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("btnEditProfile").style.display = state.can.manage ? "" : "none";
  document.getElementById("btnAddComponent").style.display = state.can.manage ? "" : "none";
  document.getElementById("btnAddAssignment").style.display = state.can.manage ? "" : "none";
}

function componentSubtitle(item) {
  const type = String(item?.component_type || "").toUpperCase();
  if (type === "SALARY_FIXED_MONTH") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)}`;
  if (type === "SALARY_HOURLY") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.rate_minor)} / час`;
  if (type === "SALARY_PER_SHIFT") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)} / смена`;
  if (type === "PERCENT_TOTAL_REVENUE") return `${COMPONENT_LABELS[type]} · ${fmtPercentBps(item.percent_bps)}`;
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const depTitle = departmentTitleFor(item);
    return `${COMPONENT_LABELS[type]} · ${fmtPercentBps(item.percent_bps)}${depTitle ? ` · ${depTitle}` : ""} · по отраб. дням`;
  }
  if (type === "KPI_BONUS") {
    const metricTitle = kpiMetricTitleFor(item);
    const threshold = item.threshold_value != null ? ` · порог ${item.threshold_value}` : "";
    const stepsCount = Array.isArray(item.steps) && item.steps.length ? ` · ступеней: ${item.steps.length}` : "";
    return `${COMPONENT_LABELS[type]}${metricTitle ? ` · ${metricTitle}` : ""}${threshold}${stepsCount}${item.amount_minor != null ? ` · ${fmtMoneyMinor(item.amount_minor)}` : ""}`;
  }
  return `${type} · ${fmtMoneyMinor(item.amount_minor || item.rate_minor || 0)}`;
}

function renderComponents() {
  const el = document.getElementById("componentsList");
  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="muted">Нет доступа</div>`;
    return;
  }
  const items = Array.isArray(state.profile?.components) ? state.profile.components : [];
  if (!items.length) {
    el.innerHTML = `<div class="muted">Компоненты ещё не добавлены</div>`;
    return;
  }
  el.innerHTML = "";
  items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(it.title)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивен</span>`}
        </div>
        <div class="muted mt-6">${esc(COMPONENT_LABELS[String(it.component_type || "").toUpperCase()] || it.component_type || "Компонент")}</div>
        <div class="mono listrow__meta">${esc(componentSubtitle(it))} · sort=${Number(it.sort_order || 0)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;" id="componentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#componentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Редакт.";
      editBtn.onclick = () => openComponentEditor({ mode: "edit", item: it });
      actions.appendChild(editBtn);

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "btn sm" + (it.is_active ? " danger" : "");
      toggleBtn.textContent = it.is_active ? "Отключить" : "Включить";
      toggleBtn.onclick = async () => {
        try {
          await updatePayComponent(state.venueId, it.id, { is_active: !it.is_active });
          toast("Компонент обновлён", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
        }
      };
      actions.appendChild(toggleBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить компонент?",
          text: `Удалить компонент "${it.title}"?`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayComponent(state.venueId, it.id);
          toast("Компонент удалён", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось удалить"), "err");
        }
      };
      actions.appendChild(deleteBtn);
    }
    el.appendChild(row);
  });
}

function renderAssignments() {
  const el = document.getElementById("assignmentsList");
  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="muted">Нет доступа</div>`;
    return;
  }
  const items = Array.isArray(state.profile?.assignments) ? state.profile.assignments : [];
  if (!items.length) {
    el.innerHTML = `<div class="muted">Назначений пока нет</div>`;
    return;
  }
  el.innerHTML = "";
  items.forEach((it) => {
    const label = memberName(it.member);
    const range = `${it.start_date || "без даты начала"} → ${it.end_date || "без даты окончания"}`;
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(label)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивно</span>`}
        </div>
        <div class="mono listrow__meta">${esc(range)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;" id="assignmentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#assignmentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Редакт.";
      editBtn.onclick = () => openAssignmentEditor({ mode: "edit", item: it });
      actions.appendChild(editBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить назначение?",
          text: `Удалить назначение для ${label}?`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayProfileAssignment(state.venueId, it.id);
          toast("Назначение удалено", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось удалить"), "err");
        }
      };
      actions.appendChild(deleteBtn);
    }
    el.appendChild(row);
  });
}

function componentForm({ mode, item }) {
  const it = item || {};
  const type = String(it.component_type || "SALARY_FIXED_MONTH").toUpperCase();
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasDepartments = Array.isArray(state.departments) && state.departments.length > 0;
  const departmentOptions = state.departments.map((dep) => `<option value="${esc(dep.id)}" ${Number(dep.id) === Number(it.department_id) ? "selected" : ""}>${esc(dep.title)}</option>`).join("");
  const hasKpiMetrics = Array.isArray(state.kpiMetrics) && state.kpiMetrics.length > 0;
  const kpiOptions = state.kpiMetrics.map((metric) => `<option value="${esc(metric.id)}" ${Number(metric.id) === Number(it.kpi_metric_id) ? "selected" : ""}>${esc(metric.title)}</option>`).join("");
  return `
    <div class="finance-form mt-8">
      <label>
        <span>Тип</span>
        <select id="f_component_type">
          <option value="SALARY_FIXED_MONTH" ${type === "SALARY_FIXED_MONTH" ? "selected" : ""}>Оклад за месяц</option>
          <option value="SALARY_HOURLY" ${type === "SALARY_HOURLY" ? "selected" : ""}>Почасовая ставка</option>
          <option value="SALARY_PER_SHIFT" ${type === "SALARY_PER_SHIFT" ? "selected" : ""}>Фикс за смену</option>
          <option value="PERCENT_TOTAL_REVENUE" ${type === "PERCENT_TOTAL_REVENUE" ? "selected" : ""}>% от общей выручки</option>
          <option value="PERCENT_DEPARTMENT_REVENUE" ${type === "PERCENT_DEPARTMENT_REVENUE" ? "selected" : ""}>% от выручки департамента</option>
          <option value="KPI_BONUS" ${type === "KPI_BONUS" ? "selected" : ""}>KPI-бонус</option>
        </select>
      </label>
      <label>
        <span>Название компонента</span>
        <input id="f_title" placeholder="Оклад" value="${esc(it.title || "")}" />
      </label>
      <label id="f_amount_wrap">
        <span id="f_amount_label">Сумма, ₽</span>
        <input id="f_amount_minor" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(it.amount_minor))}" />
      </label>
      <label id="f_rate_wrap">
        <span id="f_rate_label">Ставка, ₽ / час</span>
        <input id="f_rate_minor" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(it.rate_minor))}" />
      </label>
      <label id="f_percent_wrap">
        <span id="f_percent_label">Процент</span>
        <input id="f_percent" inputmode="decimal" placeholder="Например, 5" value="${esc(percentInputFromBps(it.percent_bps))}" />
      </label>
      ${hasDepartments ? `
      <label id="f_department_wrap">
        <span>Департамент</span>
        <select id="f_department_id">
          <option value="">Выбери департамент</option>
          ${departmentOptions}
        </select>
      </label>` : `
      <label id="f_department_wrap">
        <span>ID департамента</span>
        <input id="f_department_id" inputmode="numeric" placeholder="Например: 3" value="${esc(it.department_id ?? "")}" />
      </label>
      <div id="f_department_hint" class="muted">Список департаментов не загрузился. Можно указать department_id вручную.</div>`}
      ${hasKpiMetrics ? `
      <label id="f_kpi_metric_wrap">
        <span>KPI-метрика</span>
        <select id="f_kpi_metric_id">
          <option value="">Выбери KPI</option>
          ${kpiOptions}
        </select>
      </label>` : `
      <label id="f_kpi_metric_wrap">
        <span>ID KPI-метрики</span>
        <input id="f_kpi_metric_id" inputmode="numeric" placeholder="Например: 5" value="${esc(it.kpi_metric_id ?? "")}" />
      </label>
      <div id="f_kpi_metric_hint" class="muted">Список KPI не загрузился. Можно указать kpi_metric_id вручную.</div>`}
      <label id="f_threshold_wrap">
        <span id="f_threshold_label">Порог KPI</span>
        <input id="f_threshold_value" inputmode="numeric" placeholder="Например: 30" value="${esc(it.threshold_value ?? "")}" />
      </label>
      <label id="f_steps_wrap">
        <span>Ступени бонуса (JSON, опционально)</span>
        <textarea id="f_steps_json" rows="6" placeholder='[{"threshold_value":10,"amount_rub":500},{"threshold_value":20,"amount_rub":1000}]'>${esc(stepsTextareaValue(it.steps))}</textarea>
      </label>
      <div id="f_steps_hint" class="muted">Если заполнены ступени, будет выбрана максимальная подходящая ступень. Суммы в JSON указывай в рублях через поле amount_rub. Если оставить пусто — сработает обычный порог и сумма.</div>
      <label>
        <span>Порядок</span>
        <input id="f_sort_order" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
      </label>
      <label class="chk">
        <input type="checkbox" id="f_active" ${activeChecked} />
        <span>Компонент активен</span>
      </label>
    </div>

    <div class="row mt-12" style="justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function syncComponentFields() {
  const type = String(document.getElementById("f_component_type")?.value || "SALARY_FIXED_MONTH").toUpperCase();
  const amountWrap = document.getElementById("f_amount_wrap");
  const rateWrap = document.getElementById("f_rate_wrap");
  const percentWrap = document.getElementById("f_percent_wrap");
  const departmentWrap = document.getElementById("f_department_wrap");
  const departmentHint = document.getElementById("f_department_hint");
  const kpiMetricWrap = document.getElementById("f_kpi_metric_wrap");
  const kpiMetricHint = document.getElementById("f_kpi_metric_hint");
  const thresholdWrap = document.getElementById("f_threshold_wrap");
  const stepsWrap = document.getElementById("f_steps_wrap");
  const stepsHint = document.getElementById("f_steps_hint");
  const amountLabel = document.getElementById("f_amount_label");
  const rateLabel = document.getElementById("f_rate_label");
  const percentLabel = document.getElementById("f_percent_label");
  const thresholdLabel = document.getElementById("f_threshold_label");

  [amountWrap, rateWrap, percentWrap, departmentWrap, departmentHint, kpiMetricWrap, kpiMetricHint, thresholdWrap, stepsWrap, stepsHint].forEach((el) => {
    if (el) el.style.display = "none";
  });

  if (type === "SALARY_HOURLY") {
    if (rateWrap) rateWrap.style.display = "grid";
    if (rateLabel) rateLabel.textContent = "Ставка, ₽ / час";
    return;
  }

  if (type === "SALARY_FIXED_MONTH" || type === "SALARY_PER_SHIFT") {
    if (amountWrap) amountWrap.style.display = "grid";
    if (amountLabel) amountLabel.textContent = type === "SALARY_PER_SHIFT" ? "Сумма, ₽ / смена" : "Сумма, ₽ / месяц";
    return;
  }

  if (type === "PERCENT_TOTAL_REVENUE") {
    if (percentWrap) percentWrap.style.display = "grid";
    if (percentLabel) percentLabel.textContent = "Процент от общей выручки";
    return;
  }

  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    if (percentWrap) percentWrap.style.display = "grid";
    if (departmentWrap) departmentWrap.style.display = "grid";
    if (departmentHint) departmentHint.style.display = "";
    if (percentLabel) percentLabel.textContent = "Процент от выручки департамента";
    return;
  }

  if (type === "KPI_BONUS") {
    if (amountWrap) amountWrap.style.display = "grid";
    if (amountLabel) amountLabel.textContent = "Бонус, ₽";
    if (kpiMetricWrap) kpiMetricWrap.style.display = "grid";
    if (kpiMetricHint) kpiMetricHint.style.display = "";
    if (thresholdWrap) thresholdWrap.style.display = "grid";
    if (stepsWrap) stepsWrap.style.display = "grid";
    if (stepsHint) stepsHint.style.display = "";
    if (thresholdLabel) thresholdLabel.textContent = "Порог KPI";
  }
}

function openComponentEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать компонент" : "Новый компонент",
    hint: "Поддержаны ставки, проценты и KPI-бонусы",
    bodyHtml: componentForm({ mode, item }),
  });
  document.getElementById("f_component_type")?.addEventListener("change", syncComponentFields);
  syncComponentFields();
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const componentType = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
    const title = String(document.getElementById("f_title")?.value || "").trim();
    const amountMinorRaw = String(document.getElementById("f_amount_minor")?.value || "").trim();
    const rateMinorRaw = String(document.getElementById("f_rate_minor")?.value || "").trim();
    const percentRaw = String(document.getElementById("f_percent")?.value || "").trim();
    const departmentRaw = String(document.getElementById("f_department_id")?.value || "").trim();
    const sortRaw = String(document.getElementById("f_sort_order")?.value || "0").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    if (!title) {
      toast("Укажи название компонента", "warn");
      return;
    }

    const kpiMetricRaw = String(document.getElementById("f_kpi_metric_id")?.value || "").trim();
    const thresholdRaw = String(document.getElementById("f_threshold_value")?.value || "").trim();
    const stepsRaw = String(document.getElementById("f_steps_json")?.value || "").trim();

    const payload = {
      component_type: componentType,
      title,
      amount_minor: null,
      rate_minor: null,
      percent_bps: null,
      department_id: null,
      kpi_metric_id: null,
      threshold_value: null,
      steps_json: null,
      sort_order: Number(sortRaw || 0),
      is_active: isActive,
    };

    if (componentType === "SALARY_HOURLY") {
      if (!rateMinorRaw) {
        toast("Укажи почасовую ставку в рублях", "warn");
        return;
      }
      payload.rate_minor = parseMoneyRubToMinor(rateMinorRaw);
      if (payload.rate_minor === null) {
        toast("Некорректная почасовая ставка", "warn");
        return;
      }
    } else if (componentType === "SALARY_FIXED_MONTH" || componentType === "SALARY_PER_SHIFT") {
      if (!amountMinorRaw) {
        toast("Укажи сумму в рублях", "warn");
        return;
      }
      payload.amount_minor = parseMoneyRubToMinor(amountMinorRaw);
      if (payload.amount_minor === null) {
        toast("Некорректная сумма", "warn");
        return;
      }
    } else if (componentType === "PERCENT_TOTAL_REVENUE") {
      const percentBps = parsePercentInputToBps(percentRaw);
      if (percentBps === null) {
        toast("Укажи процент, например 5 или 7.5", "warn");
        return;
      }
      payload.percent_bps = percentBps;
    } else if (componentType === "PERCENT_DEPARTMENT_REVENUE") {
      const percentBps = parsePercentInputToBps(percentRaw);
      if (percentBps === null) {
        toast("Укажи процент, например 5 или 7.5", "warn");
        return;
      }
      if (!departmentRaw) {
        toast("Выбери департамент", "warn");
        return;
      }
      payload.percent_bps = percentBps;
      payload.department_id = Number(departmentRaw);
    } else if (componentType === "KPI_BONUS") {
      if (!kpiMetricRaw) {
        toast("Выбери KPI-метрику", "warn");
        return;
      }
      payload.kpi_metric_id = Number(kpiMetricRaw);
      if (thresholdRaw) payload.threshold_value = Number(thresholdRaw);
      const parsedSteps = parseStepsInput(stepsRaw);
      if (parsedSteps === false) {
        toast("Ступени должны быть валидным JSON-массивом", "warn");
        return;
      }
      if (Array.isArray(parsedSteps) && parsedSteps.length) {
        payload.steps_json = parsedSteps;
      } else {
        if (!amountMinorRaw) {
          toast("Укажи бонус в рублях или заполни ступени", "warn");
          return;
        }
        payload.amount_minor = parseMoneyRubToMinor(amountMinorRaw);
        if (payload.amount_minor === null) {
          toast("Некорректный бонус", "warn");
          return;
        }
      }
    }

    try {
      if (isEdit && item?.id) {
        await updatePayComponent(state.venueId, item.id, payload);
        toast("Компонент обновлён", "ok");
      } else {
        await createPayComponent(state.venueId, state.profileId, payload);
        toast("Компонент создан", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

function assignmentForm({ mode, item }) {
  const it = item || {};
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasMembers = Array.isArray(state.members) && state.members.length > 0;
  const options = state.members.map((m) => `<option value="${esc(m.user_id)}">${esc(memberName(m))}</option>`).join("");
  return `
    <div class="finance-form mt-8">
      ${mode === "edit" ? `
        <label>
          <span>Сотрудник</span>
          <input value="${esc(memberName(it.member))}" disabled />
        </label>
      ` : hasMembers ? `
        <label>
          <span>Сотрудник</span>
          <select id="f_member_user_id">
            <option value="">Выбери сотрудника</option>
            ${options}
          </select>
        </label>
      ` : `
        <label>
          <span>User ID сотрудника</span>
          <input id="f_member_user_id" inputmode="numeric" placeholder="Например: 12" />
        </label>
        <div class="muted">Список сотрудников не загрузился. Можно ввести user_id вручную.</div>
      `}
      <label>
        <span>Дата начала</span>
        <input id="f_start_date" type="date" value="${esc(it.start_date || "")}" />
      </label>
      <label>
        <span>Дата окончания</span>
        <input id="f_end_date" type="date" value="${esc(it.end_date || "")}" />
      </label>
      <label class="chk">
        <input type="checkbox" id="f_active" ${activeChecked} />
        <span>Назначение активно</span>
      </label>
    </div>

    <div class="row mt-12" style="justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function openAssignmentEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать назначение" : "Новое назначение",
    hint: "Если даты пустые, профиль считается действующим без ограничений",
    bodyHtml: assignmentForm({ mode, item }),
  });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const memberUserId = String(document.getElementById("f_member_user_id")?.value || "").trim();
    const startDate = String(document.getElementById("f_start_date")?.value || "").trim();
    const endDate = String(document.getElementById("f_end_date")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    const payload = {
      start_date: startDate || null,
      end_date: endDate || null,
      is_active: isActive,
    };

    if (!isEdit) {
      if (!memberUserId) {
        toast("Выбери сотрудника", "warn");
        return;
      }
      payload.member_user_id = Number(memberUserId);
    }

    try {
      if (isEdit && item?.id) {
        await updatePayProfileAssignment(state.venueId, item.id, payload);
        toast("Назначение обновлено", "ok");
      } else {
        await createPayProfileAssignment(state.venueId, state.profileId, payload);
        toast("Назначение создано", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

function openProfileEditor() {
  if (!state.can.manage || !state.profile) return;
  openEditModal({
    title: "Редактировать профиль",
    hint: "Изменения применятся ко всем последующим расчётам",
    bodyHtml: `
      <div class="finance-form mt-8">
        <label>
          <span>Название</span>
          <input id="f_title" value="${esc(state.profile.title || "")}" />
        </label>
        <label>
          <span>Описание</span>
          <textarea id="f_description" rows="4">${esc(state.profile.description || "")}</textarea>
        </label>
        <label class="chk">
          <input type="checkbox" id="f_active" ${state.profile.is_active ? "checked" : ""} />
          <span>Профиль активен</span>
        </label>
      </div>
      <div class="row mt-12" style="justify-content:flex-end; gap:8px">
        <button class="btn" id="btnCancel" type="button">Отмена</button>
        <button class="btn primary" id="btnSave" type="button">Сохранить</button>
      </div>
    `,
  });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const title = String(document.getElementById("f_title")?.value || "").trim();
    const description = String(document.getElementById("f_description")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;
    if (!title) {
      toast("Укажи название профиля", "warn");
      return;
    }
    try {
      await updatePayProfile(state.venueId, state.profileId, {
        title,
        description: description || null,
        is_active: isActive,
      });
      toast("Профиль обновлён", "ok");
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

async function load() {
  const componentsList = document.getElementById("componentsList");
  const assignmentsList = document.getElementById("assignmentsList");
  if (componentsList) componentsList.innerHTML = `<div class="skeleton"></div>`;
  if (assignmentsList) assignmentsList.innerHTML = `<div class="skeleton"></div>`;

  try {
    state.profile = await getPayProfile(state.venueId, state.profileId);
  } catch (e) {
    root.innerHTML = `<div class="card"><div class="muted">Ошибка загрузки профиля: ${esc(e?.data?.detail || e?.message || "не удалось загрузить")}</div></div>`;
    return;
  }

  renderHeader();
  renderComponents();
  renderAssignments();
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  wireEditModalClose();
  await ensureLogin({ silent: true });

  const params = parseParams();
  state.venueId = params.venueId;
  state.profileId = params.profileId;

  if (!state.venueId || !state.profileId) {
    root.innerHTML = `<div class="card"><div class="muted">Не найден venue_id или profile_id</div></div>`;
    return;
  }

  await mountNav({ activeTab: "summary" });

  try {
    state.me = await getMe();
  } catch {
    state.me = null;
  }

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
  } catch {
    state.perms = null;
  }

  state.can = computeCaps(state.perms, state.me);

  try {
    const membersResp = await getVenueMembers(state.venueId);
    state.members = Array.isArray(membersResp?.members) ? membersResp.members : [];
  } catch {
    state.members = [];
  }

  try {
    const depsResp = await getDepartments(state.venueId);
    state.departments = Array.isArray(depsResp) ? depsResp : [];
  } catch {
    state.departments = [];
  }

  try {
    const kpiResp = await getKpiMetrics(state.venueId, { includeArchived: false });
    state.kpiMetrics = Array.isArray(kpiResp) ? kpiResp : [];
  } catch {
    state.kpiMetrics = [];
  }

  document.getElementById("btnEditProfile")?.addEventListener("click", openProfileEditor);
  document.getElementById("btnAddComponent")?.addEventListener("click", () => openComponentEditor({ mode: "create" }));
  document.getElementById("btnAddAssignment")?.addEventListener("click", () => openAssignmentEditor({ mode: "create" }));

  await load();
}

document.addEventListener("DOMContentLoaded", boot);
