const METRIKA_ID = 108617620;
const PRODUCTION_HOSTS = new Set(["app.axelio.ru"]);
const SCRIPT_MARKER = "data-axelio-demo-metrika";

let initialized = false;
let lastHitUrl = "";

function isProductionHost() {
  return PRODUCTION_HOSTS.has(String(window.location?.hostname || "").toLowerCase());
}

function isDemoState(state) {
  return state?.demo_mode === true;
}

function currentUrl() {
  return String(window.location?.href || "");
}

function demoParams(state = null) {
  return {
    axelio_mode: "demo",
    axelio_demo_persona: String(state?.demo_persona || "UNKNOWN").toUpperCase(),
  };
}

function loadMetrikaLibrary() {
  if (typeof window.ym !== "function") {
    window.ym = function () {
      (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.l = 1 * new Date();
  }

  if (document.querySelector(`script[${SCRIPT_MARKER}]`)) return;

  const script = document.createElement("script");
  script.async = true;
  script.src = `https://mc.yandex.ru/metrika/tag.js?id=${METRIKA_ID}`;
  script.setAttribute(SCRIPT_MARKER, "true");
  document.head.appendChild(script);
}

export function enableDemoMetrika(state) {
  if (!isProductionHost() || !isDemoState(state)) return false;

  loadMetrikaLibrary();

  if (!initialized) {
    window.ym(METRIKA_ID, "init", {
      defer: true,
      triggerEvent: true,
      clickmap: true,
      trackLinks: true,
      accurateTrackBounce: true,
      webvisor: true,
      params: demoParams(state),
    });
    initialized = true;
  }

  const url = currentUrl();
  if (url && url !== lastHitUrl) {
    window.ym(METRIKA_ID, "hit", url, {
      title: String(document.title || "Axelio DEMO"),
      referer: String(document.referrer || ""),
      params: demoParams(state),
    });
    lastHitUrl = url;
  }

  return true;
}

export function trackDemoMetrikaEvent(eventName, payload = {}) {
  if (!initialized || typeof window.ym !== "function") return false;
  const normalizedEvent = String(eventName || "").trim().toLowerCase();
  if (!normalizedEvent) return false;

  const parameters = {
    event_name: normalizedEvent,
    persona: String(payload.persona || "UNKNOWN").toUpperCase(),
    page_path: String(payload.page_path || window.location?.pathname || ""),
    cta_code: payload.cta_code ? String(payload.cta_code) : undefined,
  };
  window.ym(METRIKA_ID, "params", { axelio_demo_event: parameters });
  window.ym(METRIKA_ID, "reachGoal", `demo_${normalizedEvent}`, parameters);
  return true;
}

export function disableDemoMetrika() {
  if (!initialized || typeof window.ym !== "function") return false;

  window.ym(METRIKA_ID, "destruct");
  initialized = false;
  lastHitUrl = "";
  return true;
}

export function getDemoMetrikaStatus() {
  return {
    counterId: METRIKA_ID,
    productionHost: isProductionHost(),
    initialized,
    lastHitUrl,
  };
}
