export function createCatalogSetupController(context) {
  const { toast, confirmModal, api, UNIT_LABEL, CATALOG_CONFIG, state, esc, slugifyCode, ensureUniqueCode, getStepByKey, getInlineCatalogState, buildUnitOptions, getNextStepKey, moveToStep, loadSetup } = context;

  function renderCatalogListItems(stepKey, items, currentStep) {
    const cfg = CATALOG_CONFIG[stepKey];
    const inlineState = getInlineCatalogState(stepKey);
    const visibleItems = inlineState.showArchived ? items : items.filter((item) => item.is_active);
    if (!visibleItems.length) {
      return `<div class="setup-empty">${esc(cfg.emptyText)}</div>`;
    }
    return visibleItems.map((item) => {
      const unit = cfg.includeUnit ? String(item.unit || "QTY").toUpperCase() : "";
      return `
        <div class="setup-minirow">
          <div class="setup-minirow__main">
            <div class="setup-minirow__titlewrap">
              <b>${esc(item.title)}</b>
              ${item.is_active ? "" : `<span class="badge">архив</span>`}
              ${cfg.includeUnit ? `<span class="badge">${esc(UNIT_LABEL[unit] || unit)}</span>` : ""}
            </div>
            <div class="setup-minirow__meta">${esc(item.is_active ? cfg.activeHint : cfg.archivedHint)}</div>
          </div>
          <div class="setup-minirow__actions">
            <button class="btn sm" type="button" data-inline-edit="${esc(stepKey)}" data-item-id="${esc(item.id)}">Изменить</button>
            <button class="btn sm ${item.is_active ? "danger" : ""}" type="button" data-inline-toggle="${esc(stepKey)}" data-item-id="${esc(item.id)}">${item.is_active ? "В архив" : "Вернуть"}</button>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderCatalogEditor(stepKey, items, currentStep) {
    const cfg = CATALOG_CONFIG[stepKey];
    const inlineState = getInlineCatalogState(stepKey);
    const activeCount = items.filter((item) => item.is_active).length;
    const editingId = inlineState.editor?.id;
    const editingItem = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
    const mode = editingItem ? "edit" : "create";
    const initialTitle = editingItem?.title || "";
    const initialCode = editingItem?.code || "";
    const initialUnit = String(editingItem?.unit || "QTY").toUpperCase();

    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
          <label class="setup-toggle">
            <input type="checkbox" id="inlineShowArchived" ${inlineState.showArchived ? "checked" : ""} />
            <span>Показывать архив</span>
          </label>
        </div>

        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-minirows">${renderCatalogListItems(stepKey, items, currentStep)}</div>
          </div>

          <div class="setup-formcard">
            <div class="setup-editor__title">${mode === "edit" ? (cfg.editTitle || `Изменить ${cfg.title}`) : (cfg.createTitle || `Новый ${cfg.title}`)}</div>
            <div class="muted mt-6">${mode === "edit" ? "Сохрани изменения и шаг останется завершённым." : "Можно создать базовые элементы прямо здесь и сразу продолжить настройку."}</div>
            <div class="setup-formgrid mt-12">
              <label>
                <span>Название</span>
                <input class="input" id="inlineTitle" placeholder="Введите название" value="${esc(initialTitle)}" />
              </label>
              <label>
                <span>Код</span>
                <input class="input" id="inlineCode" placeholder="Будет сгенерирован автоматически" value="${esc(initialCode)}" />
              </label>
              ${cfg.includeUnit ? `
                <label>
                  <span>Единица</span>
                  <select class="input" id="inlineUnit">${buildUnitOptions(initialUnit)}</select>
                </label>
              ` : ""}
            </div>

            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnInlineSave" type="button">${mode === "edit" ? "Сохранить" : "Создать"}</button>
              ${mode === "edit" ? `<button class="btn subtle" id="btnInlineCancelEdit" type="button">Отмена</button>` : ""}
            </div>

            <div class="setup-inline-note">Код нужен для внутренней логики. Если не менять его вручную, он соберётся автоматически из названия.</div>
          </div>
        </div>

        <div class="setup-actionbar mt-14">
          ${activeCount > 0 && !currentStep.completed ? `<button class="btn" id="btnInlineComplete" type="button">Подтвердить шаг</button>` : ""}
          ${activeCount > 0 && !currentStep.completed ? `<button class="btn subtle" id="btnInlineCompleteNext" type="button">Подтвердить и дальше</button>` : ""}
          ${cfg.skippableInline && !currentStep.completed && !currentStep.skipped ? `<button class="btn subtle" id="btnInlineSkip" type="button">${esc(cfg.skipLabel || "Вернуться позже")}</button>` : ""}
        </div>
      </div>
    `;
  }

  async function loadInlineCatalogItems(stepKey, { force = false } = {}) {
    const cfg = CATALOG_CONFIG[stepKey];
    const inlineState = getInlineCatalogState(stepKey);
    if (!cfg) return [];
    if (!force && Array.isArray(inlineState.items)) return inlineState.items;
    inlineState.loading = true;
    try {
      const items = await cfg.load(state.venueId);
      inlineState.items = Array.isArray(items) ? items : [];
      return inlineState.items;
    } finally {
      inlineState.loading = false;
    }
  }

  async function refreshCatalogStepAndSetup(stepKey, currentStep, { tryNext = false } = {}) {
    await loadInlineCatalogItems(stepKey, { force: true });
    await loadSetup({ preserveSelection: true });
    if (tryNext) {
      const next = getNextStepKey(currentStep.key);
      if (next) moveToStep(next);
    }
  }

  async function mountCatalogEditor(currentStep) {
    const stepKey = currentStep.key;
    const host = document.getElementById("setupInlineEditor");
    if (!host) return;
    const cfg = CATALOG_CONFIG[stepKey];
    if (!cfg) {
      host.innerHTML = "";
      return;
    }

    host.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
    const items = await loadInlineCatalogItems(stepKey);
    const activeCount = items.filter((item) => item.is_active).length;
    if (stepKey in CATALOG_CONFIG && Number(currentStep.count || 0) !== activeCount && !(cfg.skippableInline && currentStep.skipped)) {
      await loadSetup({ preserveSelection: true });
      return;
    }

    host.innerHTML = renderCatalogEditor(stepKey, items, getStepByKey(stepKey) || currentStep);
    const inlineState = getInlineCatalogState(stepKey);
    const titleInput = document.getElementById("inlineTitle");
    const codeInput = document.getElementById("inlineCode");
    const unitInput = document.getElementById("inlineUnit");

    const applyAutoCode = () => {
      if (!codeInput || codeInput.dataset.touched === "1") return;
      codeInput.value = ensureUniqueCode(slugifyCode(titleInput?.value || "", stepKey === "kpi" ? "kpi" : "item"), items, inlineState.editor?.id || null);
    };
    titleInput?.addEventListener("input", applyAutoCode);
    codeInput?.addEventListener("input", () => { if (codeInput) codeInput.dataset.touched = codeInput.value ? "1" : ""; });
    if (titleInput && !codeInput?.value) applyAutoCode();

    document.getElementById("inlineShowArchived")?.addEventListener("change", async (e) => {
      inlineState.showArchived = !!e.target?.checked;
      await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
    });

    document.getElementById("btnInlineCancelEdit")?.addEventListener("click", async () => {
      inlineState.editor = { mode: "create", id: null };
      await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
    });

    document.getElementById("btnInlineSave")?.addEventListener("click", async () => {
      const title = String(titleInput?.value || "").trim();
      let code = String(codeInput?.value || "").trim().toLowerCase();
      if (!title) {
        toast("Заполни название", "err");
        titleInput?.focus();
        return;
      }
      if (!code) code = ensureUniqueCode(slugifyCode(title, stepKey === "kpi" ? "kpi" : "item"), items, inlineState.editor?.id || null);
      const payload = {
        title,
        code,
        is_active: true,
        sort_order: (Math.max(0, ...items.map((item) => Number(item.sort_order || 0))) || 0) + 10,
      };
      if (cfg.includeUnit) payload.unit = String(unitInput?.value || "QTY").toUpperCase();
      try {
        const wasEdit = Boolean(inlineState.editor?.id);
        if (wasEdit) await cfg.update(state.venueId, inlineState.editor.id, payload);
        else await cfg.create(state.venueId, payload);
        inlineState.editor = { mode: "create", id: null };
        await refreshCatalogStepAndSetup(stepKey, currentStep);
        if (!currentStep.completed) {
          try {
            await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
            await loadSetup({ preserveSelection: true });
          } catch {}
        }
        toast(wasEdit ? "Изменения сохранены" : "Элемент создан", "ok");
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось сохранить", "err");
      }
    });

    document.querySelectorAll(`[data-inline-edit="${stepKey}"]`).forEach((btn) => {
      btn.addEventListener("click", async () => {
        inlineState.editor = { mode: "edit", id: btn.getAttribute("data-item-id") || null };
        await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
      });
    });

    document.querySelectorAll(`[data-inline-toggle="${stepKey}"]`).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const itemId = btn.getAttribute("data-item-id") || "";
        const item = items.find((row) => String(row.id) === String(itemId));
        if (!item) return;
        const makeActive = !item.is_active;
        const ok = await confirmModal({
          title: makeActive ? `Вернуть ${cfg.title}?` : `Архивировать ${cfg.title}?`,
          text: `${makeActive ? "Вернуть" : "Убрать"} «${item.title}»?`,
          confirmText: makeActive ? "Вернуть" : "В архив",
          danger: !makeActive,
        });
        if (!ok) return;
        try {
          await cfg.update(state.venueId, item.id, { is_active: makeActive });
          await refreshCatalogStepAndSetup(stepKey, currentStep);
          toast(makeActive ? "Элемент восстановлен" : "Элемент архивирован", "ok");
        } catch (e) {
          toast(e?.data?.detail || e?.message || "Не удалось изменить состояние", "err");
        }
      });
    });

    document.getElementById("btnInlineComplete")?.addEventListener("click", async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
        await loadSetup({ preserveSelection: true });
        toast("Шаг подтверждён", "ok");
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
      }
    });

    document.getElementById("btnInlineCompleteNext")?.addEventListener("click", async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
        await loadSetup({ preserveSelection: true });
        toast("Шаг подтверждён", "ok");
        const next = getNextStepKey(stepKey);
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
      }
    });

    document.getElementById("btnInlineSkip")?.addEventListener("click", async () => {
      const ok = await confirmModal({
        title: cfg.skipConfirmTitle || "Отложить шаг?",
        text: cfg.skipConfirmText || "Этот шаг будет помечен как отложенный. К нему можно будет вернуться в любой момент.",
        confirmText: "Отложить",
        danger: false,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: "POST", body: { step_key: stepKey } });
        await loadSetup({ preserveSelection: true });
        toast("Шаг отложен", "ok");
        const next = getNextStepKey(stepKey);
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось отложить шаг", "err");
      }
    });
  }

  return { mountCatalogEditor };
}
