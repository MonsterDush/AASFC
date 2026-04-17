function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function normalizePermissionTemplates(items = []) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    ...item,
    id: item?.id,
    title: String(item?.title || "").trim(),
    description: String(item?.description || "").trim(),
    permission_codes: Array.isArray(item?.permission_codes) ? item.permission_codes.map((code) => String(code || "").trim().toUpperCase()).filter(Boolean) : [],
    permission_summary: item?.permission_summary && typeof item.permission_summary === 'object' ? item.permission_summary : null,
    is_active: item?.is_active !== false,
    is_system: item?.is_system === true,
  }));
}

export function getPermissionTemplateById(templates, templateId) {
  return (Array.isArray(templates) ? templates : []).find((item) => String(item?.id || "") === String(templateId || "")) || null;
}

export function buildPermissionTemplateOptions(templates, { selectedId = "", emptyLabel = "— выбрать шаблон прав —", includeSystemBadge = true } = {}) {
  const current = String(selectedId || "");
  const items = (Array.isArray(templates) ? templates : []).filter((item) => item?.is_active !== false);
  return [`<option value="">${esc(emptyLabel)}</option>`]
    .concat(items.map((item) => `<option value="${esc(item.id)}" ${String(item.id) === current ? "selected" : ""}>${esc(item.title || `Шаблон #${item.id}`)}${includeSystemBadge && item.is_system ? " · system" : ""}</option>`))
    .join("");
}

export function renderPermissionTemplateSummary(template, { emptyText = "Шаблон не выбран. Можно собрать права вручную ниже.", noDescriptionText = "Шаблон без описания", wrapId = "" } = {}) {
  if (!template) {
    return `<div class="muted"${wrapId ? ` id="${esc(wrapId)}"` : ""}>${esc(emptyText)}</div>`;
  }
  const labels = Array.isArray(template?.permission_summary?.summary_labels) ? template.permission_summary.summary_labels : [];
  return `
    <div${wrapId ? ` id="${esc(wrapId)}"` : ""}>
      <div class="muted">${esc(template.description || noDescriptionText)}</div>
      <div class="row" style="gap:6px; flex-wrap:wrap; margin-top:6px">${labels.length ? labels.map((label) => `<span class="badge">${esc(label)}</span>`).join("") : `<span class="muted">Прав: ${Number(template?.permission_summary?.permission_count || (template.permission_codes || []).length || 0)}</span>`}</div>
    </div>
  `;
}

export function renderPermissionTemplateSummaryById(templates, templateId, options = {}) {
  return renderPermissionTemplateSummary(getPermissionTemplateById(templates, templateId), options);
}

export function applyPermissionTemplateToCheckboxHost({ templates, templateId, checkboxSelector, checkboxAttr, summaryHost = null, titleInput = null, fillTitleWhenEmpty = false, summaryOptions = {} } = {}) {
  const template = getPermissionTemplateById(templates, templateId);
  if (!template) return false;
  if (titleInput && fillTitleWhenEmpty && !String(titleInput.value || "").trim() && template.title) {
    titleInput.value = String(template.title || "").trim();
  }
  const selected = new Set((template.permission_codes || []).map((code) => String(code || "").trim().toUpperCase()));
  const nodes = Array.from((summaryHost?.ownerDocument || document).querySelectorAll(checkboxSelector || 'input[type="checkbox"]'));
  nodes.forEach((el) => {
    const code = String(el.getAttribute(checkboxAttr || 'data-perm-code') || "").trim().toUpperCase();
    if (!code) return;
    el.checked = selected.has(code);
  });
  if (summaryHost) {
    summaryHost.innerHTML = renderPermissionTemplateSummary(template, summaryOptions);
  }
  return true;
}
