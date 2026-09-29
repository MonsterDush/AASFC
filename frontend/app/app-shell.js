const NAV_ICON_PATHS = {
  venue: ["M3 11.5 12 4l9 7.5", "M5.5 10.5V20h13v-9.5", "M9.5 20v-6h5v6"],
  dashboard: ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"],
  summary: ["M4 19V9", "M10 19V5", "M16 19v-7", "M22 19H2"],
  revenue: ["M4 17 10 11l4 4 6-8", "M15 7h5v5"],
  expenses: ["M6 3h12v18l-3-2-3 2-3-2-3 2z", "M9 8h6", "M9 12h6"],
  payroll: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8", "M17 8h5", "M19.5 5.5v5"],
  ledger: ["M3 6h18v13H3z", "M3 10h18", "M7 15h4"],
  day: ["M5 4h14v16H5z", "M8 2v4", "M16 2v4", "M5 9h14"],
  schedule: ["M5 4h14v16H5z", "M8 2v4", "M16 2v4", "M5 9h14", "M8 13h3", "M13 13h3", "M8 17h3"],
  report: ["M5 3h14v18H5z", "M9 7h6", "M9 11h6", "M9 15h4"],
  integrations: ["M8 12h8", "M12 8v8", "M5 5h4v4H5z", "M15 15h4v4h-4z"],
  plans: ["M4 19V5", "M4 19h16", "M8 16v-5", "M12 16V8", "M16 16v-3"],
  settings: ["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7", "M12 2v3", "M12 19v3", "M4.9 4.9 7 7", "M17 17l2.1 2.1", "M2 12h3", "M19 12h3", "M4.9 19.1 7 17", "M17 7l2.1-2.1"],
};

export function createAppNavIcon(name = "") {
  const wrap = document.createElement("span");
  wrap.className = "app-nav-icon";
  wrap.setAttribute("aria-hidden", "true");
  const paths = NAV_ICON_PATHS[name] || NAV_ICON_PATHS.dashboard;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  paths.forEach((data) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", data);
    svg.appendChild(path);
  });
  wrap.appendChild(svg);
  return wrap;
}

export function mountAppShell({
  container,
  venues = [],
  activeVenueId = "",
  isOwner = false,
  t,
  setActiveVenueId,
} = {}) {
  const wrap = container?.closest(".wrap");
  if (!wrap) return;

  wrap.querySelectorAll("[data-app-shell-chrome]").forEach((node) => node.remove());

  const qp = activeVenueId ? `?venue_id=${encodeURIComponent(activeVenueId)}` : "";
  const brand = document.createElement("a");
  brand.className = "app-nav-brand";
  brand.href = isOwner && activeVenueId ? `/owner-dashboard.html${qp}` : "/app-venues.html";
  brand.setAttribute("data-app-shell-chrome", "brand");
  brand.setAttribute("aria-label", "Axelio");

  const logo = document.createElement("span");
  logo.className = "logo";
  logo.setAttribute("aria-hidden", "true");
  const wordmark = document.createElement("span");
  wordmark.textContent = "Axelio";
  brand.append(logo, wordmark);
  container.prepend(brand);

  const activeVenue = venues.find((venue) => String(venue.id) === String(activeVenueId)) || venues[0];
  if (activeVenue) {
    const venue = document.createElement("div");
    venue.className = "app-nav-venue";
    venue.setAttribute("data-app-shell-chrome", "venue");

    const avatar = document.createElement("span");
    avatar.className = "app-nav-venue__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = String(activeVenue.name || "A").trim().slice(0, 2).toUpperCase();

    const select = document.createElement("select");
    select.className = "app-nav-venue__select";
    select.setAttribute("aria-label", t("venue"));
    venues.forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = item.name || `${t("venue")} #${item.id}`;
      select.appendChild(option);
    });
    select.value = String(activeVenue.id);
    select.addEventListener("change", () => {
      const nextVenueId = select.value;
      setActiveVenueId(nextVenueId);
      const url = new URL(location.href);
      url.searchParams.set("venue_id", nextVenueId);
      location.href = `${url.pathname}${url.search}`;
    });

    venue.append(avatar, select);
    const settingsLink = container.querySelector('a[data-tab="settings"]');
    if (settingsLink) container.insertBefore(venue, settingsLink);
    else container.appendChild(venue);
  }

  document.body.classList.add("app-shell-enabled");
}
