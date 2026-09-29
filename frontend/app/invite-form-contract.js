export function buildDefaultPositionPayload(item) {
  if (!item || item.is_active === false) return null;
  const title = String(item.title || "").trim();
  if (!title) return null;
  return {
    title,
    venue_position_id: Number(item.venue_position_id || item.id || 0) || null,
    rate: Math.max(0, Math.round(Number(item.rate || 0))),
    percent: Math.max(0, Math.min(100, Math.round(Number(item.percent || 0)))),
    pay_profile_id: Number(item.pay_profile_id || 0) || null,
    pay_profile_title: item.pay_profile_title || null,
    permission_codes: Array.isArray(item.permission_codes) ? item.permission_codes : [],
  };
}

export function buildInvitePayload({ channel, role, contactLabel, telegram, phone, positionPreset }) {
  const normalizedChannel = String(channel || "TELEGRAM").toUpperCase();
  const payload = {
    invite_channel: normalizedChannel,
    venue_role: String(role || "STAFF").toUpperCase(),
    contact_label: String(contactLabel || "").trim() || null,
    default_position: buildDefaultPositionPayload(positionPreset),
  };
  if (normalizedChannel === "PHONE") payload.phone = String(phone || "").trim();
  else payload.tg_username = String(telegram || "").trim();
  return payload;
}
