import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  api,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

function applyRevenueCardAccess(canView) {
  const card = document.getElementById("turnoverCard");
  if (!card) return;
  card.style.display = canView ? "" : "none";
}

async function canViewRevenue() {
  const venueId = getActiveVenueId();
  if (!venueId) return false;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    return role === "OWNER" || role === "VENUE_OWNER" || hasPerm(pset, "REVENUE_VIEW");
  } catch {
    return false;
  }
}

function fmtMoney(n) {
  const x = Math.round(Number(n || 0));
  try { return new Intl.NumberFormat("ru-RU").format(x) + " ₽"; } catch { return String(x) + " ₽"; }
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

async function loadTurnoverForMonth(monthYYYYMM) {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  const allowed = await canViewRevenue();
  applyRevenueCardAccess(allowed);
  if (!allowed) return;

  const res = await api(`/venues/${encodeURIComponent(venueId)}/revenue?month=${encodeURIComponent(monthYYYYMM)}&mode=PAYMENTS`);
  const total = res?.total ?? null;
  const el = document.getElementById("turnoverTotal");
  if (el) el.textContent = (total === null || total === undefined) ? "—" : fmtMoney(total);

  const btn = document.getElementById("turnoverDetailsBtn");
  if (btn) {
    btn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", monthYYYYMM);
      qp.set("mode", "PAYMENTS");
      qp.set("period", "month");
      // Canonical revenue page
      location.href = `/owner-turnover.html?${qp.toString()}`;
    };
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "summary" });

  // show venue name in subtitle (best-effort)
  try {
    const venues = await getMyVenues();
    const v = venues.find(x => String(x.id) === String(getActiveVenueId()));
    if (v) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = v.name || "";
    }
  } catch {}

  const monthPick = document.getElementById("summaryMonthPick");
  const month = params.get("month") || currentMonth();
  if (monthPick) {
    monthPick.value = month;
    monthPick.onchange = (e) => loadTurnoverForMonth(e.target.value || currentMonth());
  }

  await loadTurnoverForMonth(month);
}

document.addEventListener("DOMContentLoaded", () => { boot(); });
