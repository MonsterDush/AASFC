export function intervalPositionIds(interval) {
  if (Array.isArray(interval?.position_ids)) return interval.position_ids.map(Number);
  return interval?.position_id ? [Number(interval.position_id)] : [];
}

export function intervalPositionLabel(interval) {
  return interval?.position_titles?.join(", ") || interval?.position_title || "Все должности";
}

export function positionMatchesInterval(position, interval) {
  const ids = intervalPositionIds(interval);
  return !ids.length || ids.includes(Number(position?.catalog_position_id));
}

export function availableIntervalsForMember(intervals, positions, memberId) {
  if (!Number(memberId)) return intervals;
  const memberPositions = positions.filter((position) => position.is_active !== false
    && Number(position.member_user_id ?? position.member?.user_id) === Number(memberId));
  return intervals.filter((interval) => memberPositions.some((position) => positionMatchesInterval(position, interval)));
}

export function positionScopeEditor(id, positions, interval, esc) {
  const selected = intervalPositionIds(interval);
  const items = positions.filter((position) => position.is_active !== false && !Number(position.member_user_id));
  selected.forEach((positionId, index) => {
    if (!items.some((position) => Number(position.id) === positionId)) {
      items.push({ id: positionId, title: interval?.position_titles?.[index] || interval?.position_title || "Должность" });
    }
  });
  return `<div id="${esc(id)}" role="group" aria-label="Доступно для должностей">
    <div class="muted mb-6">Доступно для должностей</div>
    <label class="chk"><input type="checkbox" data-all ${selected.length ? "" : "checked"} /><span>Все должности</span></label>
    <div class="grid grid2 mt-8">${items.map((position) => `<label class="chk">
      <input type="checkbox" data-position-id="${esc(position.id)}" ${selected.includes(Number(position.id)) ? "checked" : ""} />
      <span>${esc(position.title)}</span></label>`).join("")}</div>
  </div>`;
}

export function readPositionScope(root) {
  return Array.from(root?.querySelectorAll("[data-position-id]:checked") || [], (input) => Number(input.dataset.positionId));
}

export function wirePositionScope(root) {
  root?.addEventListener("change", (event) => {
    const all = root.querySelector("[data-all]");
    if (event.target === all) {
      root.querySelectorAll("[data-position-id]").forEach((input) => { input.checked = false; });
    }
    all.checked = readPositionScope(root).length === 0;
  });
}
