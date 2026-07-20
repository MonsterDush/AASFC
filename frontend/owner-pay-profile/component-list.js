
export function createPayComponentList({
  state,
  esc,
  support,
  openComponentEditor,
  updatePayComponent,
  deletePayComponent,
  toast,
  confirmModal,
  load,
}) {
const {
  COMPONENT_LABELS,
  fmtMoneyMinor,
  formatPercentConfig,
  departmentTitleFor,
  kpiMetricTitleFor,
} = support;

function componentStepsPreview(item) {
  const steps = Array.isArray(item?.steps) ? item.steps : [];
  if (!steps.length) return "";
  return `<div class="kpi-step-chips">${steps.map((step) => `<span class="kpi-step-chip">от ${esc(step.threshold_value)} → ${esc(fmtMoneyMinor(step.amount_minor || 0))}${step?.title ? ` · ${esc(step.title)}` : ""}</span>`).join("")}</div>`;
}

function componentSubtitle(item) {
  const type = String(item?.component_type || "").toUpperCase();
  if (type === "SALARY_FIXED_MONTH") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)}`;
  if (type === "SALARY_HOURLY") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.rate_minor)} / час`;
  if (type === "SALARY_PER_SHIFT") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)} / смена`;
  if (type === "MINIMUM_PAYOUT") return `${COMPONENT_LABELS[type]} · до ${fmtMoneyMinor(item.amount_minor)} / месяц`;
  if (type === "PERCENT_TOTAL_REVENUE") return `${COMPONENT_LABELS[type]} · ${formatPercentConfig(item)}`;
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const depTitle = departmentTitleFor(item);
    return `${COMPONENT_LABELS[type]} · ${formatPercentConfig(item)}${depTitle ? ` · ${depTitle}` : ""}`;
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
        <div class="row gap-8">
          <b>${esc(it.title)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивен</span>`}
        </div>
        <div class="muted mt-6">${esc(COMPONENT_LABELS[String(it.component_type || "").toUpperCase()] || it.component_type || "Компонент")}</div>
        <div class="muted listrow__meta">${esc(componentSubtitle(it))}</div>
        ${String(it?.component_type || "").toUpperCase() === "KPI_BONUS" ? componentStepsPreview(it) : ""}
      </div>
      <div class="row row--nowrap gap-8 flex-none" id="componentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#componentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Изменить";
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

return { renderComponents };
}
