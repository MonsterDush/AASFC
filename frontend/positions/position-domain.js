
export function createPositionDomain({ state }) {
function fioInitials(fullName) {
  const s = String(fullName || "").trim();
  if (!s) return "";
  const p = s.split(/\s+/).filter(Boolean);
  if (p.length === 1) return p[0];
  const surname = p[0];
  const initials = p.slice(1).map(x => (x[0] ? x[0].toUpperCase() + "." : "")).join("");
  return `${surname} ${initials}`.trim();
}

function memberNiceName(m) {
  const displayName = (m?.display_name || "").trim();
  if (displayName) return displayName;
  const shortName = (m?.short_name || "").trim();
  if (shortName) return shortName;
  const fi = fioInitials(m?.full_name);
  if (fi) return fi;
  const u = (m?.tg_username || "").trim();
  if (u) return u.startsWith("@") ? u : `@${u}`;
  return m?.user_id ? "Сотрудник" : "—";
}

function memberLabel(m) {
  const name = memberNiceName(m);
  const u = (m?.tg_username || "").trim();
  const uTxt = u ? (u.startsWith("@") ? u : `@${u}`) : "";
  const role = (m?.venue_role || "").toUpperCase();
  return `${name}${uTxt && !name.includes("@") ? ` · ${uTxt}` : ""}${role ? ` · ${role}` : ""}`;
}

function parsePermCodes(v) {
  if (Array.isArray(v)) {
    return v.map((x) => String(x || "").trim()).filter(Boolean);
  }
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return [];
    // JSON array string
    try {
      const j = JSON.parse(s);
      if (Array.isArray(j)) return j.map((x) => String(x || "").trim()).filter(Boolean);
    } catch {}
    // fallback: comma/space separated, also handles "['A','B']"
    const cleaned = s.replace(/[\[\]\"']/g, "");
    return cleaned.split(/[,;\s]+/).map((x) => String(x || "").trim()).filter(Boolean);
  }
  return [];
}


// Permission codes are the single source of truth for position access.
function posPermSet(p) {
  const raw = (p && p.permission_codes) ?? [];
  const arr = Array.isArray(raw) ? raw : parsePermCodes(raw);
  const set = new Set();
  for (const x of arr || []) {
    const s = String(x || "").trim().toUpperCase();
    if (s) set.add(s);
  }
  return set;
}

function posHasPerm(p, code) {
  if (!code) return false;
  return posPermSet(p).has(String(code).trim().toUpperCase());
}

function posHasAnyPerm(p, codes) {
  const s = posPermSet(p);
  return Array.isArray(codes) && codes.some((c) => s.has(String(c).trim().toUpperCase()));
}

function posReportsEnabled(p) {
  // Any report-related permission means "Отчёты: да"
  return posHasAnyPerm(p, [
    "SHIFT_REPORT_VIEW",
    "SHIFT_REPORT_CLOSE",
    "SHIFT_REPORT_EDIT",
    "SHIFT_REPORT_REOPEN",
    "REPORTS_VIEW_DAILY",
    "REPORTS_VIEW_MONTHLY",
    "REPORTS_VIEW_PNL",
  ]);
}

function posScheduleManage(p) {
  return posHasPerm(p, "SHIFTS_MANAGE");
}


function normalizePositions(out) {
  let items = [];
  if (!out) items = [];
  else if (Array.isArray(out)) items = out;
  else if (Array.isArray(out.items)) items = out.items;
  else if (Array.isArray(out.positions)) items = out.positions;
  else if (Array.isArray(out.data)) items = out.data;
  else items = [];

  return items.map((p) => {
    const x = { ...(p || {}) };
    if (x.pay_profile_id != null && x.pay_profile_id !== "") x.pay_profile_id = Number(x.pay_profile_id) || null;
    const pc = parsePermCodes(x.permission_codes);
    if (pc.length) x.permission_codes = pc;
    else if (typeof x.permission_codes === "string") x.permission_codes = [];
    return x;
  });
}

function normalizePositionPresets(out) {
  let items = [];
  if (!out) items = [];
  else if (Array.isArray(out)) items = out;
  else if (Array.isArray(out.items)) items = out.items;
  else if (Array.isArray(out.presets)) items = out.presets;
  else if (Array.isArray(out.data)) items = out.data;
  else items = [];

  return items.map((p, idx) => {
    const x = { ...(p || {}) };
    x.id = String(x.id || `preset-${idx + 1}`);
    x.title = String(x.title || "").trim();
    x.rate = Math.max(0, Math.round(Number(x.rate || 0) || 0));
    x.percent = Math.max(0, Math.min(100, Math.round(Number(x.percent || 0) || 0)));
    x.pay_profile_id = x.pay_profile_id != null && x.pay_profile_id !== "" ? Number(x.pay_profile_id) || null : null;
    x.pay_profile_title = String(x.pay_profile_title || "").trim();
    x.permission_codes = parsePermCodes(x.permission_codes);
    x.is_active = x.is_active !== false;
    return x;
  }).filter((x) => x.title);
}

function positionSources() {
  return [
    ...(Array.isArray(state.positionPresets) ? state.positionPresets.filter((x) => x.is_active !== false) : []),
    ...(Array.isArray(state.positions) ? state.positions.filter((x) => x.is_active !== false) : []),
  ];
}

function uniqueTitles() {
  const set = new Set();
  for (const p of positionSources()) {
    const t = String(p.title || "").trim();
    if (t) set.add(t);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
}

function positionPresetFromTemplate(title) {
  const t = String(title || "").trim();
  if (!t) return null;

  const src = positionSources().find((x) => String(x.title || "").trim() === t) || { title: t };

  // Only permission_codes are stored in invite preset (no legacy flags).
  const permission_codes = parsePermCodes(src.permission_codes);

  return {
    title: t,
    rate: Math.max(0, Math.round(Number(src.rate || 0) || 0)),
    percent: Math.max(0, Math.min(100, Math.round(Number(src.percent || 0) || 0))),
    pay_profile_id: src.pay_profile_id || null,
    pay_profile_title: src.pay_profile_title || null,
    permission_codes,
  };
}

return {
  fioInitials,
  memberNiceName,
  memberLabel,
  parsePermCodes,
  posPermSet,
  posHasPerm,
  posHasAnyPerm,
  posReportsEnabled,
  posScheduleManage,
  normalizePositions,
  normalizePositionPresets,
  positionSources,
  uniqueTitles,
  positionPresetFromTemplate,
};
}
