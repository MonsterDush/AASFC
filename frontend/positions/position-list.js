
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

function renderPositions() {
  const list = document.getElementById("list");
  list.innerHTML = "";

  if (!state.positions.length) {
    list.innerHTML = `<div class="muted">Должностей пока нет</div>`;
    return;
  }

  const memberById = new Map(state.members.map((m) => [String(m.user_id), m]));

  // group by title
  const groups = new Map();
  for (const p of state.positions) {
    const t = String(p.title || "Без названия").trim() || "Без названия";
    if (!groups.has(t)) groups.set(t, []);
    groups.get(t).push(p);
  }

  const titles = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b, "ru"));

  for (const title of titles) {
    const arr = groups.get(title).slice().sort((a, b) => {
      const aa = String(memberById.get(String(a.member_user_id))?.tg_username || "");
      const bb = String(memberById.get(String(b.member_user_id))?.tg_username || "");
      return aa.localeCompare(bb);
    });

    const wrap = document.createElement("div");
    wrap.className = "itemcard";
    wrap.style.marginTop = "10px";

    wrap.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
        <b>${esc(title)} <span class="muted">(${arr.length})</span></b>
        ${auth.canManage ? `<button class="btn" data-add-same>+ Добавить сотрудника</button>` : ``}
      </div>
      <div class="list" style="margin-top:10px" data-rows></div>
    `;

    // "+ Добавить сотрудника" с предзаполненным title
    const addSameBtn = wrap.querySelector("[data-add-same]");
    if (addSameBtn) addSameBtn.onclick = () => openCreateModal({
      title,
      hint: "Добавляем ещё одного сотрудника на эту должность.",
    });

    const rows = wrap.querySelector("[data-rows]");

    for (const p of arr) {
      const m = memberById.get(String(p.member_user_id || ""));
      const who = m ? memberLabel(m) : (p.member_user_id ? "Сотрудник" : "—");

      const row = document.createElement("div");
      row.className = "list__row";

      row.innerHTML = `
        <div class="list__main">
          <div><b>${esc(who)}</b></div>
          <div class="muted" style="margin-top:4px">
            Профиль: ${esc(p.pay_profile_title || "не назначен")} ·
            Отчёты: ${posReportsEnabled(p) ? "да" : "нет"} · График: ${posScheduleManage(p) ? "да" : "нет"}
          </div>
        </div>
        <div class="row" style="gap:8px; flex-wrap:wrap">
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

return { renderPositions };
}
