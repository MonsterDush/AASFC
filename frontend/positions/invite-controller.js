
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
    card.classList.add("hidden");
    return;
  }

  card.classList.remove("hidden");
  list.innerHTML = "";

  const titles = uniqueTitles();
  const canAssign = auth.canAssign;

  if (!titles.length) {
    const hint = document.createElement("div");
    hint.className = "position-state";
    hint.textContent = "Сначала создайте хотя бы одну должность — тогда можно будет назначать её приглашённым.";
    list.appendChild(hint);
  }

  invites.forEach((inv) => {
    const row = document.createElement("div");
    row.className = "position-invite-row";

    const channel = String(inv?.channel || inv?.invite_channel || "TELEGRAM").toUpperCase();
    const uname = (inv?.tg_username || "").trim().replace(/^@+/, "");
    const contact = channel === "PHONE"
      ? String(inv?.contact_label || inv?.phone || "Телефон")
      : `@${uname || "—"}`;
    const presetTitle = inv?.default_position?.title ? String(inv.default_position.title) : "";

    const options = [
      `<option value="">— не назначено —</option>`,
      ...titles.map((t) => `<option value="${esc(t)}" ${t === presetTitle ? "selected" : ""}>${esc(t)}</option>`),
    ].join("");

    row.innerHTML = `
      <div class="position-invite-person">
        <div><b>${esc(contact)}</b> <span class="badge badge--draft">приглашён</span></div>
        <div class="muted small mt-4">${esc(inv?.venue_role === "OWNER" ? "Владелец" : "Персонал")}</div>
      </div>
      <div class="position-invite-assignment">
        <div class="muted mb-6">Должность</div>
        <select data-invite-id="${esc(String(inv.id))}" ${(!canAssign || !titles.length) ? "disabled" : ""}>
          ${options}
        </select>
        ${!canAssign ? `<div class="muted small mt-6">Недостаточно прав для назначения</div>` : ``}
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
