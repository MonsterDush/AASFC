import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getVenueById,
  getVenueSettings,
  updateVenueSettings,
  setActiveVenueId,
} from "/app.js?v=20260726-navmore1";

applyTelegramTheme();
mountCommonUI("venue");
await ensureLogin({ silent: true });
await mountNav({ activeTab: "finance", requireVenue: true });

const params = new URLSearchParams(location.search);
const venueId = params.get("venue_id") || "";
if (venueId) setActiveVenueId(venueId);

const el = {
  title: document.getElementById("title"),
  venueTitle: document.getElementById("venueTitle"),
  pageHint: document.getElementById("pageHint"),
  back: document.getElementById("backToVenue"),
  list: document.getElementById("rulesList"),
  add: document.getElementById("addRuleBtn"),
  save: document.getElementById("saveBtn"),
  saveHint: document.getElementById("saveHint"),
  rulesNote: document.getElementById("rulesNote"),
};

const esc = (s) => String(s ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;")
  .replace(/'/g, "&#39;");

function normalizeTitle(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function loadErrorMessage(error) {
  const detail = String(error?.data?.detail || error?.message || "").trim();
  if (/forbidden/i.test(detail)) return "Нет доступа к настройкам этого заведения.";
  if (/not found/i.test(detail)) return "Заведение или его настройки не найдены.";
  return detail || "Повтори попытку позже: текущие настройки не были получены.";
}

function parseRows(weights) {
  const rows = Array.isArray(weights?.rows)
    ? weights.rows
    : Array.isArray(weights?.by_position)
      ? weights.by_position
      : Array.isArray(weights)
        ? weights
        : [];
  return rows
    .map((row) => ({
      title: String(row?.title || row?.position_title || row?.position || "").trim(),
      percent: Math.max(0, Math.min(100, Number(row?.percent || 0) || 0)),
    }))
    .filter((row) => row.title);
}

let availableTitles = [];
let rows = [];
let listError = "";

function renderRulesNote() {
  const configuredTotal = rows.reduce(
    (sum, row) => sum + Math.max(0, Math.min(100, Number(row?.percent || 0) || 0)),
    0,
  );
  if (!el.rulesNote) return;
  const warning = configuredTotal > 100
    ? ` В текущих правилах уже ${Math.round(configuredTotal)}% даже без учёта повторяющихся должностей — проверь состав смен перед закрытием отчёта.`
    : "";
  el.rulesNote.textContent = `Сумма процентов может быть меньше 100%: нераспределённый остаток делится поровну между остальными сотрудниками смены. Процент применяется к каждому назначенному сотруднику; если фактическая сумма долей смены превысит 100%, отчёт нельзя будет закрыть.${warning}`;
}

function buildTitleOptions(current = "") {
  const options = [...availableTitles];
  if (current && !options.some((x) => normalizeTitle(x) === normalizeTitle(current))) options.unshift(current);
  return options.map((title) => `<option value="${esc(title)}">${esc(title)}</option>`).join("");
}

function render() {
  if (!el.list) return;
  renderRulesNote();
  if (listError) {
    el.list.innerHTML = `<div class="tip-settings-state tip-settings-state--error"><b>Не удалось загрузить правила</b><span>${esc(listError)}</span></div>`;
    return;
  }
  if (!availableTitles.length && !rows.length) {
    el.list.innerHTML = `<div class="tip-settings-state"><b>Нет должностей для настройки</b><span>Сначала создай или назначь должности в заведении.</span></div>`;
    return;
  }
  if (!rows.length) {
    el.list.innerHTML = `<div class="tip-settings-state"><b>Правил пока нет</b><span>Сейчас чаевые будут делиться поровну, пока ты не добавишь хотя бы одно правило.</span></div>`;
    return;
  }
  el.list.innerHTML = rows.map((row, idx) => `
    <div class="itemcard tip-settings-row">
      <label class="tip-settings-row__field">
        <span>Должность</span>
        <select data-role-title="${idx}">${buildTitleOptions(row.title)}</select>
      </label>
      <label class="tip-settings-row__field">
        <span>% на человека</span>
        <input type="number" min="0" max="100" inputmode="numeric" data-role-percent="${idx}" value="${esc(row.percent)}" />
      </label>
      <button class="btn danger tip-settings-row__remove" data-role-remove="${idx}">Удалить</button>
    </div>
  `).join("");

  rows.forEach((row, idx) => {
    const titleEl = el.list.querySelector(`[data-role-title="${idx}"]`);
    const percentEl = el.list.querySelector(`[data-role-percent="${idx}"]`);
    const removeEl = el.list.querySelector(`[data-role-remove="${idx}"]`);
    if (titleEl) {
      titleEl.value = row.title;
      titleEl.addEventListener("change", () => {
        rows[idx].title = String(titleEl.value || "").trim();
      });
    }
    if (percentEl) {
      percentEl.addEventListener("input", () => {
        rows[idx].percent = Math.max(0, Math.min(100, Number(percentEl.value || 0) || 0));
        renderRulesNote();
      });
    }
    if (removeEl) {
      removeEl.addEventListener("click", () => {
        rows.splice(idx, 1);
        render();
      });
    }
  });
}

function nextAvailableTitle() {
  const used = new Set(rows.map((row) => normalizeTitle(row.title)));
  return availableTitles.find((title) => !used.has(normalizeTitle(title))) || availableTitles[0] || "";
}

function validateRows() {
  const seen = new Set();
  const clean = [];
  for (const row of rows) {
    const title = String(row?.title || "").trim();
    const percent = Math.max(0, Math.min(100, Math.round(Number(row?.percent || 0) || 0)));
    if (!title) return { ok: false, message: "Укажи должность в каждом правиле." };
    const norm = normalizeTitle(title);
    if (seen.has(norm)) return { ok: false, message: "Одна и та же должность не должна повторяться в нескольких правилах." };
    seen.add(norm);
    clean.push({ title, percent });
  }
  return { ok: true, rows: clean };
}

async function load() {
  if (!venueId) {
    listError = "Сначала выбери заведение.";
    el.add.disabled = true;
    el.save.disabled = true;
    render();
    toast("Сначала выбери заведение", "err");
    return;
  }
  if (el.back) el.back.href = `/app-venue.html?venue_id=${encodeURIComponent(venueId)}`;

  const [venueResult, settingsResult, positionsResult] = await Promise.allSettled([
    getVenueById(venueId),
    getVenueSettings(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/positions`),
  ]);
  const venue = venueResult.status === "fulfilled" ? venueResult.value : null;
  const settings = settingsResult.status === "fulfilled" ? settingsResult.value : null;
  const positions = positionsResult.status === "fulfilled" ? positionsResult.value : [];

  const venueName = venue?.name || `Заведение ${venueId}`;
  if (el.title) el.title.textContent = `Чаевые · ${venueName}`;
  if (el.venueTitle) el.venueTitle.textContent = venueName;

  if (settingsResult.status === "rejected") {
    listError = loadErrorMessage(settingsResult.reason);
    el.add.disabled = true;
    el.save.disabled = true;
    render();
    return;
  }

  const titles = Array.isArray(positions)
    ? positions.map((item) => String(item?.title || "").trim()).filter(Boolean)
    : [];
  const dedup = new Map();
  for (const title of titles) {
    const norm = normalizeTitle(title);
    if (!norm || dedup.has(norm)) continue;
    dedup.set(norm, title);
  }
  availableTitles = Array.from(dedup.values()).sort((a, b) => a.localeCompare(b, "ru"));
  rows = parseRows(settings?.tips_weights);
  listError = "";
  el.add.disabled = !availableTitles.length;
  el.save.disabled = false;
  render();

  if (positionsResult.status === "rejected" && el.saveHint) {
    el.saveHint.textContent = "Список должностей не обновился; доступны только ранее сохранённые правила.";
  }

  const mode = String(settings?.tips_split_mode || "EQUAL").toUpperCase();
  if (mode !== "WEIGHTED_BY_POSITION" && el.pageHint) {
    el.pageHint.textContent = "Сейчас в заведении активен режим “Поровну”. Сохранение на этой странице автоматически переключит режим на “По должностям”.";
  }
}

el.add?.addEventListener("click", () => {
  rows.push({ title: nextAvailableTitle(), percent: 0 });
  render();
});

el.save?.addEventListener("click", async () => {
  const valid = validateRows();
  if (!valid.ok) {
    toast(valid.message, "err");
    return;
  }
  try {
    await updateVenueSettings(venueId, {
      tips_split_mode: "WEIGHTED_BY_POSITION",
      tips_weights: { rows: valid.rows },
    });
    if (el.saveHint) {
      el.saveHint.textContent = "Сохранено";
      clearTimeout(el.saveHint._t);
      el.saveHint._t = setTimeout(() => { el.saveHint.textContent = ""; }, 2200);
    }
    toast("Настройки распределения сохранены", "ok");
    rows = valid.rows;
    render();
  } catch (e) {
    toast(e?.data?.detail || e?.message || "Не удалось сохранить", "err");
  }
});

await load();
