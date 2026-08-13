export function createVenueApi(context) {
  const { storeDemoUiState, removeDemoBanner, mountDemoBanner, maybeTrackDemoPageView, api, ensureLogin } = context;

  const LS_ACTIVE_VENUE = "axelio.activeVenueId";


  function withTimeout(promise, ms, label = "REQUEST_TIMEOUT") {
    let timer = null;
    return new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        const err = new Error(label);
        err.code = "TIMEOUT";
        reject(err);
      }, ms);
      Promise.resolve(promise).then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        }
      );
    });
  }


  function getActiveVenueId() {
    try { return localStorage.getItem(LS_ACTIVE_VENUE) || ""; } catch { return ""; }
  }

  function setActiveVenueId(id) {
    try {
      if (id === null || id === undefined || String(id).trim() === "") {
        localStorage.removeItem(LS_ACTIVE_VENUE);
        return;
      }
      localStorage.setItem(LS_ACTIVE_VENUE, String(id));
    } catch {}
  }

  async function getMe({ timeoutMs = 8000 } = {}) {
    const me = await withTimeout(api("/me"), timeoutMs, "ME_TIMEOUT");
    const profileLocale = String(me?.preferred_locale || "").toLowerCase();
    const currentLocale = window.AxelioI18n?.getLocale?.();
    const requestedLocale = String(new URLSearchParams(location.search).get("lang") || "")
      .trim()
      .toLowerCase()
      .split(/[-_]/, 1)[0];
    if (["ru", "en"].includes(requestedLocale)) {
      me.preferred_locale = requestedLocale;
      if (profileLocale !== requestedLocale) {
        void api("/me/profile", {
          method: "PATCH",
          body: { preferred_locale: requestedLocale },
        }).catch(() => {});
      }
    } else if (["ru", "en"].includes(profileLocale)) {
      try {
        if (currentLocale !== profileLocale) {
          window.AxelioI18n?.setLocale?.(profileLocale);
          location.reload();
        }
      } catch {}
    } else if (["ru", "en"].includes(currentLocale)) {
      me.preferred_locale = currentLocale;
      void api("/me/profile", {
        method: "PATCH",
        body: { preferred_locale: currentLocale },
      }).catch(() => {});
    }
    const demoState = storeDemoUiState(me);
    if (demoState?.demo_mode) { mountDemoBanner(demoState); maybeTrackDemoPageView(demoState); }
    else removeDemoBanner();
    return me;
  }

  async function getMyVenues({ timeoutMs = 8000, includeArchived = false } = {}) {
    const suffix = includeArchived ? "?include_archived=true" : "";
    return withTimeout(api(`/me/venues${suffix}`), timeoutMs, "MY_VENUES_TIMEOUT");
  }

  async function createSelfServiceVenue(payload) {
    return api("/venues/self-service", { method: "POST", body: payload });
  }

  async function getMyVenuePermissions(venueId, { timeoutMs = 8000 } = {}) {
    if (!venueId) return { venue_id: null, role: null, permissions: [] };
    try {
      return await withTimeout(
        api(`/me/venues/${encodeURIComponent(venueId)}/permissions`),
        timeoutMs,
        "MY_VENUE_PERMISSIONS_TIMEOUT",
      );
    } catch (e) {
      if (e?.code === "TIMEOUT" || /TIMEOUT/i.test(String(e?.message || ""))) {
        return { venue_id: Number(venueId) || venueId, role: null, permissions: [], _timed_out: true };
      }
      throw e;
    }
  }

  // ------------------------------
  // Venues: members + positions
  // ------------------------------

  async function getVenueMembers(venueId) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/members`);
  }

  async function getVenuePositions(venueId) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/positions`);
  }

  async function getVenuePositionPresets(venueId, { includeInactive = false } = {}) {
    if (!venueId) throw new Error("NO_VENUE");
    const qs = includeInactive ? "?include_inactive=true" : "";
    return api(`/venues/${encodeURIComponent(venueId)}/position-presets${qs}`);
  }

  async function createVenuePosition(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/positions`, {
      method: "POST",
      body: payload,
    });
  }

  async function updateVenuePosition(venueId, positionId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!positionId) throw new Error("NO_POSITION");
    return api(`/venues/${encodeURIComponent(venueId)}/positions/${encodeURIComponent(positionId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function deleteVenuePosition(venueId, positionId) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!positionId) throw new Error("NO_POSITION");
    return api(`/venues/${encodeURIComponent(venueId)}/positions/${encodeURIComponent(positionId)}`, {
      method: "DELETE",
    });
  }

  // ------------------------------
  // Venue settings
  // ------------------------------

  async function getVenueSettings(venueId) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/settings`);
  }

  async function updateVenueSettings(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/settings`, {
      method: "PATCH",
      body: payload,
    });
  }

  // ------------------------------
  // Invites (pending)
  // ------------------------------

  /**
   * Sets default position preset for a pending invite.
   * Backend endpoint: PATCH /venues/{venue_id}/invites/{invite_id}/default_position
   */
  async function patchInviteDefaultPosition(venueId, inviteId, defaultPosition) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!inviteId) throw new Error("NO_INVITE");
    return api(`/venues/${encodeURIComponent(venueId)}/invites/${encodeURIComponent(inviteId)}/default_position`, {
      method: "PATCH",
      body: { default_position: defaultPosition ?? null },
    });
  }

  // ------------------------------
  // Catalogs: departments / payment methods / KPI metrics
  // ------------------------------

  async function getDepartments(venueId, { includeArchived = false } = {}) {
    if (!venueId) throw new Error("NO_VENUE");
    const q = includeArchived ? "?include_archived=true" : "";
    return api(`/venues/${encodeURIComponent(venueId)}/departments${q}`);
  }

  async function createDepartment(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/departments`, { method: "POST", body: payload });
  }

  async function updateDepartment(venueId, departmentId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!departmentId) throw new Error("NO_DEPARTMENT");
    return api(`/venues/${encodeURIComponent(venueId)}/departments/${encodeURIComponent(departmentId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function getPaymentMethods(venueId, { includeArchived = false } = {}) {
    if (!venueId) throw new Error("NO_VENUE");
    const q = includeArchived ? "?include_archived=true" : "";
    return api(`/venues/${encodeURIComponent(venueId)}/payment-methods${q}`);
  }

  async function createPaymentMethod(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/payment-methods`, { method: "POST", body: payload });
  }

  async function updatePaymentMethod(venueId, paymentMethodId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!paymentMethodId) throw new Error("NO_PAYMENT_METHOD");
    return api(`/venues/${encodeURIComponent(venueId)}/payment-methods/${encodeURIComponent(paymentMethodId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function getKpiMetrics(venueId, { includeArchived = false } = {}) {
    if (!venueId) throw new Error("NO_VENUE");
    const q = includeArchived ? "?include_archived=true" : "";
    return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics${q}`);
  }

  async function createKpiMetric(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics`, { method: "POST", body: payload });
  }

  async function updateKpiMetric(venueId, kpiMetricId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!kpiMetricId) throw new Error("NO_KPI_METRIC");
    return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics/${encodeURIComponent(kpiMetricId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  /**
   * Boots a page: ensures login (cookie), loads /me,
   * optionally enforces an active venue (from LS or query).
   */


  // ------------------------------
  // Payroll: profiles / components / assignments / runs
  // ------------------------------

  async function getPayProfiles(venueId, { includeInactive = false } = {}) {
    if (!venueId) throw new Error("NO_VENUE");
    const q = includeInactive ? "?include_inactive=true" : "";
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles${q}`);
  }

  async function getPayProfile(venueId, profileId) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!profileId) throw new Error("NO_PAY_PROFILE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`);
  }

  async function createPayProfile(venueId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles`, { method: "POST", body: payload });
  }

  async function updatePayProfile(venueId, profileId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!profileId) throw new Error("NO_PAY_PROFILE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function deletePayProfile(venueId, profileId) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!profileId) throw new Error("NO_PAY_PROFILE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    });
  }

  async function createPayProfileAssignment(venueId, profileId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!profileId) throw new Error("NO_PAY_PROFILE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}/assignments`, {
      method: "POST",
      body: payload,
    });
  }

  async function updatePayProfileAssignment(venueId, assignmentId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!assignmentId) throw new Error("NO_ASSIGNMENT");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profile-assignments/${encodeURIComponent(assignmentId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function deletePayProfileAssignment(venueId, assignmentId) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!assignmentId) throw new Error("NO_ASSIGNMENT");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profile-assignments/${encodeURIComponent(assignmentId)}`, {
      method: "DELETE",
    });
  }

  async function createPayComponent(venueId, profileId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!profileId) throw new Error("NO_PAY_PROFILE");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}/components`, {
      method: "POST",
      body: payload,
    });
  }

  async function updatePayComponent(venueId, componentId, payload) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!componentId) throw new Error("NO_COMPONENT");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-components/${encodeURIComponent(componentId)}`, {
      method: "PATCH",
      body: payload,
    });
  }

  async function deletePayComponent(venueId, componentId) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!componentId) throw new Error("NO_COMPONENT");
    return api(`/venues/${encodeURIComponent(venueId)}/pay-components/${encodeURIComponent(componentId)}`, {
      method: "DELETE",
    });
  }

  async function calculatePayroll(venueId, month) {
    if (!venueId) throw new Error("NO_VENUE");
    return api(`/venues/${encodeURIComponent(venueId)}/payroll/calculate`, {
      method: "POST",
      body: { month },
    });
  }

  async function getPayroll(venueId, month) {
    if (!venueId) throw new Error("NO_VENUE");
    if (!month) throw new Error("NO_MONTH");
    return api(`/venues/${encodeURIComponent(venueId)}/payroll?month=${encodeURIComponent(month)}`);
  }

  async function bootPage({ requireVenue = false, silentLogin = true } = {}) {
    await ensureLogin({ silent: silentLogin });

    let me = null;
    try {
      me = await getMe();
    } catch (e) {
      return { ok: false, me: null, error: e };
    }

    let venues = null;
    if (requireVenue) {
      try {
        venues = await getMyVenues();
      } catch {
        venues = [];
      }

      let activeVenueId = getActiveVenueId();
      // If user has exactly one venue and none selected — auto-select
      if (!activeVenueId && Array.isArray(venues) && venues.length === 1) {
        activeVenueId = String(venues[0].id);
        setActiveVenueId(activeVenueId);
      }

      // Still no venue — go to venues picker
      if (!activeVenueId) {
        location.href = "/app-venues.html";
        return { ok: false, me, venues, redirected: true };
      }

      return { ok: true, me, venues, activeVenueId };
    }

    return { ok: true, me };
  }

  return { getActiveVenueId, setActiveVenueId, getMe, getMyVenues, createSelfServiceVenue, getMyVenuePermissions, getVenueMembers, getVenuePositions, getVenuePositionPresets, createVenuePosition, updateVenuePosition, deleteVenuePosition, getVenueSettings, updateVenueSettings, patchInviteDefaultPosition, getDepartments, createDepartment, updateDepartment, getPaymentMethods, createPaymentMethod, updatePaymentMethod, getKpiMetrics, createKpiMetric, updateKpiMetric, getPayProfiles, getPayProfile, createPayProfile, updatePayProfile, deletePayProfile, createPayProfileAssignment, updatePayProfileAssignment, deletePayProfileAssignment, createPayComponent, updatePayComponent, deletePayComponent, calculatePayroll, getPayroll, bootPage };
}
