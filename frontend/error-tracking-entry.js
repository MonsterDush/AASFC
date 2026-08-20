import * as Sentry from "@sentry/browser";

const CONFIG_URL = "/runtime-config.json";
const REDACTED_KEYS = new Set([
  "authorization",
  "cookie",
  "password",
  "phone",
  "secret",
  "token",
]);

function scrub(value, depth = 0) {
  if (depth > 5) return "[truncated]";
  if (Array.isArray(value))
    return value.slice(0, 50).map((item) => scrub(item, depth + 1));
  if (!value || typeof value !== "object") return value;
  const sanitized = {};
  for (const [key, item] of Object.entries(value)) {
    sanitized[key] = REDACTED_KEYS.has(key.toLowerCase())
      ? "[filtered]"
      : scrub(item, depth + 1);
  }
  return sanitized;
}

function safeSampleRate(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number >= 0 && number <= 1 ? number : 0;
}

async function loadRuntimeConfig() {
  const response = await fetch(CONFIG_URL, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new Error(`runtime config returned ${response.status}`);
  return response.json();
}

function captureQueuedErrors() {
  const queue = Array.isArray(window.__AXELIO_EARLY_ERRORS__)
    ? window.__AXELIO_EARLY_ERRORS__
    : [];
  for (const item of queue.splice(0)) {
    if (item.error instanceof Error) {
      Sentry.captureException(item.error);
    } else {
      Sentry.captureMessage(String(item.message || "Unhandled browser error"), {
        level: "error",
        extra: scrub(item),
      });
    }
  }
  window.__AXELIO_RELEASE_EARLY_ERROR_LISTENERS__?.();
}

async function initializeErrorTracking() {
  try {
    const config = await loadRuntimeConfig();
    const dsn = String(config.sentryBrowserDsn || "").trim();
    if (dsn) {
      Sentry.init({
        dsn,
        release: `axelio@${String(config.release || "local")}`,
        environment: String(config.environment || "development"),
        tracesSampleRate: safeSampleRate(config.sentryBrowserTracesSampleRate),
        sendDefaultPii: false,
        beforeSend(event) {
          const sanitized = scrub(event);
          if (sanitized.request) {
            delete sanitized.request.cookies;
            delete sanitized.request.data;
          }
          if (sanitized.user) delete sanitized.user;
          return sanitized;
        },
      });
      window.AxelioErrorTracking = Object.freeze({
        captureException: (error, context) =>
          Sentry.captureException(error, scrub(context)),
        captureMessage: (message, context) =>
          Sentry.captureMessage(String(message), scrub(context)),
        enabled: true,
      });
      captureQueuedErrors();
      return;
    }
    window.__AXELIO_RELEASE_EARLY_ERROR_LISTENERS__?.();
    window.AxelioErrorTracking = Object.freeze({ enabled: false });
  } catch {
    window.__AXELIO_RELEASE_EARLY_ERROR_LISTENERS__?.();
    window.AxelioErrorTracking = Object.freeze({ enabled: false });
  }
}

void initializeErrorTracking();
