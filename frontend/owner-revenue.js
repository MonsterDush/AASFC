import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
} from "/app.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function numOr0(v) {
  const n = typeof v === "number" ? v : Number(String(v ?? "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

function fmtMoney(n) {
  const x = Math.round(numOr0(n));
  try {
    return new Intl.NumberFormat("ru-RU").format(x) + " ₽";
  } catch {
    return String(x) + " ₽";
  }
}

function todayMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || getActiveVenueId() || "";
  if (id) setActiveVenueId(id);
  return id;
}

function downloadBlob(filename, blob) {
  const a = document.createElement("a");
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

async function poolMap(items, limit, fn) {
  const res = new Array(items.length);
  let i = 0;
  const workers = Array.from({ length: Math.max(1, limit) }, async () => {
    while (true) {
      const idx = i++;
      if (idx >= items.length) break;
      try {
        res[idx] = await fn(items[idx], idx);
      } catch (e) {
        res[idx] = { __error: e, __input: items[idx] };
      }
    }
  });
  await Promise.all(workers);
  return res;
}

const state = {
  venueId: "",
  venueName: "",
  month: todayMonth(),
  mode: "DEPARTMENTS", // or PAYMENTS
  loading: false,
  closedCount: 0,
  total: 0,
  rows: [], // { title, amount }
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Доходы</b>
          <div class="muted" id="subtitle">${esc(state.venueName || "по закрытым отчётам")}</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="muted">
        Доходы считаются только по отчётам со статусом <b>CLOSED</b>.
      </div>

      <div class="itemcard" style="margin-top:12px">
        <div class="section-head">
          <div class="section-title">
            <b>Период</b>
            <div class="muted">месяц + режим агрегации</div>
          </div>
          <div class="section-actions">
            <button class="btn" id="btnReload">Обновить</button>
          </div>
        </div>

        <div class="row mt-10" style="gap:10px; flex-wrap:wrap; justify-content:space-between">
          <input id="monthInput" type="month" class="input minw-240" value="${esc(state.month)}" />
          <div class="seg-toggle" id="modeToggle">
            <button data-mode="DEPARTMENTS" class="${state.mode === "DEPARTMENTS" ? "active" : ""}">Департаменты</button>
            <button data-mode="PAYMENTS" class="${state.mode === "PAYMENTS" ? "active" : ""}">Оплаты</button>
          </div>
        </div>

        <div class="row mt-10" style="gap:10px; flex-wrap:wrap; justify-content:space-between; align-items:center">
          <div class="muted" id="metaLine">…</div>
          <div class="row" style="gap:10px">
            <button class="btn" id="btnExport">Экспорт в Excel</button>
          </div>
        </div>
        <div class="muted mt-6">Экспортирует текущие фильтры (месяц и режим). Формат: CSV (Excel открывает).</div>

        <div class="divider" style="margin-top:12px"></div>

        <div id="list" style="margin-top:12px">
          <div class="skeleton"></div>
          <div class="skeleton"></div>
        </div>

        <div class="divider" style="margin-top:12px"></div>
        <div class="row row--nowrap" style="justify-content:space-between; margin-top:12px">
          <b>Итого</b>
          <b id="total">—</b>
        </div>
      </div>

      <div class="row" style="margin-top:12px">
        <a class="link" id="back" href="#">← Назад к заведению</a>
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

    <div class="nav">
      <div class="wrap"><div id="nav"></div></div>
    </div>
  `;

  mountCommonUI("revenue");

  const back = document.getElementById("back");
  if (back) {
    back.onclick = (e) => {
      e.preventDefault();
      const qp = state.venueId ? `?venue_id=${encodeURIComponent(state.venueId)}` : "";
      location.href = `/app-venue.html${qp}`;
    };
  }

  const btnReload = document.getElementById("btnReload");
  if (btnReload) btnReload.onclick = () => loadAndRender();

  const mi = document.getElementById("monthInput");
  if (mi) {
    mi.addEventListener("change", () => {
      state.month = mi.value || todayMonth();
      loadAndRender();
    });
  }

  document.querySelectorAll("#modeToggle button[data-mode]").forEach((b) => {
    b.addEventListener("click", () => {
      const m = b.getAttribute("data-mode");
      if (!m || m === state.mode) return;
      state.mode = m;
      document.querySelectorAll("#modeToggle button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      loadAndRender();
    });
  });

  const be = document.getElementById("btnExport");
  if (be) be.onclick = () => exportCsv();
}

function renderList() {
  const el = document.getElementById("list");
  const totalEl = document.getElementById("total");
  const meta = document.getElementById("metaLine");

  if (!el || !totalEl || !meta) return;

  meta.textContent = state.loading
    ? "Загрузка…"
    : `Закрытых отчётов: ${state.closedCount} · режим: ${state.mode === "PAYMENTS" ? "оплаты" : "департаменты"}`;

  if (state.loading) {
    el.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
    totalEl.textContent = "—";
    return;
  }

  totalEl.textContent = state.closedCount ? fmtMoney(state.total) : "—";

  if (!state.closedCount) {
    el.innerHTML = `<div class="muted">За выбранный месяц нет закрытых отчётов</div>`;
    return;
  }

  if (!state.rows.length) {
    el.innerHTML = `<div class="muted">Нет данных для агрегации (проверь, что цифры доступны в отчётах)</div>`;
    return;
  }

  el.innerHTML = "";
  for (const r of state.rows) {
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left"><b>${esc(r.title)}</b></div>
      <div style="flex:0 0 auto; font-weight:900">${esc(fmtMoney(r.amount))}</div>
    `;
    el.appendChild(row);
  }
}

async function loadVenueName() {
  if (!state.venueId) return;
  try {
    const venues = await getMyVenues();
    const v = (venues || []).find((x) => String(x.id) === String(state.venueId));
    state.venueName = v?.name || "";
    const sub = document.getElementById("subtitle");
    if (sub) sub.textContent = state.venueName || "по закрытым отчётам";
  } catch {}
}

function aggKeyFromItem(it) {
  const title = String(it?.title || "").trim();
  if (title) return title;
  const code = String(it?.code || "").trim();
  if (code) return code;
  const id = Number(it?.id);
  if (Number.isFinite(id) && id > 0) return `#${id}`;
  return "—";
}

function getValueFromItem(it) {
  if (it && typeof it.value === "number") return it.value;
  if (it && it.value != null) return numOr0(it.value);
  if (it && typeof it.value_numeric === "number") return it.value_numeric;
  return numOr0(it?.value_numeric);
}

async function fetchMonthList() {
  return await api(`/venues/${encodeURIComponent(state.venueId)}/reports?month=${encodeURIComponent(state.month)}`);
}

async function fetchReport(dayISO) {
  return await api(`/venues/${encodeURIComponent(state.venueId)}/reports/${encodeURIComponent(dayISO)}`);
}

async function loadAndRender() {
  if (!state.venueId) return;

  state.loading = true;
  state.closedCount = 0;
  state.total = 0;
  state.rows = [];
  renderList();

  await loadVenueName();

  let list = [];
  try {
    list = await fetchMonthList();
  } catch (e) {
    state.loading = false;
    renderList();
    toast("Не удалось загрузить список отчётов: " + (e?.data?.detail || e?.message || "ошибка"), "err");
    return;
  }

  const closedDates = (Array.isArray(list) ? list : [])
    .filter((r) => String(r?.status || "").toUpperCase() === "CLOSED" && r?.date)
    .map((r) => r.date);

  state.closedCount = closedDates.length;

  if (!closedDates.length) {
    state.loading = false;
    renderList();
    return;
  }

  const reps = await poolMap(closedDates, 6, async (d) => await fetchReport(d));

  const hasAnyNumbers =
    reps.some((r) => Array.isArray(r?.payments) ? r.payments.some((x) => getValueFromItem(x) !== 0) : false) ||
    reps.some((r) => Array.isArray(r?.departments) ? r.departments.some((x) => getValueFromItem(x) !== 0) : false) ||
    reps.some((r) => numOr0(r?.revenue_total) !== 0 || numOr0(r?.cash) !== 0 || numOr0(r?.cashless) !== 0);

  const m = new Map();
  let total = 0;

  for (const rep of reps) {
    if (!rep || rep.__error) continue;

    const arr = state.mode === "PAYMENTS" ? rep.payments : rep.departments;
    if (Array.isArray(arr) && arr.length) {
      for (const it of arr) {
        const k = aggKeyFromItem(it);
        const v = Math.max(0, getValueFromItem(it));
        if (!v) continue;
        m.set(k, (m.get(k) || 0) + v);
        total += v;
      }
      continue;
    }

    // Fallback: legacy fields
    if (state.mode === "PAYMENTS") {
      const cash = Math.max(0, numOr0(rep.cash));
      const cashless = Math.max(0, numOr0(rep.cashless));
      if (cash) m.set("Наличные", (m.get("Наличные") || 0) + cash);
      if (cashless) m.set("Безналичные", (m.get("Безналичные") || 0) + cashless);
      total += cash + cashless;
    } else {
      const rev = Math.max(0, numOr0(rep.revenue_total));
      if (rev) {
        m.set("Общая выручка", (m.get("Общая выручка") || 0) + rev);
        total += rev;
      }
    }
  }

  state.rows = Array.from(m.entries())
    .map(([title, amount]) => ({ title, amount }))
    .sort((a, b) => (b.amount || 0) - (a.amount || 0));

  state.total = total;
  state.loading = false;
  renderList();

  if (!hasAnyNumbers) toast("Похоже, нет доступа к цифрам (в отчётах суммы скрыты)", "err");
}

function exportCsv() {
  if (!state.closedCount) {
    toast("Нет данных для экспорта", "err");
    return;
  }
  const modeLabel = state.mode === "PAYMENTS" ? "payments" : "departments";
  const filename = `revenue_${state.venueId || "venue"}_${state.month}_${modeLabel}.csv`;

  const lines = [];
  lines.push(["Категория", "Сумма"]);
  for (const r of state.rows) lines.push([r.title, Math.round(numOr0(r.amount))]);
  lines.push(["ИТОГО", Math.round(numOr0(state.total))]);

  const csv = "\ufeff" + lines
    .map((row) => row.map((x) => `"${String(x ?? "").replace(/"/g, '""')}"`).join(";"))
    .join("\n");

  downloadBlob(filename, new Blob([csv], { type: "text/csv;charset=utf-8" }));
}

(async () => {
  applyTelegramTheme();

  state.venueId = parseVenueId();
  renderShell();

  await ensureLogin({ silent: true });

  if (!state.venueId) {
    root.innerHTML = `
      <div class="card">
        <b>Не выбрано заведение</b>
        <div class="muted mt-6">Откройте страницу с параметром venue_id или выберите активное заведение в настройках.</div>
        <div class="row mt-10"><a class="btn" href="/app-venues.html">К выбору заведений</a></div>
      </div>
    `;
    return;
  }

  await mountNav({ activeTab: "revenue", requireVenue: true });

  await loadAndRender();
})();
