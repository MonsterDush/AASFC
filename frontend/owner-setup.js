import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  api,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenueById,
} from "/app.js";

import {
  permSetFromResponse,
  roleUpper,
  isOwnerRole,
  isSysAdminRole,
  getBillingAccessMode,
  getSetupPhase,
  getSetupProgress,
  getSetupResumeStep,
  getSetupStatus,
  isSetupDone,
  isSetupPrepareDone,
} from "/permissions.js?v=20260409-setup2";

applyTelegramTheme();
mountCommonUI("venue");
await ensureLogin({ silent: true });
await mountNav({ activeTab: "venue" });

const root = document.getElementById("root");

const STEP_CONTENT = {
  welcome: {
    title: "Приветствие и название",
    subtitle: "Подтверди текущее название или переименуй заведение до старта настройки.",
    what: "Это базовая карточка заведения, с которой начинается дальнейшая настройка.",
    where: "Название показывается в навигации, в списке заведений и в командных сценариях.",
    later: "Можно оставить как есть и вернуться позже.",
    primaryLabel: "Переименовать",
    primaryAction: "rename",
    secondaryLabel: "Открыть карточку заведения",
    secondaryHref: (venueId) => `/app-venue.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  payment_methods: {
    title: "Способы оплат",
    subtitle: "Настрой, какие оплаты доступны в заведении и будут участвовать в закрытии смены.",
    what: "Это список способов оплаты: наличные, безналичные и любые твои дополнительные варианты.",
    where: "Используются в закрытии смены, выручке и месячной сводке.",
    later: "Лучше не откладывать, потому что это основа отчётов.",
    primaryLabel: "Открыть оплаты",
    primaryHref: (venueId) => `/owner-payment-methods.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  departments: {
    title: "Департаменты",
    subtitle: "Определи направления выручки внутри заведения.",
    what: "Обычно это кальяны, бар, кухня и другие внутренние направления дохода.",
    where: "Используются в закрытии смены, аналитике и процентах в зарплатах.",
    later: "Лучше заполнить на старте, чтобы сразу вести корректную детализацию.",
    primaryLabel: "Открыть департаменты",
    primaryHref: (venueId) => `/owner-departments.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  kpi: {
    title: "KPI и доп. продажи",
    subtitle: "Реши, нужны ли дополнительные показатели уже сейчас.",
    what: "Это счётчики и суммы, которые можно собирать при закрытии смены: допродажи, штуки, KPI.",
    where: "Используются в отчётах и KPI-бонусах в зарплатных профилях.",
    later: "Да, этот шаг можно спокойно отложить и вернуться позже.",
    primaryLabel: "Открыть KPI",
    primaryHref: (venueId) => `/owner-kpi.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  pay_profiles: {
    title: "Профили зарплат",
    subtitle: "Создай базовые профили начислений без привязки к конкретным сотрудникам.",
    what: "Профиль зарплаты — это набор правил, по которым потом считаются начисления.",
    where: "Используется в должностях, начислениях, ФОТ и сводке.",
    later: "Нежелательно откладывать, если хочешь быстро привязать должности к понятным правилам.",
    primaryLabel: "Открыть профили зарплаты",
    primaryHref: (venueId) => `/owner-pay-profiles.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  positions: {
    title: "Должности и права",
    subtitle: "Создай должности, привяжи к ним профиль зарплаты и стартовый набор прав.",
    what: "Это роли сотрудников внутри заведения: кто за что отвечает и что видит в приложении.",
    where: "Используется в приглашениях, графике, зарплатах и ограничении доступа.",
    later: "Лучше завершить до приглашения команды.",
    primaryLabel: "Открыть должности",
    primaryHref: (venueId) => `/positions.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  invites: {
    title: "Приглашение участников",
    subtitle: "Добавь команду и сразу назначь людям подходящие должности.",
    what: "Приглашения позволяют заранее подготовить состав команды ещё до принятия приглашения.",
    where: "Используется для запуска графика, отчётов и распределения ролей.",
    later: "Да, можно пригласить людей позже, если сначала настраиваешь всё один.",
    primaryLabel: "Открыть приглашения",
    primaryHref: (venueId) => `/invites.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  shift_intervals: {
    title: "Интервалы смен",
    subtitle: "Собери интервалы, из которых потом строится график и часть расчётов.",
    what: "Это типовые временные отрезки смен: утро, день, вечер и любые свои варианты.",
    where: "Используется в графике, закрытии смены и начислениях.",
    later: "Не стоит откладывать, если сразу планируешь работу команды.",
    primaryLabel: "Открыть интервалы",
    primaryHref: (venueId) => `/shift-intervals.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  expense_categories: {
    title: "Категории расходов",
    subtitle: "Разложи будущие траты по понятным категориям.",
    what: "Категории нужны для чистой структуры расходов и сводки по месяцам.",
    where: "Используется в расходах и месячной аналитике.",
    later: "Да, это уже дополнительная настройка.",
    primaryLabel: "Открыть категории расходов",
    primaryHref: (venueId) => `/owner-expense-categories.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  suppliers: {
    title: "Поставщики",
    subtitle: "Заведи контрагентов, чтобы расходные операции было удобнее оформлять.",
    what: "Это справочник поставщиков, который ускоряет занесение расходов.",
    where: "Используется в расходах и истории закупок.",
    later: "Да, можно добавить после базового запуска.",
    primaryLabel: "Открыть поставщиков",
    primaryHref: (venueId) => `/owner-suppliers.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  recurring_expenses: {
    title: "Регулярные настройки",
    subtitle: "Подготовь регулярные расходы и повторяющиеся финансовые правила.",
    what: "Это автоматизация однотипных ежемесячных расходов и повторяющихся финансовых записей.",
    where: "Используется для регулярных расходов и дальнейшей сводки.",
    later: "Да, это уже этап полировки после базового запуска.",
    primaryLabel: "Открыть регулярные расходы",
    primaryHref: (venueId) => `/owner-recurring-expenses.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
};

const STATUS_LABELS = {
  AVAILABLE: "Доступно",
  COMPLETED: "Готово",
  SKIPPED: "Позже",
  REQUIRES_ATTENTION: "Проверить",
  LOCKED: "Недоступно",
};

const state = {
  venueId: "",
  me: null,
  venue: null,
  perms: null,
  setup: null,
  selectedStepKey: "",
  selectedPhase: "PREPARE",
  loading: true,
  accessError: "",
};

function esc(value) {
  return String(value ?? "")
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

function getStepFromUrl() {
  const params = new URLSearchParams(location.search);
  return String(params.get("step") || "").trim();
}

function setStepInUrl(stepKey, phase) {
  const url = new URL(location.href);
  if (stepKey) url.searchParams.set("step", stepKey);
  else url.searchParams.delete("step");
  if (phase) url.searchParams.set("phase", String(phase).toLowerCase());
  else url.searchParams.delete("phase");
  history.replaceState({}, "", url.pathname + url.search + url.hash);
}

function toStepStatusClass(status) {
  switch (String(status || "").toUpperCase()) {
    case "COMPLETED": return "setup-status setup-status--completed";
    case "SKIPPED": return "setup-status setup-status--skipped";
    case "REQUIRES_ATTENTION": return "setup-status setup-status--attention";
    default: return "setup-status setup-status--available";
  }
}

function getVisibleSteps() {
  const phase = String(state.selectedPhase || getSetupPhase(state.setup) || "PREPARE").toUpperCase();
  return Array.isArray(state.setup?.steps) ? state.setup.steps.filter((step) => String(step.phase || "").toUpperCase() === phase) : [];
}

function getCurrentStep() {
  const steps = Array.isArray(state.setup?.steps) ? state.setup.steps : [];
  const fallbackKey = getStepFromUrl() || state.selectedStepKey || getSetupResumeStep(state.setup) || steps[0]?.key || "";
  const found = steps.find((step) => step.key === fallbackKey) || steps.find((step) => step.key === getSetupResumeStep(state.setup)) || steps[0] || null;
  return found;
}

function phaseTitle() {
  return String(state.selectedPhase || "PREPARE").toUpperCase() === "EXTRA" ? "Дополнительная настройка" : "Базовая настройка";
}

function renderAccessError(message) {
  root.innerHTML = `
    <div class="itemcard section-card">
      <b>Быстрая настройка недоступна</b>
      <div class="muted mt-8">${esc(message || "Открыть мастер настройки можно только владельцу заведения с полным доступом.")}</div>
      <div class="setup-actionbar">
        <a class="btn" href="/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId || ""))}">К заведению</a>
        <a class="btn subtle" href="/app-venues.html">К списку заведений</a>
      </div>
    </div>
  `;
}

function renderLoading() {
  root.innerHTML = `
    <div class="skeleton"></div>
    <div class="skeleton"></div>
    <div class="skeleton"></div>
  `;
}

function renderStartScreen() {
  const venueName = state.venue?.name || `Заведение #${state.venueId}`;
  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>Подготовим ${esc(venueName)}</b>
          <div class="muted">Мастер проведёт по базовой настройке, а потом предложит дополнительную доводку.</div>
        </div>
      </div>
      <div class="setup-summary">
        <div class="setup-kpi">
          <div class="setup-kpi__value">8 шагов</div>
          <div class="setup-kpi__hint">Базовый запуск: оплаты, департаменты, зарплаты, должности, команда и интервалы.</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">3 шага</div>
          <div class="setup-kpi__hint">Дополнительная настройка: расходы, поставщики и регулярные правила.</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">Гибко</div>
          <div class="setup-kpi__hint">Часть шагов можно отложить и вернуться к ним позже без потери прогресса.</div>
        </div>
      </div>
      <div class="setup-actionbar">
        <button class="btn primary" id="btnStartSetup" type="button">Начать настройку</button>
        <a class="btn subtle" href="/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId))}">Пока к заведению</a>
      </div>
      <div class="setup-inline-note">Базовая настройка нужна для корректной работы графика, закрытия смены, сводки и зарплатных сценариев.</div>
    </div>
  `;
  document.getElementById("btnStartSetup")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/start`, { method: "POST" });
      await loadSetup({ preserveSelection: false });
      toast("Настройка начата", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось начать настройку", "err");
    }
  });
}

function renderSetup() {
  const currentStep = getCurrentStep();
  if (!currentStep) {
    root.innerHTML = `<div class="setup-empty">Не удалось определить шаг настройки.</div>`;
    return;
  }
  state.selectedStepKey = currentStep.key;
  state.selectedPhase = String(currentStep.phase || state.selectedPhase || "PREPARE").toUpperCase();
  setStepInUrl(currentStep.key, state.selectedPhase);

  const meta = STEP_CONTENT[currentStep.key] || {
    title: currentStep.title,
    subtitle: "Этот шаг уже добавлен в мастер, но текст-помощник для него пока не заполнен.",
    what: "Настрой параметры шага на целевой странице.",
    where: "Используется внутри заведения и связанных модулей.",
    later: currentStep.skippable ? "Этот шаг можно отложить." : "Этот шаг лучше не откладывать.",
  };

  const progress = getSetupProgress(state.setup);
  const progressPercent = progress.total > 0 ? Math.round((progress.resolved / progress.total) * 100) : 0;
  const visibleSteps = getVisibleSteps();
  const setupStatus = getSetupStatus(state.setup);
  const prepareDone = isSetupPrepareDone(state.setup);
  const done = isSetupDone(state.setup);
  const canOpenExtra = prepareDone || state.selectedPhase === "EXTRA";
  const canCompleteStep = currentStep.key === "welcome" || currentStep.data_ready;

  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>${esc(state.venue?.name || `Заведение #${state.venueId}`)}</b>
          <div class="muted">${esc(phaseTitle())} · статус: ${esc(setupStatus)}</div>
        </div>
        <div class="setup-inline-list">
          <span class="setup-chip">Готово: ${progress.done} из ${progress.total}</span>
          <span class="setup-chip">Решено: ${progress.resolved} из ${progress.total}</span>
          <span class="setup-chip">Следующий шаг: ${esc(getSetupResumeStep(state.setup) || currentStep.key)}</span>
        </div>
      </div>
      <div class="setup-progressbar"><span style="width:${progressPercent}%"></span></div>
      <div class="setup-summary">
        <div class="setup-kpi">
          <div class="setup-kpi__value">${state.setup?.prepare_resolved || 0}/${state.setup?.prepare_total || 0}</div>
          <div class="setup-kpi__hint">Базовая настройка</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">${state.setup?.extra_resolved || 0}/${state.setup?.extra_total || 0}</div>
          <div class="setup-kpi__hint">Дополнительная настройка</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">${progressPercent}%</div>
          <div class="setup-kpi__hint">Общий прогресс мастера</div>
        </div>
      </div>
      <div class="setup-phase-switch">
        <button class="btn ${state.selectedPhase === "PREPARE" ? "primary" : "subtle"}" id="btnPhasePrepare" aria-current="${state.selectedPhase === "PREPARE" ? "true" : "false"}" type="button">Базовая настройка</button>
        <button class="btn ${state.selectedPhase === "EXTRA" ? "primary" : "subtle"}" id="btnPhaseExtra" aria-current="${state.selectedPhase === "EXTRA" ? "true" : "false"}" type="button" ${canOpenExtra ? "" : "disabled"}>Дополнительная настройка</button>
        <button class="btn subtle" id="btnRefreshSetup" type="button">Обновить прогресс</button>
        <a class="btn subtle" href="/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId))}">К заведению</a>
      </div>
    </div>

    <div class="setup-shell mt-12">
      <div class="itemcard section-card">
        <div class="section-card__head">
          <div class="section-card__title">
            <b>${esc(phaseTitle())}</b>
            <div class="muted">Шаги можно проходить по порядку или возвращаться к ним позже.</div>
          </div>
        </div>
        <div class="setup-steps mt-12" id="setupStepList">
          ${visibleSteps.map((step) => {
            const isActive = step.key === currentStep.key;
            const statusLabel = STATUS_LABELS[String(step.status || "AVAILABLE").toUpperCase()] || step.status;
            const countText = step.count_key ? `Объектов: ${Number(step.count || 0)}` : "Подтвердить решение";
            return `
              <button class="setup-step ${isActive ? "is-active" : ""}" type="button" data-step-key="${esc(step.key)}">
                <div class="setup-step__top">
                  <div>
                    <div class="setup-step__title">${esc(step.title)}</div>
                    <div class="setup-step__meta">${esc(countText)}</div>
                  </div>
                  <span class="${toStepStatusClass(step.status)}">${esc(statusLabel)}</span>
                </div>
              </button>
            `;
          }).join("")}
        </div>
      </div>

      <div class="itemcard section-card">
        <div class="setup-detail__head">
          <div>
            <b>${esc(meta.title || currentStep.title)}</b>
            <div class="muted mt-6">${esc(meta.subtitle || "")}</div>
          </div>
          <span class="${toStepStatusClass(currentStep.status)}">${esc(STATUS_LABELS[String(currentStep.status || "AVAILABLE").toUpperCase()] || currentStep.status)}</span>
        </div>

        <div class="setup-inline-list">
          <span class="setup-chip">Ключ шага: ${esc(currentStep.key)}</span>
          <span class="setup-chip">Объектов: ${Number(currentStep.count || 0)}</span>
          <span class="setup-chip">${currentStep.data_ready ? "Данные есть" : "Данные ещё не заполнены"}</span>
        </div>

        <div class="setup-detail__grid">
          <div class="setup-helper"><b>Что это</b>${esc(meta.what || "")}</div>
          <div class="setup-helper"><b>Где используется</b>${esc(meta.where || "")}</div>
          <div class="setup-helper"><b>Можно ли позже</b>${esc(meta.later || "")}</div>
        </div>

        <div class="setup-actionbar">
          ${meta.primaryAction === "rename" ? `<button class="btn primary" id="btnRenameVenue" type="button">${esc(meta.primaryLabel || "Переименовать")}</button>` : ""}
          ${typeof meta.primaryHref === "function" ? `<a class="btn primary" href="${esc(meta.primaryHref(state.venueId, state))}">${esc(meta.primaryLabel || "Открыть")}</a>` : ""}
          ${typeof meta.secondaryHref === "function" ? `<a class="btn subtle" href="${esc(meta.secondaryHref(state.venueId, state))}">${esc(meta.secondaryLabel || "Открыть")}</a>` : ""}
          <button class="btn" id="btnReloadCurrent" type="button">Проверить шаг</button>
          ${canCompleteStep && !currentStep.completed ? `<button class="btn" id="btnCompleteStep" type="button">Отметить завершённым</button>` : ""}
          ${currentStep.skippable && !currentStep.completed && !currentStep.skipped ? `<button class="btn subtle" id="btnSkipStep" type="button">Вернуться позже</button>` : ""}
          ${(currentStep.completed || currentStep.skipped || currentStep.requires_attention) ? `<button class="btn subtle" id="btnResetStep" type="button">Сбросить шаг</button>` : ""}
        </div>

        <div class="setup-inline-note">
          ${currentStep.requires_attention ? "Шаг был отмечен завершённым, но сейчас данные выглядят неполными. Проверь страницу настройки и обнови шаг." : (currentStep.completed ? "Шаг завершён и учитывается в общем прогрессе мастера." : (currentStep.skipped ? "Шаг отложен и не блокирует общий прогресс." : "После изменений на целевой странице вернись сюда и нажми «Проверить шаг» или «Отметить завершённым»."))}
        </div>

        <div class="setup-footer">
          <div class="setup-actionbar">
            <button class="btn subtle" id="btnPrevStep" type="button">← Назад</button>
            <button class="btn subtle" id="btnNextStep" type="button">Дальше →</button>
          </div>
          <div class="setup-actionbar">
            ${state.selectedPhase === "PREPARE" && prepareDone && !done ? `<button class="btn primary" id="btnFinishPrepare" type="button">Завершить базовую настройку</button>` : ""}
            ${state.selectedPhase === "EXTRA" && prepareDone && (state.setup?.extra_resolved === state.setup?.extra_total) && !done ? `<button class="btn primary" id="btnFinishExtra" type="button">Завершить весь мастер</button>` : ""}
          </div>
        </div>
      </div>
    </div>
  `;

  wireSetupActions(currentStep, visibleSteps);
}

function wireSetupActions(currentStep, visibleSteps) {
  document.getElementById("btnPhasePrepare")?.addEventListener("click", () => {
    state.selectedPhase = "PREPARE";
    const first = (state.setup?.steps || []).find((step) => String(step.phase || "").toUpperCase() === "PREPARE");
    if (first) state.selectedStepKey = first.key;
    renderSetup();
  });

  document.getElementById("btnPhaseExtra")?.addEventListener("click", () => {
    if (!isSetupPrepareDone(state.setup)) return;
    state.selectedPhase = "EXTRA";
    const first = (state.setup?.steps || []).find((step) => String(step.phase || "").toUpperCase() === "EXTRA");
    if (first) state.selectedStepKey = first.key;
    renderSetup();
  });

  document.getElementById("btnRefreshSetup")?.addEventListener("click", async () => {
    await loadSetup({ preserveSelection: true });
    toast("Прогресс обновлён", "ok");
  });

  document.querySelectorAll("[data-step-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedStepKey = String(btn.getAttribute("data-step-key") || "");
      renderSetup();
    });
  });

  document.getElementById("btnRenameVenue")?.addEventListener("click", async () => {
    const current = state.venue?.name || "";
    const name = window.prompt("Новое название заведения:", current);
    if (!name || !String(name).trim()) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}`, { method: "PATCH", body: { name: String(name).trim() } });
      state.venue = await getVenueById(state.venueId);
      toast("Название обновлено", "ok");
      await loadSetup({ preserveSelection: true });
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось переименовать заведение", "err");
    }
  });

  document.getElementById("btnReloadCurrent")?.addEventListener("click", async () => {
    await loadSetup({ preserveSelection: true });
  });

  document.getElementById("btnCompleteStep")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, {
        method: "POST",
        body: { step_key: currentStep.key },
      });
      await loadSetup({ preserveSelection: true });
      toast("Шаг отмечен завершённым", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
    }
  });

  document.getElementById("btnSkipStep")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "Вернуться позже?",
      text: "Этот шаг будет помечен как отложенный. Ты сможешь вернуться к нему в любой момент.",
      confirmText: "Отложить",
      danger: false,
    });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, {
        method: "POST",
        body: { step_key: currentStep.key },
      });
      await loadSetup({ preserveSelection: true });
      toast("Шаг отложен", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось отложить шаг", "err");
    }
  });

  document.getElementById("btnResetStep")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "Сбросить шаг?",
      text: "Шаг снова станет незавершённым. Данные в модуле не удаляются, меняется только состояние мастера.",
      confirmText: "Сбросить",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/reset-step`, {
        method: "POST",
        body: { step_key: currentStep.key },
      });
      await loadSetup({ preserveSelection: true });
      toast("Шаг сброшен", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось сбросить шаг", "err");
    }
  });

  document.getElementById("btnPrevStep")?.addEventListener("click", () => {
    const idx = visibleSteps.findIndex((step) => step.key === currentStep.key);
    if (idx > 0) {
      state.selectedStepKey = visibleSteps[idx - 1].key;
      renderSetup();
    }
  });

  document.getElementById("btnNextStep")?.addEventListener("click", () => {
    const idx = visibleSteps.findIndex((step) => step.key === currentStep.key);
    if (idx >= 0 && idx < visibleSteps.length - 1) {
      state.selectedStepKey = visibleSteps[idx + 1].key;
      renderSetup();
    }
  });

  document.getElementById("btnFinishPrepare")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/finish-prepare`, { method: "POST" });
      await loadSetup({ preserveSelection: false });
      state.selectedPhase = "EXTRA";
      toast("Базовая настройка завершена", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить базовую настройку", "err");
    }
  });

  document.getElementById("btnFinishExtra")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/finish-extra`, { method: "POST" });
      await loadSetup({ preserveSelection: false });
      toast("Мастер настройки завершён", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить мастер", "err");
    }
  });
}

async function loadSetup({ preserveSelection = true } = {}) {
  if (!state.venueId) {
    state.accessError = "Заведение не выбрано.";
    renderAccessError(state.accessError);
    return;
  }
  const prevStep = preserveSelection ? state.selectedStepKey : "";
  const prevPhase = preserveSelection ? state.selectedPhase : "";
  state.setup = await api(`/venues/${encodeURIComponent(state.venueId)}/setup`);
  state.selectedPhase = String(prevPhase || getSetupPhase(state.setup) || "PREPARE").toUpperCase();
  const urlStep = getStepFromUrl();
  state.selectedStepKey = urlStep || prevStep || getSetupResumeStep(state.setup) || state.setup?.steps?.[0]?.key || "";
  if (getSetupStatus(state.setup) === "NOT_STARTED") {
    renderStartScreen();
    return;
  }
  renderSetup();
}

async function bootstrap() {
  try {
    renderLoading();
    state.venueId = parseVenueId();
    state.me = await getMe();
    state.venue = state.venueId ? await getVenueById(state.venueId) : null;
    state.perms = state.venueId ? await getMyVenuePermissions(state.venueId) : null;

    const venueRole = roleUpper(state.perms) || roleUpper(state.venue) || "";
    const sysRole = String(state.me?.system_role || "").toUpperCase();
    const isOwner = isOwnerRole(venueRole);
    const isAdmin = isSysAdminRole(sysRole);
    const billingMode = getBillingAccessMode(state.perms || state.venue || {});

    if (!state.venueId) {
      renderAccessError("Сначала выбери заведение, а потом открой мастер настройки.");
      return;
    }
    if (!(isOwner || isAdmin)) {
      renderAccessError("Открыть мастер настройки может только владелец заведения или суперадмин.");
      return;
    }
    if (billingMode && String(billingMode).toUpperCase() !== "FULL") {
      renderAccessError("При ограниченном доступе по подписке мастер настройки недоступен. Сначала продли доступ к заведению.");
      return;
    }

    await loadSetup({ preserveSelection: false });
  } catch (e) {
    const detail = e?.data?.detail || e?.message || "Не удалось открыть мастер настройки";
    renderAccessError(detail);
  }
}

await bootstrap();
