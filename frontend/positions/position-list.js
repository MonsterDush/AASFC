
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

function renderPositions() {
  const list = document.getElementById("list");
  list.innerHTML = "";

  const groups = buildPositionGroups();
  if (!groups.length) {
    list.innerHTML = `<div class="muted">Должностей пока нет</div>`;
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
    wrap.className = "itemcard mt-10";

    wrap.innerHTML = `
      <div class="row row--between ai-center">
        <b>${esc(title)} <span class="muted">(${arr.length})</span></b>
        ${auth.canManage ? `<button class="btn" data-add-same>+ Добавить сотрудника</button>` : ``}
      </div>
      <div class="list mt-10" data-rows></div>
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
        <div class="list__row">
          <div class="list__main">
            <div><b>Сотрудники ещё не назначены</b></div>
            <div class="muted mt-4">
              Профиль: ${esc(preset.pay_profile_title || "не назначен")} ·
              Отчёты: ${posReportsEnabled(preset) ? "да" : "нет"} · График: ${posScheduleManage(preset) ? "да" : "нет"}
            </div>
          </div>
        </div>
      `;
    }

    for (const p of arr) {
      const m = memberById.get(String(p.member_user_id || ""));
      const who = m ? memberLabel(m) : (p.member_user_id ? "Сотрудник" : "—");

      const row = document.createElement("div");
      row.className = "list__row";

      row.innerHTML = `
        <div class="list__main">
          <div><b>${esc(who)}</b></div>
          <div class="muted mt-4">
            Профиль: ${esc(p.pay_profile_title || "не назначен")} ·
            Отчёты: ${posReportsEnabled(p) ? "да" : "нет"} · График: ${posScheduleManage(p) ? "да" : "нет"}
          </div>
        </div>
        <div class="row gap-8">
          ${auth.canManage ? `<button class="btn" data-edit>Изменить</button>` : (auth.canManagePerms ? `<button class="btn" data-perms>Права</button>` : ``)}
          ${auth.canManage ? `<button class="btn danger" data-del>Архивировать</button>` : ``}
        </div>
      `;

      const btnEdit = row.querySelector("[data-edit]");
      if (btnEdit) btnEdit.onclick = async () => { await openEditModal(p, "edit"); };

      const btnPerms = row.querySelector("[data-perms]");
      if (btnPerms) btnPerms.onclick = async () => { await openEditModal(p, "perms"); };

      const btnDel = row.querySelector("[data-del]");
      if (btnDel) btnDel.onclick = async () => {
        const ok = await confirmModal({
          title: "Архивировать должность?",
          text: `Удалить должность «${title}» для сотрудника?`,
          confirmText: "В архив",
          danger: true,
        });
        if (!ok) return;

        try {
          await deleteVenuePosition(state.venueId, p.id);
          toast("Должность архивирована", "ok");
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
