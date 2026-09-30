const STORAGE_PREFIX = "axelio.setup-draft.v1";

export function setupDraftStorageKey(venueId, stepKey) {
  return `${STORAGE_PREFIX}:${String(venueId || "")}:${String(stepKey || "")}`;
}

function controlKey(control) {
  const id = String(control?.id || "").trim();
  if (id) return `id:${id}`;
  const name = String(control?.name || "").trim();
  if (!name) return "";
  const type = String(control?.type || "").toLowerCase();
  return type === "checkbox" || type === "radio"
    ? `name:${name}:value:${String(control.value || "")}`
    : `name:${name}`;
}

export function collectSetupDraft(host) {
  const fields = {};
  host?.querySelectorAll?.("input, select, textarea").forEach((control) => {
    const key = controlKey(control);
    const type = String(control?.type || "").toLowerCase();
    if (!key || type === "file" || type === "password") return;
    fields[key] = type === "checkbox" || type === "radio"
      ? { checked: Boolean(control.checked) }
      : { value: String(control.value ?? "") };
  });
  return fields;
}

export function restoreSetupDraft(host, fields) {
  let restored = 0;
  const visibilityControls = new Set([
    "inviteChannel",
    "inlineComponentType",
    "inlineComponentKpiCalculationMode",
    "recurringGenerationMode",
  ]);
  const changed = [];
  host?.querySelectorAll?.("input, select, textarea").forEach((control) => {
    const saved = fields?.[controlKey(control)];
    if (!saved) return;
    const type = String(control?.type || "").toLowerCase();
    if (type === "checkbox" || type === "radio") control.checked = Boolean(saved.checked);
    else if (Object.hasOwn(saved, "value")) control.value = String(saved.value ?? "");
    restored += 1;
    if (visibilityControls.has(String(control.id || ""))) changed.push(control);
  });
  changed.forEach((control) => control.dispatchEvent?.(new Event("change", { bubbles: true })));
  return restored;
}

function setDraftStatus(status, text) {
  if (status) status.textContent = text;
}

export function clearSetupDraft({ venueId, stepKey, storage = globalThis.sessionStorage } = {}) {
  try { storage?.removeItem?.(setupDraftStorageKey(venueId, stepKey)); } catch {}
  setDraftStatus(globalThis.document?.getElementById?.("setupDraftStatus"), "Изменения сохранены");
}

export function attachSetupDraft({ host, venueId, stepKey, storage = globalThis.sessionStorage } = {}) {
  if (!host || !venueId || !stepKey) return () => {};
  const key = setupDraftStorageKey(venueId, stepKey);
  const status = globalThis.document?.getElementById?.("setupDraftStatus");
  try {
    const saved = JSON.parse(storage?.getItem?.(key) || "null");
    if (saved?.fields && restoreSetupDraft(host, saved.fields)) {
      setDraftStatus(status, "Черновик восстановлен в этой вкладке");
    }
  } catch {}

  const persist = () => {
    try {
      storage?.setItem?.(key, JSON.stringify({ fields: collectSetupDraft(host), updated_at: new Date().toISOString() }));
      setDraftStatus(status, "Черновик сохранён в этой вкладке");
    } catch {
      setDraftStatus(status, "Не удалось сохранить черновик в этой вкладке");
    }
  };
  host.addEventListener("input", persist);
  host.addEventListener("change", persist);
  return () => {
    host.removeEventListener("input", persist);
    host.removeEventListener("change", persist);
  };
}
