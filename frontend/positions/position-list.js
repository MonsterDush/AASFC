
export function createPositionList({
  state,
  auth,
  esc,
  domain,
  editor,
  toast,
  confirmModal,
  deleteVenuePosition,
  load,
}) {
const { memberLabel, posReportsEnabled, posScheduleManage } = domain;
const { openCreateModal, openEditModal } = editor;

function buildPositionGroups() {
  const groups = new Map();
  const ensureGroup = (rawTitle) => {
    const title = String(rawTitle || "Без названия").trim() || "Без названия";
    if (!groups.has(title)) groups.set(title, { title, positions: [], preset: null });
    return groups.get(title);
  };

  for (const preset of state.positionPresets || []) {
    if (preset?.is_active === false) continue;
    const group = ensureGroup(preset?.title);
    if (!group.preset) group.preset = preset;
  }

  for (const position of state.positions || []) {
    if (position?.is_active === false) continue;
    ensureGroup(position?.title).positions.push(position);
  }

  return Array.from(groups.values()).sort((a, b) => a.title.localeCompare(b.title, "ru"));
}

function employeeCountLabel(count) {
  const value = Math.max(0, Number(count) || 0);
  const mod10 = value % 10;
  const mod100 = value % 100;
  const word = mod10 === 1 && mod100 !== 11
    ? "сотрудник"
    : (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "сотрудника" : "сотрудников");
  return `${value} ${word}`;
}

function renderPositions() {
  const list = document.getElementById("list");
  list.innerHTML = "";

  const groups = buildPositionGroups();
  if (!groups.length) {
    list.innerHTML = `
      <div class="position-state">
        <b>Должностей пока нет</b>
        <span>Создайте первую должность, чтобы назначать сотрудников, профиль начислений и права.</span>
      </div>
    `;
    return;
  }

  const memberById = new Map(state.members.map((m) => [String(m.user_id), m]));

  for (const group of groups) {
    const { title, preset } = group;
    const arr = group.positions.slice().sort((a, b) => {
      const aa = String(memberById.get(String(a.member_user_id))?.tg_username || "");
      const bb = String(memberById.get(String(b.member_user_id))?.tg_username || "");
      return aa.localeCompare(bb);
    });

    const wrap = document.createElement("div");
    wrap.className = "itemcard position-group";

    wrap.innerHTML = `
      <div class="position-group__head">
        <div class="position-group__title">
          <b>${esc(title)}</b>
          <span class="position-count">${employeeCountLabel(arr.filter((p) => Number(p.member_user_id || 0) > 0).length)}</span>
        </div>
        ${auth.canManage && auth.canAssign ? `<button class="btn" data-add-same>+ Добавить сотрудника</button>` : ``}
      </div>
      <div class="position-member-list" data-rows></div>
    `;

    // "+ Добавить сотрудника" с предзаполненным title
    const addSameBtn = wrap.querySelector("[data-add-same]");
    if (addSameBtn) addSameBtn.onclick = () => openCreateModal({
      title,
      hint: "Добавляем ещё одного сотрудника на эту должность.",
      position: preset || arr[0] || { title },
    });

    const rows = wrap.querySelector("[data-rows]");

    if (!arr.length && preset) {
      rows.innerHTML = `
        <div class="position-member-row position-member-row--empty">
          <div class="position-member-row__main">
            <div><b>Сотрудники ещё не назначены</b></div>
            <div class="position-meta-chips">
              <span class="position-meta-chip">Профиль: ${esc(preset.pay_profile_title || "не назначен")}</span>
              <span class="position-meta-chip">Отчёты: ${posReportsEnabled(preset) ? "да" : "нет"}</span>
              <span class="position-meta-chip">График: ${posScheduleManage(preset) ? "да" : "нет"}</span>
            </div>
          </div>
        </div>
      `;
    }

    for (const p of arr) {
      const m = memberById.get(String(p.member_user_id || ""));
      const hasMember = Number(p.member_user_id || 0) > 0;
      const who = m ? memberLabel(m) : (hasMember ? "Сотрудник" : "Сотрудники ещё не назначены");

      const row = document.createElement("div");
      row.className = "position-member-row";

      row.innerHTML = `
        <div class="position-member-row__main">
          <div><b>${esc(who)}</b></div>
          <div class="position-meta-chips">
            <span class="position-meta-chip">Профиль: ${esc(p.pay_profile_title || "не назначен")}</span>
            <span class="position-meta-chip">Отчёты: ${posReportsEnabled(p) ? "да" : "нет"}</span>
            <span class="position-meta-chip">График: ${posScheduleManage(p) ? "да" : "нет"}</span>
          </div>
        </div>
        <div class="position-member-row__actions">
          ${auth.canManage ? `<button class="btn" data-edit>Изменить</button>` : (auth.canManagePerms ? `<button class="btn" data-perms>Права</button>` : ``)}
          ${auth.canManage ? `<button class="btn danger" data-del>${hasMember ? "Убрать" : "Архивировать"}</button>` : ``}
        </div>
      `;

      const btnEdit = row.querySelector("[data-edit]");
      if (btnEdit) btnEdit.onclick = async () => { await openEditModal(p, "edit"); };

      const btnPerms = row.querySelector("[data-perms]");
      if (btnPerms) btnPerms.onclick = async () => { await openEditModal(p, "perms"); };

      const btnDel = row.querySelector("[data-del]");
      if (btnDel) btnDel.onclick = async () => {
        const ok = await confirmModal({
          title: hasMember ? "Убрать сотрудника с должности?" : "Архивировать должность?",
          text: hasMember
            ? `Сотрудник будет снят с должности «${title}», а сама должность останется доступной.`
            : `Должность «${title}» будет перенесена в архив.`,
          confirmText: hasMember ? "Убрать" : "В архив",
          danger: true,
        });
        if (!ok) return;

        try {
          await deleteVenuePosition(state.venueId, p.id);
          toast(hasMember ? "Сотрудник снят с должности" : "Должность архивирована", "ok");
          await load();
        } catch (e) {
          toast("Ошибка удаления: " + (e?.message || e), "err");
        }
      };

      rows.appendChild(row);
    }


    list.appendChild(wrap);
  }
}

return { buildPositionGroups, renderPositions };
}
