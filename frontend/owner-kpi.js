import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getMyVenuePermissions,
  getKpiMetrics,
  createKpiMetric,
  updateKpiMetric,
  applyDemoReadonlyCaps,
} from "/app.js?v=20260726-navmore1";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function has(perms, code) {
  const arr = perms?.permissions;
  return Array.isArray(arr) && arr.includes(code);
}

function isOwner(perms) {
  return String(perms?.role || "").toUpperCase() === "OWNER";
}


function slugifyCode(value, fallback = "item") {
  const map = { а:"a", б:"b", в:"v", г:"g", д:"d", е:"e", ё:"e", ж:"zh", з:"z", и:"i", й:"y", к:"k", л:"l", м:"m", н:"n", о:"o", п:"p", р:"r", с:"s", т:"t", у:"u", ф:"f", х:"h", ц:"ts", ч:"ch", ш:"sh", щ:"sch", ъ:"", ы:"y", ь:"", э:"e", ю:"yu", я:"ya" };
  return String(value || "")
    .trim()
    .toLowerCase()
    .split("")
    .map((ch) => (map[ch] !== undefined ? map[ch] : ch))
    .join("")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .slice(0, 64) || fallback;
}

function ensureUniqueCode(baseCode, items = [], currentId = null) {
  const used = new Set((Array.isArray(items) ? items : [])
    .filter((it) => currentId == null || String(it?.id ?? "") !== String(currentId))
    .map((it) => String(it?.code || "").trim().toLowerCase())
    .filter(Boolean));
  let code = String(baseCode || "").trim().toLowerCase();
  if (!code) code = "item";
  if (!used.has(code)) return code;
  let idx = 2;
  while (used.has(`${code}_${idx}`)) idx += 1;
  return `${code}_${idx}`;
}


function renderShell() {
  root.innerHTML = `
    <div class="topbar catalog-topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Планы и KPI</b>
          <div class="muted">метрики для бонусов</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card catalog-hero">
      <div class="muted catalog-intro">Создайте KPI-метрики (например: Фруктовые чаши, Лимонады, Допродажи). Они появятся в отчёте закрытия смены.</div>

      <div class="itemcard catalog-list-card">
        <div class="section-head">
          <div class="section-title">
            <b>Список KPI</b>
          </div>
            <div class="section-actions">
              <button class="btn primary" id="btnCreate">+ Добавить</button>
            </div>
        </div>
        <div class="section-actions catalog-filter" id="catalogFilter">
          <label class="chk">
            <input type="checkbox" id="showArchived" />
            <span class="muted">Показывать архив</span>
          </label>
        </div>

        <div id="list" class="catalog-list" aria-live="polite">
          <div class="catalog-loading" aria-busy="true"><div class="skeleton"></div><div class="skeleton"></div></div>
        </div>
      </div>

      <div class="catalog-footer">
        <button class="btn subtle inline" id="back" type="button" data-nav-button>← Назад к заведению</button>
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
            <b class="modal__title" id="editTitle">Показатель</b>
            <div class="muted small mt-4" id="editHint"></div>
          </div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div class="nav">
      <div class="wrap"><div id="nav"></div></div>
    </div>
  `;

  mountCommonUI("none");
}

function openEditModal({ title, hint, bodyHtml }) {
  const m = document.getElementById("editModal");
  const t = document.getElementById("editTitle");
  const h = document.getElementById("editHint");
  const b = document.getElementById("editBody");
  if (t) t.textContent = title || "KPI";
  if (h) h.textContent = hint || "";
  if (b) b.innerHTML = bodyHtml || "";
  m?.classList.add("open");
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((x) => x.addEventListener("click", closeEditModal));
}


function usageSummary(metric) {
  const total = Number(metric?.usage_component_count || 0);
  const boost = Number(metric?.usage_boost_component_count || 0);
  const bonus = Number(metric?.usage_bonus_component_count || 0);
  if (!total) return 'Пока не используется в начислениях';
  const parts = [];
  if (bonus) parts.push(`бонусов: ${bonus}`);
  if (boost) parts.push(`повышений %: ${boost}`);
  return `Используется в начислениях · ${parts.join(' · ')}`;
}

const UNIT_LABEL = {
  QTY: "Штуки (QTY)",
  RUB: "Рубли (RUB)",
  PERCENT: "Проценты (PERCENT)",
  CUSTOM: "Другое (CUSTOM)",
};

function unitOptions(selected) {
  const sel = String(selected || "QTY").toUpperCase();
  const items = ["QTY", "RUB", "PERCENT", "CUSTOM"];
  return items.map((u) => `<option value="${u}" ${u === sel ? "selected" : ""}>${UNIT_LABEL[u] || u}</option>`).join("");
}

let state = {
  venueId: "",
  perms: null,
  items: [],
  loadError: "",
  includeArchived: false,
  can: { view: false, create: false, edit: false, archive: false },
};

function computeCaps(perms) {
  const owner = isOwner(perms);
  return {
    view: owner || has(perms, "KPI_METRICS_VIEW"),
    create: owner || has(perms, "KPI_METRICS_CREATE"),
    edit: owner || has(perms, "KPI_METRICS_EDIT"),
    archive: owner || has(perms, "KPI_METRICS_ARCHIVE"),
  };
}

function renderList() {
  const el = document.getElementById("list");
  if (!el) return;

  if (!state.can.view) {
    el.innerHTML = `<div class="catalog-state catalog-state--denied"><b>Нет доступа к KPI</b><span>Обратитесь к владельцу заведения, чтобы получить право просмотра.</span></div>`;
    return;
  }

  if (state.loadError) {
    el.innerHTML = `<div class="catalog-state catalog-state--error"><b>Не удалось загрузить KPI</b><span>${esc(state.loadError)}</span></div>`;
    return;
  }

  if (!state.items.length) {
    el.innerHTML = `<div class="catalog-state catalog-state--empty"><b>KPI пока нет</b><span>Добавьте первую метрику для отчёта закрытия смены и начислений.</span></div>`;
    return;
  }

  el.innerHTML = "";
  for (const it of state.items) {
    const row = document.createElement("div");
    row.className = "catalog-row";

    const left = document.createElement("div");
    left.className = "catalog-row__copy";
    const unit = String(it.unit || "QTY").toUpperCase();
    left.innerHTML = `
      <div class="catalog-row__title">
        <b>${esc(it.title)}</b>
        ${it.is_active ? "" : `<span class="badge">архив</span>`}
        ${Number(it.usage_component_count || 0) > 0 ? `<span class="badge">в начислениях: ${esc(it.usage_component_count)}</span>` : ``}
      </div>
      <div class="muted catalog-row__meta">Единица измерения: ${esc(UNIT_LABEL[unit] || unit)}</div>
      <div class="muted catalog-row__meta">${esc(usageSummary(it))}</div>
    `;

    const right = document.createElement("div");
    right.className = "catalog-row__actions";

    if (state.can.edit) {
      const btnEdit = document.createElement("button");
      btnEdit.className = "btn sm";
      btnEdit.textContent = "Изменить";
      btnEdit.onclick = () => openEditor({ mode: "edit", item: it });
      right.appendChild(btnEdit);
    }

    if (state.can.archive) {
      const btn = document.createElement("button");
      btn.className = "btn sm" + (it.is_active ? " danger" : "");
      btn.textContent = it.is_active ? "В архив" : "Вернуть";
      btn.onclick = async () => {
        const ok = await confirmModal({
          title: it.is_active ? "Архивировать KPI?" : "Восстановить KPI?",
          text: `${it.is_active ? "Убрать" : "Вернуть"} "${it.title}"?${Number(it.usage_component_count || 0) > 0 ? ` Метрика используется в ${it.usage_component_count} компонент(ах) начислений.` : ''}`,
          confirmText: it.is_active ? "В архив" : "Вернуть",
          danger: it.is_active,
        });
        if (!ok) return;
        try {
          await updateKpiMetric(state.venueId, it.id, { is_active: !it.is_active });
          toast("Готово", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + e.message, "err");
        }
      };
      right.appendChild(btn);
    }

    row.appendChild(left);
    row.appendChild(right);
    el.appendChild(row);
  }
}

function editorForm({ mode, item }) {
  const it = item || {};
  const isEdit = mode === "edit";
  const activeChecked = (isEdit ? !!it.is_active : true) ? "checked" : "";
  const unit = String(it.unit || "QTY").toUpperCase();

  return `
    <div class="grid grid2 catalog-form">
      <div>
        <div class="muted mb-6">Название</div>
        <input id="f_title" placeholder="Фруктовые чаши" value="${esc(it.title || "")}" />
      </div>
      <div>
        <div class="muted mb-6">Единица</div>
        <select id="f_unit">${unitOptions(unit)}</select>
      </div>
      <div>
        <div class="muted mb-6">Порядок в списке</div>
        <input id="f_sort" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
      </div>
      <div>
        <div class="muted mb-6">Отображение</div>
        <label class="row gap-8 ai-center">
          <input type="checkbox" id="f_active" ${activeChecked} />
          <span>Показывать в списке</span>
        </label>
      </div>
    </div>

    <div class="catalog-modal-actions">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function wireEditor({ mode, item }) {
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  const titleEl = document.getElementById("f_title");
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const title = document.getElementById("f_title")?.value?.trim();
    const code = ensureUniqueCode(slugifyCode(title, "kpi_metric"), state.items, item?.id ?? null);
    const unit = document.getElementById("f_unit")?.value?.trim();
    const sort = document.getElementById("f_sort")?.value;
    const is_active = !!document.getElementById("f_active")?.checked;

    if (!title) return toast("Укажи название", "err");

    const payload = { code, title, unit: (unit || "QTY").toUpperCase(), sort_order: Number(sort || 0), is_active };

    try {
      if (mode === "create") {
        await createKpiMetric(state.venueId, payload);
      } else {
        await updateKpiMetric(state.venueId, item.id, payload);
      }
      closeEditModal();
      toast("Сохранено", "ok");
      await load();
    } catch (e) {
      toast("Ошибка: " + e.message, "err");
    }
  });
}

function openEditor({ mode, item }) {
  if (mode === "create" && !state.can.create) {
    toast("Нет прав на создание", "err");
    return;
  }
  if (mode === "edit" && !state.can.edit) {
    toast("Нет прав на редактирование", "err");
    return;
  }

  openEditModal({
    title: mode === "create" ? "Новый KPI" : "KPI",
    hint: mode === "create" ? "Добавь KPI, который будет в отчёте закрытия смены" : "Редактирование KPI",
    bodyHtml: editorForm({ mode, item }),
  });
  wireEditor({ mode, item });
}

async function load() {
  const listEl = document.getElementById("list");
  if (listEl) listEl.innerHTML = `<div class="catalog-loading" aria-busy="true"><div class="skeleton"></div><div class="skeleton"></div></div>`;

  if (!state.can.view) {
    state.items = [];
    state.loadError = "";
    renderList();
    return;
  }

  try {
    const items = await getKpiMetrics(state.venueId, { includeArchived: state.includeArchived });
    state.items = Array.isArray(items) ? items : [];
    state.loadError = "";
  } catch (e) {
    state.items = [];
    state.loadError = e?.message || "Повторите попытку позже.";
    toast("Ошибка загрузки: " + e.message, "err");
  }

  renderList();
}

(async () => {
  applyTelegramTheme();
  renderShell();

  await ensureLogin({ silent: true });

  state.venueId = parseVenueId();
  if (!state.venueId) {
    location.replace("/app-venues.html");
    return;
  }

  await mountNav({ activeTab: "venue", requireVenue: true });

  const back = document.getElementById("back");
  if (back) back.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
  } catch {
    state.perms = null;
  }
  state.can = applyDemoReadonlyCaps(computeCaps(state.perms), { source: state.perms });
  document.getElementById("catalogFilter")?.classList.toggle("hidden", !state.can.view);

  const btnCreate = document.getElementById("btnCreate");
  if (btnCreate) {
    btnCreate.classList.toggle("hidden", !state.can.create);
    btnCreate.onclick = () => openEditor({ mode: "create" });
  }

  const chk = document.getElementById("showArchived");
  if (chk) {
    chk.checked = false;
    chk.onchange = async () => {
      state.includeArchived = !!chk.checked;
      await load();
    };
  }

  wireEditModalClose();

  await load();
})();
