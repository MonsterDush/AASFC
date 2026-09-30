
export function createPayAssignmentController({
  state,
  esc,
  memberName,
  openEditModal,
  closeEditModal,
  toast,
  confirmModal,
  createPayProfileAssignment,
  updatePayProfileAssignment,
  deletePayProfileAssignment,
  load,
}) {
function resolveAssignmentMember(item) {
  const memberUserId = String(item?.member_user_id || item?.member?.user_id || "");
  const venueMember = (state.members || []).find((member) => String(member?.user_id || "") === memberUserId);
  return { ...(item?.member || {}), ...(venueMember || {}) };
}

function renderAssignments() {
  const el = document.getElementById("assignmentsList");
  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="muted">Нет доступа</div>`;
    return;
  }
  const items = Array.isArray(state.profile?.assignments) ? state.profile.assignments : [];
  const positionItems = Array.isArray(state.profile?.position_assignments) ? state.profile.position_assignments : [];
  if (!items.length && !positionItems.length) {
    el.innerHTML = `<div class="muted">Назначений пока нет</div>`;
    return;
  }
  el.innerHTML = "";
  if (positionItems.length) {
    const heading = document.createElement("div");
    heading.className = "muted small mb-8";
    heading.textContent = "Через должности";
    el.appendChild(heading);
  }
  positionItems.forEach((it) => {
    const label = memberName(resolveAssignmentMember(it));
    const range = `${it.valid_from || "без даты начала"} → ${it.valid_to || "без даты окончания"}`;
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div class="row gap-8"><b>${esc(label)}</b>${it.is_active ? "" : `<span class="badge">неактивно</span>`}</div>
        <div>${esc(it.position_title || "Должность")}</div>
        <div class="mono listrow__meta">${esc(range)}</div>
      </div>
    `;
    el.appendChild(row);
  });
  if (items.length) {
    const heading = document.createElement("div");
    heading.className = "muted small mt-12 mb-8";
    heading.textContent = "Прямые назначения без должности";
    el.appendChild(heading);
  }
  items.forEach((it) => {
    const label = memberName(resolveAssignmentMember(it));
    const range = `${it.start_date || "без даты начала"} → ${it.end_date || "без даты окончания"}`;
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div class="row gap-8">
          <b>${esc(label)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивно</span>`}
        </div>
        <div class="mono listrow__meta">${esc(range)}</div>
      </div>
      <div class="row row--nowrap gap-8 flex-none" id="assignmentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#assignmentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Изменить";
      editBtn.onclick = () => openAssignmentEditor({ mode: "edit", item: it });
      actions.appendChild(editBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить назначение?",
          text: `Удалить назначение для ${label}?`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayProfileAssignment(state.venueId, it.id);
          toast("Назначение удалено", "ok");
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

function assignmentForm({ mode, item }) {
  const it = item || {};
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasMembers = Array.isArray(state.members) && state.members.length > 0;
  const options = state.members.map((m) => `<option value="${esc(m.user_id)}">${esc(memberName(m))}</option>`).join("");
  return `
    <div class="finance-form mt-8">
      ${mode === "edit" ? `
        <label>
          <span>Сотрудник</span>
          <input value="${esc(memberName(resolveAssignmentMember(it)))}" disabled />
        </label>
      ` : hasMembers ? `
        <label>
          <span>Сотрудник</span>
          <select id="f_member_user_id">
            <option value="">Выбери сотрудника</option>
            ${options}
          </select>
        </label>
      ` : `
        <label>
          <span>Номер сотрудника</span>
          <input id="f_member_user_id" inputmode="numeric" placeholder="Например: 12" />
        </label>
        <div class="muted">Список сотрудников не загрузился. Можно ввести номер сотрудника вручную.</div>
      `}
      <label>
        <span>Дата начала</span>
        <input id="f_start_date" type="date" value="${esc(it.start_date || "")}" />
      </label>
      <label>
        <span>Дата окончания</span>
        <input id="f_end_date" type="date" value="${esc(it.end_date || "")}" />
      </label>
      <label class="chk">
        <input type="checkbox" id="f_active" ${activeChecked} />
        <span>Назначение активно</span>
      </label>
    </div>

    <div class="row row--end gap-8 mt-12">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function openAssignmentEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать прямое назначение" : "Новое прямое назначение",
    hint: "Используется только как fallback без разрешимого профиля должности. Если даты пустые, профиль действует без ограничений.",
    bodyHtml: assignmentForm({ mode, item }),
  });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const memberUserId = String(document.getElementById("f_member_user_id")?.value || "").trim();
    const startDate = String(document.getElementById("f_start_date")?.value || "").trim();
    const endDate = String(document.getElementById("f_end_date")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    const payload = {
      start_date: startDate || null,
      end_date: endDate || null,
      is_active: isActive,
    };

    if (!isEdit) {
      if (!memberUserId) {
        toast("Выбери сотрудника", "warn");
        return;
      }
      payload.member_user_id = Number(memberUserId);
    }

    try {
      if (isEdit && item?.id) {
        await updatePayProfileAssignment(state.venueId, item.id, payload);
        toast("Назначение обновлено", "ok");
      } else {
        await createPayProfileAssignment(state.venueId, state.profileId, payload);
        toast("Назначение создано", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

return { resolveAssignmentMember, renderAssignments, openAssignmentEditor };
}
