export function createNavigation(context) {
  const { normalizePermList, permSetFromResponse, roleUpper, hasAnyPerm, hasPermPrefix, hasStaffDashboardExtras, t, cacheSystemRole, applyTheme, api, ensureLogin, getActiveVenueId, setActiveVenueId, getMe, getMyVenues, getMyVenuePermissions } = context;

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Renders a venue switcher <select> into container (or returns null if 0/1 venues).
   * onChange receives (newVenueId).
   */
  function renderVenueSwitcher({ container, venues, activeVenueId, onChange }) {
    if (!container) return null;
    if (!Array.isArray(venues) || venues.length <= 1) {
      container.innerHTML = "";
      return null;
    }

    container.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "venue-switch";

    const label = document.createElement("span");
    label.className = "venue-switch__label";
    label.textContent = "Venue:";

    const sel = document.createElement("select");
    sel.className = "venue-switch__select";

    venues.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = String(v.id);
      opt.textContent = v.name ? v.name : `Venue #${v.id}`;
      sel.appendChild(opt);
    });

    sel.value = String(activeVenueId || venues[0].id || "");

    sel.onchange = () => {
      const id = sel.value;
      setActiveVenueId(id);
      if (typeof onChange === "function") onChange(id);
    };

    wrap.appendChild(label);
    wrap.appendChild(sel);
    container.appendChild(wrap);

    return sel;
  }

  /**
   * Convenience: loads /me/venues, renders switcher, and keeps URL in sync via onChange.
   * If current page uses ?venue_id=, we update that param and reload.
   */
  async function mountVenueSwitcher({ containerSelector = "#venueSwitcher", venues = null, onChange = null } = {}) {
    const el = document.querySelector(containerSelector);
    if (!el) return null;

    const v = venues || (await getMyVenues().catch(() => []));
    const active = getActiveVenueId() || (v[0] ? String(v[0].id) : "");

    return renderVenueSwitcher({
      container: el,
      venues: v,
      activeVenueId: active,
      onChange:
        onChange ||
        ((newId) => {
          const url = new URL(location.href);
          if (url.searchParams.has("venue_id")) url.searchParams.set("venue_id", newId);
          location.href = url.pathname + url.search;
        }),
    });
  }

  async function getVenueById(venueId) {
    if (!venueId) return null;

    // Берём из "моих заведений" (это доступно OWNER/STAFF)
    const list = await api("/me/venues?include_archived=true");
    const v = (list || []).find(x => String(x.id) === String(venueId));
    return v || null;
  }
  // ------------------------------
  // Permissions + dynamic navigation (A2/A3)
  // ------------------------------


  function can(permCode, venuePerms) {
    if (!permCode) return false;
    const list = normalizePermList(venuePerms?.permissions || venuePerms);
    return list.includes(String(permCode));
  }


  function renderNavLinks({ container, links, activeTab }) {
    if (!container) return;
    if (typeof container.__axelioNavCleanup === "function") {
      container.__axelioNavCleanup();
    }
    container.innerHTML = "";

    const mobilePrimaryLinkCount = 3;
    const appendLink = (parent, link, { menu = false, overflow = false } = {}) => {
      const a = document.createElement("a");
      a.href = link.href;
      a.textContent = menu && link.tab === "settings" ? t("settings") : link.title;
      if (link.className && !menu) a.className = link.className;
      if (menu) a.classList.add("nav-more__link");
      if (overflow && !menu) a.classList.add("nav-overflow-link");
      a.setAttribute("data-tab", link.tab);
      if (link.tab === activeTab) {
        a.classList.add("active");
        a.setAttribute("aria-current", "page");
      }
      parent.appendChild(a);
      return a;
    };

    links.forEach((link, index) => {
      appendLink(container, link, { overflow: index >= mobilePrimaryLinkCount });
    });

    const overflowLinks = links.slice(mobilePrimaryLinkCount);
    if (!overflowLinks.length) return;

    const moreWrap = document.createElement("div");
    moreWrap.className = "nav-more";

    const menuId = `${container.id || "nav"}-more-menu`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "nav-more__button";
    button.textContent = t("more");
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-controls", menuId);
    button.setAttribute("aria-expanded", "false");
    if (overflowLinks.some((link) => link.tab === activeTab)) {
      button.classList.add("active");
    }

    const menu = document.createElement("div");
    menu.id = menuId;
    menu.className = "nav-more__menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    overflowLinks.forEach((link) => {
      const menuLink = appendLink(menu, link, { menu: true });
      menuLink.setAttribute("role", "menuitem");
    });

    const closeMenu = ({ restoreFocus = false } = {}) => {
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (restoreFocus) button.focus();
    };
    const onDocumentClick = (event) => {
      if (!moreWrap.contains(event.target)) closeMenu();
    };
    const onDocumentKeydown = (event) => {
      if (event.key === "Escape" && !menu.hidden) {
        closeMenu({ restoreFocus: true });
      }
    };

    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const shouldOpen = menu.hidden;
      menu.hidden = !shouldOpen;
      button.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    });
    menu.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("keydown", onDocumentKeydown);
    container.__axelioNavCleanup = () => {
      document.removeEventListener("click", onDocumentClick);
      document.removeEventListener("keydown", onDocumentKeydown);
    };

    moreWrap.append(button, menu);
    container.appendChild(moreWrap);
  }

  /**
   * Mounts a bottom nav with only allowed items.
   *
   * Rules (MVP):
   * - SUPER_ADMIN: admin pages only
   * - Others: Venues + (if active venue) Venue/Invites
   *
   * Later we'll extend links as we add pages (Shifts/Salary/Adjustments/Reports).
   */
  async function mountNav({ activeTab = "dashboard", containerSelector = "#nav" } = {}) {
    const container = document.querySelector(containerSelector);
    if (!container) return { ok: false, reason: "NO_CONTAINER" };

    // Deep links: if venue_id is in URL, treat it as active venue (prevents missing owner navbar)
    try {
      const qv = new URLSearchParams(location.search).get("venue_id");
      if (qv) setActiveVenueId(qv);
    } catch {}

    await ensureLogin({ silent: true });

    let me = null;
    try { me = await getMe(); } catch {
      container.innerHTML = "";
      return { ok: false, reason: "NO_ME" };
    }

    // cache system role for gated features (themes, admin-only UI)
    cacheSystemRole(me?.system_role);
    // re-apply theme now that role is known (enables SUPER_ADMIN-only themes)
    applyTheme();

    // SUPER_ADMIN bottom nav
    if (me?.system_role === "SUPER_ADMIN") {
      renderNavLinks({
        container,
        links: [
          { title: t("admin_venues"), href: "/admin-venues.html", tab: "admin-venues" },
          { title: "Биллинг", href: "/admin-billing.html", tab: "admin-billing" },
          { title: "Шаблоны", href: "/admin-position-templates.html", tab: "admin-position-templates" },
          { title: "DEMO", href: "/admin-demo.html", tab: "admin-demo" },
          { title: t("admin_invites"), href: "/admin-invites.html", tab: "admin-invites" },
          { title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" },
        ],
        activeTab,
      });
      return { ok: true, me };
    }

    // Regular users (OWNER/STAFF)
    let venues = [];
    try { venues = await getMyVenues(); } catch { venues = []; }

    let activeVenueId = getActiveVenueId();

    // If user has venues but no active venue chosen yet, pick the first one automatically.
    // This prevents "2-tab navbar" on pages that require a venue context.
    try {
      const page = (location.pathname.split("/").pop() || "").toLowerCase();
      const isVenuePicker = page === "app-venues.html";
      if (!activeVenueId && !isVenuePicker && venues.length >= 1) {
        activeVenueId = String(venues[0].id);
        setActiveVenueId(activeVenueId);
      } else if (!activeVenueId && venues.length === 1) {
        activeVenueId = String(venues[0].id);
        setActiveVenueId(activeVenueId);
      }
    } catch {
      if (!activeVenueId && venues.length === 1) {
        activeVenueId = String(venues[0].id);
        setActiveVenueId(activeVenueId);
      }
    }

  // Determine permissions for active venue (best-effort)
  let isOwner = false;
  let canViewReports = false;
  let canShowStaffOverview = false;

  const activeVenue = activeVenueId ? venues.find(v => String(v.id) === String(activeVenueId)) : null;
  const roleFromList = String(activeVenue?.role || activeVenue?.venue_role || activeVenue?.my_role || "").toUpperCase();

  if (activeVenueId) {
    try {
      const permsResp = await getMyVenuePermissions(activeVenueId);
      const role = roleUpper(permsResp) || roleFromList;
      isOwner = role === "OWNER" || role === "VENUE_OWNER";

      const pset = permSetFromResponse(permsResp);

      // Report access means: user can open report pages / close shift / see report sections.
      canViewReports =
        isOwner ||
        hasPermPrefix(pset, "SHIFT_REPORT_") ||
        hasPermPrefix(pset, "REPORTS_") ||
        hasAnyPerm(pset, [
          "SHIFT_REPORT_VIEW",
          "SHIFT_REPORT_CLOSE",
          "SHIFT_REPORT_EDIT",
          "SHIFT_REPORT_REOPEN",
          "REPORTS_VIEW_DAILY",
          "REPORTS_VIEW_MONTHLY",
          "REPORTS_VIEW_PNL",
        ]);
      canShowStaffOverview = !isOwner && hasStaffDashboardExtras(pset, role, String(me?.system_role || ""));
    } catch {
      isOwner = roleFromList === "OWNER" || roleFromList === "VENUE_OWNER";
      canViewReports = isOwner;
      canShowStaffOverview = false;
    }
  }

  const qp = activeVenueId ? `?venue_id=${encodeURIComponent(activeVenueId)}` : "";

    const links = [];

    if (activeVenueId) {
      if (isOwner) {      // Owner bottom nav: Venue / Summary / Expenses
        links.push({ title: t("venue"), href: `/app-venue.html${qp}`, tab: "venue" });      links.push({ title: t("summary"), href: `/owner-summary.html${qp}`, tab: "summary" });
        links.push({ title: t("expenses"), href: `/owner-expenses.html${qp}`, tab: "expenses" });
        links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
      } else {
        // Staff bottom nav:
  // - If NO report access: Schedule + Salaries + Adjustments + Settings
  // - If HAS report access: Schedule + Finance + Reports + Settings
  links.push({ title: t("shifts"), href: `/staff-shifts.html${qp}`, tab: "shifts" });

  if (canViewReports) {
    links.push({ title: canShowStaffOverview ? t("overview") : t("finance"), href: `${canShowStaffOverview ? "/app-dashboard.html" : "/staff-finance.html"}${qp}`, tab: canShowStaffOverview ? "overview" : "finance" });
    links.push({ title: t("report"), href: `/staff-report.html${qp}`, tab: "report" });
  } else {
    links.push({ title: t("salary"), href: `/staff-salary.html${qp}`, tab: "salary" });
    links.push({ title: t("adjustments"), href: `/staff-adjustments.html${qp}`, tab: "adjustments" });
  }

  links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
      }
    } else {
      // No active venue chosen yet
      links.push({ title: t("manage_venues"), href: "/app-venues.html", tab: "app-venues" });
      links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
    }

    renderNavLinks({ container, links, activeTab });
    return { ok: true, me, venues, activeVenueId };
  }

  // ------------------------------
  // Venue dropdown menu (topbar)
  // ------------------------------
  async function leaveVenue(venueId) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/leave`, { method: "POST" });
  }

  async function mountVenueMenu({ containerSelector = "#venueMenu", onVenueChanged = null } = {}) {
    const el = document.querySelector(containerSelector);
    if (!el) return null;

    let venues = [];
    try { venues = await getMyVenues(); } catch { venues = []; }

    // Always show, even if 0/1 venues
    const active = getActiveVenueId() || (venues[0] ? String(venues[0].id) : "");
    if (active) setActiveVenueId(active);

    el.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "venue-switch";

    const label = document.createElement("span");
    label.className = "venue-switch__label";
    label.textContent = t("venue") + ":";

    const sel = document.createElement("select");
    sel.className = "input min-w240";

    if (!venues.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "—";
      sel.appendChild(opt);
    } else {
      for (const v of venues) {
        const opt = document.createElement("option");
        opt.value = String(v.id);
        opt.textContent = v.name ? v.name : `#${v.id}`;
        sel.appendChild(opt);
      }
    }

    // action items
    const optManage = document.createElement("option");
    optManage.value = "__manage__";
    optManage.textContent = "────────";
    optManage.disabled = true;
    sel.appendChild(optManage);

    const optManage2 = document.createElement("option");
    optManage2.value = "__manage2__";
    optManage2.textContent = t("manage_venues");
    sel.appendChild(optManage2);

    sel.value = active || (venues[0] ? String(venues[0].id) : "");

    sel.onchange = async () => {
      const val = sel.value;
      if (val === "__manage2__") {
        location.href = "/app-venues.html";
        return;
      }

      // normal venue switch
      setActiveVenueId(val);
      if (typeof onVenueChanged === "function") onVenueChanged(val);
      else {
        const url = new URL(location.href);
        if (url.searchParams.has("venue_id")) url.searchParams.set("venue_id", val);
        location.href = url.pathname + url.search;
      }
    };

    wrap.appendChild(label);
    wrap.appendChild(sel);
    el.appendChild(wrap);
    return sel;
  }

  return { renderVenueSwitcher, mountVenueSwitcher, getVenueById, can, mountNav, leaveVenue, mountVenueMenu };
}
