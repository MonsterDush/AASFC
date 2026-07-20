
export function createPositionInviteController({
  state,
  auth,
  esc,
  domain,
  toast,
  patchInviteDefaultPosition,
}) {
const { uniqueTitles, positionPresetFromTemplate } = domain;

function renderInvites() {
  const card = document.getElementById("invitesCard");
  const list = document.getElementById("invitesList");
  if (!card || !list) return;

  const invites = Array.isArray(state.invites) ? state.invites : [];
  if (!invites.length) {
    card.style.display = "none";
    return;
  }

  card.style.display = "";
  list.innerHTML = "";

  const titles = uniqueTitles();
  const canAssign = auth.canAssign;

  if (!titles.length) {
    const hint = document.createElement("div");
    hint.className = "muted";
    hint.textContent = "Сначала создайте хотя бы одну должность — тогда можно будет назначать её приглашённым.";
    list.appendChild(hint);
  }

  invites.forEach((inv) => {
    const row = document.createElement("div");
    row.className = "row";
    row.style = "justify-content:space-between; gap:12px; border-bottom:1px solid var(--border); padding:10px 0; align-items:flex-start; flex-wrap:wrap";

    const uname = (inv?.tg_username || "").trim();
    const presetTitle = inv?.default_position?.title ? String(inv.default_position.title) : "";

    const options = [
      `<option value="">— не назначено —</option>`,
      ...titles.map((t) => `<option value="${esc(t)}" ${t === presetTitle ? "selected" : ""}>${esc(t)}</option>`),
    ].join("");

    row.innerHTML = `
      <div style="min-width:220px">
        <div><b>@${esc(uname || "-")}</b> <span class="badge badge--draft">приглашён</span></div>
        <div class="muted" style="margin-top:4px; font-size:12px">${esc(inv?.venue_role === "OWNER" ? "Владелец" : "Персонал")}</div>
      </div>
      <div style="min-width:240px">
        <div class="muted" style="margin-bottom:6px">Должность</div>
        <select data-invite-id="${esc(String(inv.id))}" ${(!canAssign || !titles.length) ? "disabled" : ""}>
          ${options}
        </select>
        ${!canAssign ? `<div class="muted small" style="margin-top:6px">Недостаточно прав для назначения</div>` : ``}
      </div>
    `;

    list.appendChild(row);
  });

  // handlers
  list.querySelectorAll("select[data-invite-id]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const inviteId = Number(sel.getAttribute("data-invite-id"));
      if (!inviteId) return;
      if (!auth.canAssign) return;

      const v = String(sel.value || "");
      const preset = v ? positionPresetFromTemplate(v) : null;

      try {
        await patchInviteDefaultPosition(state.venueId, inviteId, preset);
        toast("Сохранено", "ok");

        // update local state
        for (const it of state.invites) {
          if (Number(it.id) === inviteId) {
            it.default_position = preset;
            break;
          }
        }

        renderInvites();
      } catch (e) {
        toast("Не удалось назначить должность: " + (e?.data?.detail || e?.message || "ошибка"), "err");
      }
    });
  });
}

return { renderInvites };
}
