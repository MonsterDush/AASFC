const t = (text) => window.AxelioI18n?.t?.(text) || text;

export function tierBreakdown(snap, { esc, fmtMoneyMinor, fmtPercentBps }) {
  const rows = [];
  const push = (label, value) => rows.push(`<div class="payroll-breakdown__kv-item"><span class="payroll-breakdown__kv-label">${esc(t(label))}</span><span class="payroll-breakdown__kv-value">${esc(value)}</span></div>`);
  const kpi = snap.threshold_unit === "VALUE";
  const tierLabel = (tier) => tier ? `≥ ${tier.threshold_value}${kpi ? "" : "%"} → ${fmtPercentBps(tier.percent_bps)}` : t("Базовый процент");
  push("Источник порога", [t(snap.boost_source_title), ...(snap.boost_department_titles || []), snap.boost_kpi_metric_title].filter(Boolean).join(" · "));
  push("База начисления", fmtMoneyMinor(snap.base_amount_minor));
  push("Базовый процент", fmtPercentBps(snap.regular_percent_bps));
  push("Настроенные ступени", (snap.percent_tiers || []).map(tierLabel).join(" · "));
  if (snap.applied_percent_varies_by_day) {
    push("Применённый процент", t("Определяется отдельно по каждому дню"));
  } else {
    if (!kpi) push("План", snap.boost_target_minor == null ? t("Не установлен") : fmtMoneyMinor(snap.boost_target_minor));
    push(kpi ? "Факт KPI" : "Факт", kpi ? String(snap.boost_actual_value ?? 0) : fmtMoneyMinor(snap.boost_actual_minor));
    if (!kpi) push("Выполнение плана", snap.achievement_percent == null ? "—" : `${Number(snap.achievement_percent.toFixed(2))}%`);
    push("Достигнутая ступень", tierLabel(snap.matched_tier));
    push("Применённый процент", fmtPercentBps(snap.applied_percent_bps));
  }
  push("Режим пересчёта", t(snap.boost_recalc_mode_effective === "EXCESS_ONLY" ? "Повышенный процент только на превышение" : "Новый процент на всю сумму"));
  if (snap.recalc_fallback_reason) push("Совместимость старого правила", t("База отличается от плана: применён процент на всю сумму"));
  if (snap.minimum_applied) push("Минимальная гарантия", fmtMoneyMinor(snap.minimum_guarantee_minor));
  if (snap.maximum_applied) push("Максимум начисления", fmtMoneyMinor(snap.maximum_cap_minor));
  push("Начислено", fmtMoneyMinor(snap.final_amount_minor));
  const segments = (snap.segments || []).map((row) => `${fmtMoneyMinor(row.base_amount_minor)} × ${fmtPercentBps(row.percent_bps)} = ${fmtMoneyMinor(row.amount_minor)}`).join(" · ");
  return `<div class="payroll-breakdown__kv">${rows.join("")}</div>${segments ? `<p class="muted">${esc(segments)}</p>` : ""}`;
}

export function tierDayBreakdown(snap, { esc, fmtMoneyMinor, fmtPercentBps, formatDateRu }) {
  if (!snap.day_rows?.length) return "";
  return `<details class="payroll-breakdown__dayrows"><summary>${t("Расчёт по дням")} · ${snap.day_rows.length}</summary>${snap.day_rows.map((row) => {
    const parts = [t("План"), row.target_amount_minor == null ? t("Не установлен") : fmtMoneyMinor(row.target_amount_minor), t("Факт"), fmtMoneyMinor(row.actual_amount_minor)];
    if (row.monthly_allocation) parts.splice(0, parts.length, t("Доля месячного начисления"));
    if (row.achievement_percent != null) parts.push(`${Number(row.achievement_percent.toFixed(2))}%`);
    if (row.matched_tier) parts.push(`≥ ${row.matched_tier.threshold_value}%`);
    parts.push(fmtPercentBps(row.percent_bps));
    if (row.minimum_applied) parts.push(t("Минимальная гарантия"));
    const segments = (row.segments || []).map((part) => `${fmtMoneyMinor(part.base_amount_minor)} × ${fmtPercentBps(part.percent_bps)}`).join(" + ");
    return `<div class="payroll-breakdown__dayrow"><div class="payroll-breakdown__dayrow-main"><div class="payroll-breakdown__dayrow-date">${esc(formatDateRu(row.date))}</div><div class="payroll-breakdown__dayrow-meta">${esc(parts.join(" · "))}${segments ? `<br>${esc(segments)}` : ""}</div></div><div>${esc(fmtMoneyMinor(row.amount_minor))}</div></div>`;
  }).join("")}${snap.maximum_applied ? `<p class="muted">${t("Сумма по дням показана до применения месячного максимума.")}</p>` : ""}</details>`;
}
