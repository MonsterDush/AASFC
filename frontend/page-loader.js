(function () {
  if (window.AxelioPageLoader) return;
  const earlyErrors = [];
  const queueEarlyError = (event) => {
    if (earlyErrors.length >= 50) earlyErrors.shift();
    earlyErrors.push({
      type: event.type,
      error: event.error || event.reason || null,
      message:
        event.message || String(event.reason || "Unhandled browser error"),
      filename: event.filename || "",
      lineno: Number(event.lineno || 0),
      colno: Number(event.colno || 0),
    });
  };
  window.__AXELIO_EARLY_ERRORS__ = earlyErrors;
  window.addEventListener("error", queueEarlyError);
  window.addEventListener("unhandledrejection", queueEarlyError);
  window.__AXELIO_RELEASE_EARLY_ERROR_LISTENERS__ = () => {
    window.removeEventListener("error", queueEarlyError);
    window.removeEventListener("unhandledrejection", queueEarlyError);
  };
  const errorTrackingScript = document.createElement("script");
  errorTrackingScript.src =
    "/assets/error-tracking/index.js?v=20260820-assurance1";
  errorTrackingScript.async = true;
  errorTrackingScript.crossOrigin = "anonymous";
  errorTrackingScript.onerror = window.__AXELIO_RELEASE_EARLY_ERROR_LISTENERS__;
  document.head.appendChild(errorTrackingScript);
  const OVERLAY_DELAY_MS = 220;
  const QUIET_WINDOW_MS = 120;
  const HARD_TIMEOUT_MS = 10000;
  const startedAt = performance.now();
  const originalFetch = window.fetch.bind(window);
  let domReady = document.readyState !== "loading";
  let pending = 0;
  let finished = false;
  let overlay = null;
  let observer = null;
  let quietTimer = null;
  let overlayTimer = null;
  let hardTimer = null;
  let lastActivityAt = performance.now();
  document.documentElement.classList.add("page-loading");
  function ensureOverlay() {
    if (finished || overlay || !document.body) return;
    overlay = document.createElement("div");
    overlay.className = "page-loader";
    overlay.setAttribute("data-page-loader", "");
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.innerHTML = `
      <div class="page-loader__panel">
        <div class="page-loader__spinner" aria-hidden="true"></div>
        <div class="page-loader__title">${document.documentElement.lang === "en" ? "Loading page" : "Загружаем страницу"}</div>
        <div class="page-loader__hint">${document.documentElement.lang === "en" ? "Preparing data and available actions" : "Собираем данные и доступные действия"}</div>
      </div>
    `;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay?.classList.add("is-visible"));
  }
  function scheduleCheck(delay = QUIET_WINDOW_MS) {
    if (finished) return;
    if (quietTimer) clearTimeout(quietTimer);
    quietTimer = setTimeout(tryFinish, Math.max(0, delay));
  }
  function noteActivity() {
    if (finished) return;
    lastActivityAt = performance.now();
    scheduleCheck();
  }
  function finish(reason = "ready") {
    if (finished) return;
    finished = true;
    if (quietTimer) clearTimeout(quietTimer);
    if (overlayTimer) clearTimeout(overlayTimer);
    if (hardTimer) clearTimeout(hardTimer);
    observer?.disconnect();
    document.documentElement.classList.remove("page-loading");
    document.documentElement.classList.add("page-loaded");
    overlay?.classList.add("is-leaving");
    setTimeout(() => overlay?.remove(), 260);
    try {
      window.dispatchEvent(
        new CustomEvent("axelio:page-ready", {
          detail: {
            reason,
            duration_ms: Math.round(performance.now() - startedAt),
          },
        }),
      );
    } catch {}
  }
  function tryFinish() {
    if (finished || !domReady || pending > 0) return;
    const quietFor = performance.now() - lastActivityAt;
    if (quietFor < QUIET_WINDOW_MS) {
      scheduleCheck(QUIET_WINDOW_MS - quietFor);
      return;
    }
    finish("ready");
  }
  function settleRequest() {
    pending = Math.max(0, pending - 1);
    noteActivity();
  }
  window.fetch = function (...args) {
    if (finished) return originalFetch(...args);
    pending += 1;
    noteActivity();
    try {
      return Promise.resolve(originalFetch(...args)).finally(settleRequest);
    } catch (error) {
      settleRequest();
      throw error;
    }
  };
  document.addEventListener("click", (event) => {
    const eventTarget = event.target instanceof Element ? event.target : null;
    const button = eventTarget?.closest("button[data-nav-button]");
    if (!(button instanceof HTMLButtonElement)) return;
    if (button.disabled) return;
    const target = button.dataset.href || button.getAttribute("href");
    if (!target || target === "#") return;
    event.preventDefault();
    window.location.assign(String(target));
  });
  function begin() {
    if (finished) return () => {};
    pending += 1;
    noteActivity();
    let settled = false;
    return () => {
      if (settled) return;
      settled = true;
      settleRequest();
    };
  }
  function onDomReady() {
    if (domReady && observer) return;
    domReady = true;
    observer = new MutationObserver((mutations) => {
      const hasPageMutation = mutations.some((mutation) => {
        const target =
          mutation.target instanceof Element
            ? mutation.target
            : mutation.target.parentElement;
        return !target?.closest("[data-page-loader]");
      });
      if (hasPageMutation) noteActivity();
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class", "hidden", "disabled", "aria-hidden"],
    });
    noteActivity();
  }
  window.AxelioPageLoader = {
    begin,
    finish,
    get pending() {
      return pending;
    },
    get ready() {
      return finished;
    },
  };

  overlayTimer = setTimeout(ensureOverlay, OVERLAY_DELAY_MS);
  hardTimer = setTimeout(() => finish("timeout"), HARD_TIMEOUT_MS);
  if (domReady) onDomReady();
  else
    document.addEventListener("DOMContentLoaded", onDomReady, { once: true });
})();
