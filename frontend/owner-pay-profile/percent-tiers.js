const $ = (id) => document.getElementById(id);
const t = (text) => window.AxelioI18n?.t?.(text) || text;
const number = (value) => Number(String(value ?? "").trim().replace(",", "."));
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function readPercentTiers({ validate = false } = {}) {
  const tiers = Array.from(document.querySelectorAll("[data-percent-tier]")).map((row) => {
    const threshold = row.querySelector("[data-tier-threshold]").value.trim();
    const rate = row.querySelector("[data-tier-percent]").value.trim();
    if (!threshold || !rate || !/^\d+(?:[.,]\d{1,4})?$/.test(threshold) || !/^\d+(?:[.,]\d{1,2})?$/.test(rate)) {
      if (validate) throw new Error(t("Заполните порог и процент каждой ступени"));
    }
    return { threshold_value: number(threshold), percent_bps: Math.round(number(rate) * 100) };
  }).sort((a, b) => a.threshold_value - b.threshold_value);
  if (validate) {
    let previous = Math.round(number($("f_percent")?.value) * 100);
    const seen = new Set();
    for (const tier of tiers) {
      if (!Number.isFinite(tier.threshold_value) || tier.threshold_value < 0 || !Number.isFinite(tier.percent_bps) || tier.percent_bps < previous || seen.has(tier.threshold_value)) {
        throw new Error(t("Пороги должны быть уникальными; процент не должен снижаться"));
      }
      seen.add(tier.threshold_value); previous = tier.percent_bps;
    }
    if (!tiers.length) throw new Error(t("Добавьте хотя бы одну ступень или выключите пороги"));
  }
  return tiers;
}

function rowMarkup(tier) {
  return `<div class="percent-tier-row" data-percent-tier><label><span data-tier-unit>${t("Выполнение плана, %")}</span><input data-tier-threshold inputmode="decimal" value="${esc(tier.threshold_value)}" /></label><label>${t("Процент, %")}<input data-tier-percent inputmode="decimal" value="${esc(tier.percent_bps / 100)}" /></label><button type="button" class="btn ghost" data-tier-remove aria-label="${t("Удалить ступень")}">×</button></div>`;
}

export function mountPercentTiers(item, onChange) {
  const container = $("f_tier_rows");
  if (!container) return;
  const tiers = item?.percent_tiers?.length ? item.percent_tiers : item?.boost_enabled && item.boost_percent_bps != null
    ? [{threshold_value: item.boost_source_type === "KPI_METRIC" ? item.boost_threshold_value : 100, percent_bps: item.boost_percent_bps}]
    : [100,110,120].map((threshold_value, index) => ({threshold_value, percent_bps: Number(item?.percent_bps || 300) + (index + 1) * 100}));
  container.innerHTML = tiers.map(rowMarkup).join("");
  container.oninput = onChange;
  container.onclick = (event) => { if (event.target.closest("[data-tier-remove]")) { event.target.closest("[data-percent-tier]").remove(); onChange(); } };
  $("f_add_tier").onclick = () => {
    const rows = readPercentTiers();
    if (rows.length >= 10) return;
    const last = rows.at(-1);
    container.insertAdjacentHTML("beforeend", rowMarkup({threshold_value: last ? last.threshold_value + 10 : 100, percent_bps: last ? last.percent_bps + 100 : 400}));
    onChange(); container.lastElementChild.querySelector("input").focus();
  };
}

export function syncTierPreview() {
  const enabled = $("f_boost_enabled")?.checked;
  const kpi = $("f_boost_source_type")?.value === "KPI_METRIC";
  $("f_tiers")?.classList.toggle("hidden", !enabled);
  document.querySelectorAll("[data-tier-unit]").forEach((el) => { el.textContent = t(kpi ? "Значение KPI" : "Выполнение плана, %"); });
  if (!$("f_tier_preview")) return;
  const tiers = readPercentTiers();
  $("f_add_tier").disabled = tiers.length >= 10;
  const base = number($("f_percent")?.value);
  $("f_tier_preview").textContent = `${t("Базовый процент:")} ${base}%. ` + tiers.map((row) => `≥ ${row.threshold_value}${kpi ? "" : "%"} → ${row.percent_bps / 100}%`).join(" · ");
}

export function validateTierCompatibility(selectedIds) {
  if ($("f_boost_recalc_mode")?.value !== "EXCESS_ONLY") return;
  const source = $("f_boost_source_type")?.value || "NONE";
  const type = $("f_component_type")?.value;
  const scope = $("f_base_scope")?.value;
  const departments = selectedIds("f_department_id").sort().join(",");
  const boostDepartments = selectedIds("f_boost_department_id").sort().join(",");
  if (source === "KPI_METRIC" || (source.endsWith("MONTH_PLAN") && scope !== "FULL_PERIOD") ||
      (source.startsWith("VENUE_") && type !== "PERCENT_TOTAL_REVENUE") ||
      (source.startsWith("DEPARTMENT_") && (type !== "PERCENT_DEPARTMENT_REVENUE" || !departments || departments !== boostDepartments))) {
    throw new Error(t("Для процента только на превышение база начисления должна совпадать с базой плана"));
  }
}

export function renderTierSimulation({ fmtMoneyMinor, selectedIdsFromField }) {
  const result = $("f_sim_result");
  if (!result) return;
  const enabled = $("f_boost_enabled")?.checked;
  const source = $("f_boost_source_type")?.value;
  const kpi = source === "KPI_METRIC";
  $("f_sim_target_wrap")?.classList.toggle("hidden", !enabled || kpi);
  $("f_sim_actual_wrap")?.classList.toggle("hidden", !enabled);
  if ($("f_sim_target_label")) $("f_sim_target_label").textContent = t("План, ₽");
  if ($("f_sim_actual_label")) $("f_sim_actual_label").textContent = t(kpi ? "Факт KPI" : "Факт, ₽");
  syncTierPreview();
  try {
    const tiers = enabled ? readPercentTiers({validate:true}) : [];
    if (enabled) validateTierCompatibility(selectedIdsFromField);
    const base = Math.round(number($("f_sim_base_rub")?.value) * 100);
    const target = number($("f_sim_target")?.value) * 100;
    const actual = number($("f_sim_actual")?.value) * (kpi ? 1 : 100);
    const baseRate = Math.round(number($("f_percent")?.value) * 100);
    const excess = enabled && $("f_boost_recalc_mode")?.value === "EXCESS_ONLY";
    // Compatible excess mode uses one revenue base for the condition and the payout.
    if (excess && actual !== base) { result.textContent = t("Для примера на превышение укажите одинаковые факт и базу начисления."); return; }
    const achieved = kpi ? actual : target > 0 ? actual * 100 / target : null;
    const matched = achieved == null ? null : tiers.filter((row) => row.threshold_value <= achieved).at(-1);
    const rate = matched?.percent_bps ?? baseRate;
    let amount = base * rate / 10000;
    if (excess && target > 0) {
      let cursor = 0, currentRate = baseRate; amount = 0;
      for (const tier of [...tiers, null]) {
        const boundary = tier ? target * tier.threshold_value / 100 : base;
        const end = Math.min(base, boundary);
        if (end > cursor) { amount += (end - cursor) * currentRate / 10000; cursor = end; }
        if (!tier || boundary >= base) break;
        currentRate = tier.percent_bps;
      }
    }
    amount = Math.round(amount);
    const minRaw = $("f_minimum_guarantee_minor")?.value.trim();
    const maxRaw = $("f_maximum_cap_minor")?.value.trim();
    if (minRaw) amount = Math.max(amount, Math.round(number(minRaw) * 100));
    if (maxRaw) amount = Math.min(amount, Math.round(number(maxRaw) * 100));
    const label = matched ? `≥ ${matched.threshold_value}${kpi ? "" : "%"} → ${rate/100}%` : `${t("Базовый процент:")} ${baseRate/100}%`;
    result.innerHTML = `<div class="pay-sim__stats"><div class="pay-sim__stat"><div class="pay-sim__stat-label">${t("Достигнутая ступень")}</div><div class="pay-sim__stat-value">${esc(label)}</div></div><div class="pay-sim__stat pay-sim__stat--accent"><div class="pay-sim__stat-label">${t("Начислено")}</div><div class="pay-sim__stat-value">${esc(fmtMoneyMinor(amount))}</div></div></div><p class="muted">${t(source?.endsWith("DAY_PLAN") || $("f_minimum_guarantee_scope")?.value === "DAY" ? "Пример для одного дня. Месячное начисление складывается из отдельных дней." : "Пример для одного месяца. Факт в расчёте берётся из закрытых отчётов.")}</p>`;
  } catch (error) { result.textContent = error.message; }
}
