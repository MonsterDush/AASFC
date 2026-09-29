export function payrollPreviewPath(venueId, month) {
  return `/venues/${encodeURIComponent(venueId)}/payroll/preview?month=${encodeURIComponent(month)}`;
}

export function recalculationText(latestRecalc, runCalculatedAt) {
  const reasonMap = {
    manual_calculation: "ручной расчёт",
    report_closed: "после закрытия отчёта",
    report_reopened: "после переоткрытия отчёта",
    closed_report_updated: "после правки закрытого отчёта",
    shift_assignment_added: "после назначения",
    shift_assignment_removed: "после снятия назначения",
    shift_updated: "после изменения смены",
    shift_deleted: "после удаления смены",
    member_removed_from_venue: "после удаления участника",
    member_left_venue: "после выхода участника",
    department_month_plan_updated: "после изменения месячного плана департамента",
    department_day_plan_updated: "после изменения дневного плана департамента",
    department_day_plans_updated: "после массового изменения дневных планов департамента",
    pay_profile_updated: "после изменения профиля",
    pay_component_created: "после добавления компонента",
    pay_component_updated: "после изменения компонента",
    pay_component_deleted: "после удаления компонента",
    position_pay_profile_created: "после назначения профиля должности",
    position_pay_profile_updated: "после изменения профиля должности",
    position_pay_profile_deleted: "после снятия профиля должности",
  };
  const dt = runCalculatedAt ? new Date(runCalculatedAt) : null;
  const locale = globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU";
  const baseText = dt && !Number.isNaN(dt.getTime())
    ? `обновлено ${dt.toLocaleString(locale)}`
    : (latestRecalc?.created_at ? `обновлено ${new Date(latestRecalc.created_at).toLocaleString(locale)}` : "есть перерасчёт");
  const reason = String(latestRecalc?.trigger_reason || "");
  return reason ? `${baseText} · ${reasonMap[reason] || "автоперерасчёт"}` : baseText;
}

function warningText(warning, formatDateRu) {
  const code = String(warning?.code || "").toUpperCase();
  if (code === "PAY_PROFILE_UNRESOLVED") {
    const shift = warning?.shift_id ? `смена #${warning.shift_id}` : "закрытая смена";
    const date = warning?.shift_date ? ` за ${formatDateRu(warning.shift_date)}` : "";
    return `${shift}${date}: сотруднику не удалось определить профиль зарплаты.`;
  }
  if (code === "PAY_PROFILE_WITHOUT_COMPONENTS") {
    const title = warning?.pay_profile_title || `профиль #${warning?.pay_profile_id || "—"}`;
    return `${title}: нет активных компонентов начисления.`;
  }
  return code || "Неизвестная ошибка конфигурации зарплаты";
}

export function renderPayrollDiagnostics(state, { setVisible, esc, formatDateRu }) {
  const card = document.getElementById("payrollDiagnosticsCard");
  const container = document.getElementById("payrollDiagnostics");
  if (!card || !container) return;
  const storedWarnings = Array.isArray(state.data?.latest_recalculation?.details?.warnings)
    ? state.data.latest_recalculation.details.warnings
    : [];
  const previewWarnings = Array.isArray(state.payrollPreview?.blocking_warnings)
    ? state.payrollPreview.blocking_warnings
    : [];
  const warnings = state.payrollPreview ? previewWarnings : storedWarnings;
  const shouldShow = state.periodMode === "month" && state.can.calculate
    && (warnings.length || state.payrollPreviewError);
  setVisible(card, Boolean(shouldShow));
  if (!shouldShow) {
    container.innerHTML = "";
    return;
  }
  if (state.payrollPreviewError && !warnings.length) {
    container.innerHTML = `<div class="payroll-state payroll-state--error"><b>Проверка недоступна</b><span>${esc(state.payrollPreviewError)}</span></div>`;
    return;
  }
  container.innerHTML = `<div class="payroll-state payroll-state--denied">
    <b>Расчёт заблокирован: исправьте настройки</b>
    <span>${warnings.map((warning) => esc(warningText(warning, formatDateRu))).join("<br>")}</span>
  </div>`;
}
