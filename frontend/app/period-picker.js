const COPY = {
  ru: {
    custom: "Указать период",
    today: "Сегодня",
    yesterday: "Вчера",
    previous_week: "Прошлая неделя",
    previous_month: "Прошлый месяц",
    this_week: "Эта неделя",
    this_month: "Этот месяц",
    last_7: "Последние 7 дней",
    last_30: "Последние 30 дней",
    last_90: "Последние 90 дней",
    last_365: "Последние 365 дней",
    from: "Начало периода",
    to: "Конец периода",
    apply: "Показать",
  },
  en: {
    custom: "Custom period",
    today: "Today",
    yesterday: "Yesterday",
    previous_week: "Previous week",
    previous_month: "Previous month",
    this_week: "This week",
    this_month: "This month",
    last_7: "Last 7 days",
    last_30: "Last 30 days",
    last_90: "Last 90 days",
    last_365: "Last 365 days",
    from: "Period start",
    to: "Period end",
    apply: "Apply",
  },
};

const PRESET_GROUPS = [
  ["custom", "today", "yesterday", "previous_week", "previous_month"],
  ["this_week", "this_month", "last_7", "last_30", "last_90", "last_365"],
];

let activeTrigger = null;

function cloneDate(value) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate(), 12);
}

function addDays(value, amount) {
  const result = cloneDate(value);
  result.setDate(result.getDate() + amount);
  return result;
}

function isoDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function monthValue(value) {
  return isoDate(value).slice(0, 7);
}

function startOfWeek(value) {
  const dayIndex = (value.getDay() + 6) % 7;
  return addDays(value, -dayIndex);
}

function monthRange(value) {
  const from = new Date(value.getFullYear(), value.getMonth(), 1, 12);
  const to = new Date(value.getFullYear(), value.getMonth() + 1, 0, 12);
  return { from: isoDate(from), to: isoDate(to), month: monthValue(from) };
}

export function resolvePeriodPreset(key, now = new Date()) {
  const today = cloneDate(now);
  const singleDay = (date, preset) => ({ preset, mode: "day", day: isoDate(date), from: isoDate(date), to: isoDate(date) });
  if (key === "today") return singleDay(today, key);
  if (key === "yesterday") return singleDay(addDays(today, -1), key);
  if (key === "this_week") {
    const from = startOfWeek(today);
    return { preset: key, mode: "range", from: isoDate(from), to: isoDate(addDays(from, 6)) };
  }
  if (key === "previous_week") {
    const from = addDays(startOfWeek(today), -7);
    return { preset: key, mode: "range", from: isoDate(from), to: isoDate(addDays(from, 6)) };
  }
  if (key === "this_month") return { preset: key, mode: "month", ...monthRange(today) };
  if (key === "previous_month") {
    const previous = new Date(today.getFullYear(), today.getMonth() - 1, 1, 12);
    return { preset: key, mode: "month", ...monthRange(previous) };
  }
  const rollingDays = Number(String(key || "").match(/^last_(7|30|90|365)$/)?.[1] || 0);
  if (rollingDays) {
    return {
      preset: key,
      mode: "range",
      from: isoDate(addDays(today, -(rollingDays - 1))),
      to: isoDate(today),
    };
  }
  return null;
}

export function periodPresetLabel(key, language = "ru") {
  const locale = language === "en" ? "en" : "ru";
  return COPY[locale][key] || COPY[locale].custom;
}

function closeMenu() {
  document.querySelector("[data-period-menu-popover]")?.remove();
  activeTrigger?.setAttribute("aria-expanded", "false");
  activeTrigger = null;
}

function dispatchSelection(trigger, detail) {
  const language = document.documentElement.lang === "en" ? "en" : "ru";
  const label = detail.label || periodPresetLabel(detail.preset, language);
  trigger.dataset.periodValue = detail.preset || "custom";
  const labelNode = trigger.querySelector("[data-period-label]");
  if (labelNode) labelNode.textContent = label;
  trigger.dispatchEvent(new CustomEvent("axelio:period-change", {
    bubbles: true,
    detail: { ...detail, label },
  }));
  closeMenu();
}

export function stepPeriodMonth(trigger, amount) {
  if (!trigger || !Number.isFinite(Number(amount))) return null;
  const language = document.documentElement.lang === "en" ? "en" : "ru";
  const source = String(trigger.dataset.periodFrom || "").slice(0, 7);
  const base = /^\d{4}-\d{2}$/.test(source)
    ? new Date(`${source}-01T12:00:00`)
    : new Date();
  base.setMonth(base.getMonth() + Number(amount));
  const range = monthRange(base);
  const label = base.toLocaleDateString(language === "en" ? "en-US" : "ru-RU", {
    month: "long",
    year: "numeric",
  });
  const detail = { preset: "custom", mode: "month", ...range, label };
  dispatchSelection(trigger, detail);
  return detail;
}

function ensurePeriodStepper(trigger) {
  if (!trigger || trigger.dataset.periodStepper !== "month" || trigger.closest(".period-stepper")) return;
  const language = document.documentElement.lang === "en" ? "en" : "ru";
  const wrapper = document.createElement("div");
  wrapper.className = "period-stepper";
  const makeButton = (amount, label, glyph) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "period-stepper__button";
    button.dataset.periodStep = String(amount);
    button.setAttribute("aria-label", label);
    button.textContent = glyph;
    return button;
  };
  const previous = makeButton(-1, language === "en" ? "Previous month" : "Предыдущий месяц", "‹");
  const next = makeButton(1, language === "en" ? "Next month" : "Следующий месяц", "›");
  trigger.parentElement?.insertBefore(wrapper, trigger);
  wrapper.append(previous, trigger, next);
}

function positionMenu(menu, trigger) {
  const rect = trigger.getBoundingClientRect();
  const gutter = 10;
  const maxLeft = Math.max(gutter, window.innerWidth - menu.offsetWidth - gutter);
  const left = Math.min(Math.max(gutter, rect.right - menu.offsetWidth), maxLeft);
  const spaceBelow = window.innerHeight - rect.bottom - gutter;
  const top = spaceBelow >= Math.min(menu.offsetHeight, 520)
    ? rect.bottom + 8
    : Math.max(gutter, rect.top - Math.min(menu.offsetHeight, 520) - 8);
  menu.style.setProperty("--period-menu-left", `${Math.round(left)}px`);
  menu.style.setProperty("--period-menu-top", `${Math.round(top)}px`);
  menu.style.setProperty("--period-menu-max-height", `${Math.max(260, window.innerHeight - top - gutter)}px`);
}

function openMenu(trigger) {
  closeMenu();
  activeTrigger = trigger;
  trigger.setAttribute("aria-expanded", "true");
  const language = document.documentElement.lang === "en" ? "en" : "ru";
  const copy = COPY[language];
  const selected = trigger.dataset.periodValue || "this_month";
  const customMode = trigger.dataset.periodCustomMode === "month" ? "month" : "range";
  const allowed = new Set(
    String(trigger.dataset.periodPresets || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  const isAllowed = (key) => !allowed.size || allowed.has(key);
  const menu = document.createElement("div");
  menu.className = "period-menu";
  menu.setAttribute("data-period-menu-popover", "");
  menu.setAttribute("role", "menu");

  PRESET_GROUPS.forEach((group, groupIndex) => {
    const section = document.createElement("div");
    section.className = "period-menu__section";
    group.filter(isAllowed).forEach((key) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "period-menu__option";
      button.dataset.periodPreset = key;
      button.setAttribute("role", "menuitemradio");
      button.setAttribute("aria-checked", String(selected === key));
      button.innerHTML = `<span>${copy[key]}</span><span class="period-menu__check" aria-hidden="true">${selected === key ? "✓" : ""}</span>`;
      section.appendChild(button);
    });
    if (section.childElementCount) menu.appendChild(section);
    if (groupIndex === 0 && section.childElementCount && PRESET_GROUPS[1].some(isAllowed)) {
      const divider = document.createElement("div");
      divider.className = "period-menu__divider";
      menu.appendChild(divider);
    }
  });

  const custom = document.createElement("div");
  custom.className = "period-menu__custom";
  custom.hidden = true;
  custom.innerHTML = customMode === "month"
    ? `<input type="month" data-period-month aria-label="${copy.custom}" /><button type="button" class="btn primary" data-period-apply>${copy.apply}</button>`
    : `<input type="date" data-period-from aria-label="${copy.from}" /><input type="date" data-period-to aria-label="${copy.to}" /><button type="button" class="btn primary" data-period-apply>${copy.apply}</button>`;
  menu.appendChild(custom);
  document.body.appendChild(menu);
  positionMenu(menu, trigger);

  menu.addEventListener("click", (event) => {
    const option = event.target.closest("[data-period-preset]");
    if (option) {
      const key = option.dataset.periodPreset;
      if (key === "custom") {
        custom.hidden = false;
        if (customMode === "month") {
          const monthInput = custom.querySelector("[data-period-month]");
          monthInput.value = String(trigger.dataset.periodFrom || isoDate(new Date())).slice(0, 7);
          monthInput.focus();
        } else {
          custom.querySelector("[data-period-from]").value = trigger.dataset.periodFrom || isoDate(new Date());
          custom.querySelector("[data-period-to]").value = trigger.dataset.periodTo || isoDate(new Date());
          custom.querySelector("[data-period-from]").focus();
        }
        positionMenu(menu, trigger);
        return;
      }
      const detail = resolvePeriodPreset(key);
      if (detail) dispatchSelection(trigger, detail);
      return;
    }
    if (event.target.closest("[data-period-apply]")) {
      if (customMode === "month") {
        const month = custom.querySelector("[data-period-month]").value;
        if (!/^\d{4}-\d{2}$/.test(month)) return;
        const range = monthRange(new Date(`${month}-01T12:00:00`));
        const label = new Date(`${month}-01T12:00:00`).toLocaleDateString(language === "en" ? "en-US" : "ru-RU", { month: "long", year: "numeric" });
        dispatchSelection(trigger, { preset: "custom", mode: "month", ...range, label });
        return;
      }
      const from = custom.querySelector("[data-period-from]").value;
      const to = custom.querySelector("[data-period-to]").value;
      if (!from || !to) return;
      const normalized = from <= to ? { from, to } : { from: to, to: from };
      dispatchSelection(trigger, { preset: "custom", mode: "range", ...normalized, label: `${normalized.from} — ${normalized.to}` });
    }
  });
}

export function installPeriodPickers() {
  if (typeof document === "undefined" || document.documentElement.dataset.periodPickerReady === "1") return;
  document.documentElement.dataset.periodPickerReady = "1";
  document.querySelectorAll('[data-period-picker][data-period-stepper="month"]').forEach(ensurePeriodStepper);
  document.addEventListener("click", (event) => {
    const stepButton = event.target.closest?.("[data-period-step]");
    if (stepButton) {
      event.preventDefault();
      event.stopPropagation();
      const stepper = stepButton.closest(".period-stepper");
      const periodTrigger = stepper?.querySelector("[data-period-picker]");
      stepPeriodMonth(periodTrigger, Number(stepButton.dataset.periodStep));
      return;
    }
    const trigger = event.target.closest?.("[data-period-picker]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      if (trigger === activeTrigger) closeMenu();
      else openMenu(trigger);
      return;
    }
    if (!event.target.closest?.("[data-period-menu-popover]")) closeMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
  window.addEventListener("resize", closeMenu);
  window.addEventListener("scroll", closeMenu, true);
}

if (typeof document !== "undefined") installPeriodPickers();
