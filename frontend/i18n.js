const STORAGE_KEY = "axelio.lang";
const SUPPORTED_LOCALES = new Set(["ru", "en"]);
const DEFAULT_LOCALE = "ru";
const TRANSLATABLE_ATTRIBUTES = ["placeholder", "title", "aria-label", "alt"];

let catalogPromise = null;
let fragmentCatalogPromise = null;
let observer = null;
let applying = false;
let activeCatalog = null;
let activeFragments = null;
let scheduledTranslation = null;

function normalizeLocale(value) {
  const locale = String(value || "").trim().toLowerCase().split(/[-_]/, 1)[0];
  return SUPPORTED_LOCALES.has(locale) ? locale : DEFAULT_LOCALE;
}

function supportedLocale(value) {
  const locale = String(value || "").trim().toLowerCase().split(/[-_]/, 1)[0];
  return SUPPORTED_LOCALES.has(locale) ? locale : null;
}

function browserLocale() {
  try {
    return normalizeLocale(navigator.languages?.[0] || navigator.language);
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function getLocale() {
  try {
    const requested = new URLSearchParams(location.search).get("lang");
    const requestedLocale = supportedLocale(requested);
    if (requestedLocale) return requestedLocale;
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? normalizeLocale(stored) : browserLocale();
  } catch {
    return browserLocale();
  }
}

export function setLocale(value) {
  const locale = normalizeLocale(value);
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {}
  document.documentElement.lang = locale;
  window.dispatchEvent(new CustomEvent("axelio:locale-changed", { detail: { locale } }));
  return locale;
}

export function localeTag(locale = getLocale()) {
  return normalizeLocale(locale) === "en" ? "en-US" : "ru-RU";
}

export function formatNumber(value, options = {}) {
  return new Intl.NumberFormat(localeTag(), options).format(Number(value || 0));
}

export function formatDate(value, options = {}) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value ?? "");
  return new Intl.DateTimeFormat(localeTag(), options).format(date);
}

export function formatCurrency(value, { currency = "RUB", minor = false, ...options } = {}) {
  const amount = Number(value || 0) / (minor ? 100 : 1);
  return new Intl.NumberFormat(localeTag(), {
    style: "currency",
    currency,
    maximumFractionDigits: currency === "RUB" ? 0 : 2,
    ...options,
  }).format(amount);
}

async function loadCatalog() {
  if (!catalogPromise) {
    catalogPromise = fetch("/locales/en.json?v=20260813-i18n5", { cache: "no-cache" })
      .then((response) => {
        if (!response.ok) throw new Error(`English catalog failed: HTTP ${response.status}`);
        return response.json();
      })
      .catch((error) => {
        console.error(error);
        return {};
      });
  }
  return catalogPromise;
}

export async function translateText(value, { report = true } = {}) {
  const source = String(value ?? "");
  if (getLocale() !== "en" || !/[А-Яа-яЁё]/.test(source)) return source;
  const catalog = await loadCatalog();
  const fragments = await loadFragmentCatalog();
  const translated = translateValue(source, catalog, fragments, "runtime");
  if (!report && translated === source) return source;
  return translated;
}

async function loadFragmentCatalog() {
  if (!fragmentCatalogPromise) {
    fragmentCatalogPromise = loadCatalog().then((catalog) => Object.entries(catalog)
      .filter(([source, translated]) => source.length >= 4 && source !== translated && /[А-Яа-яЁё]/.test(source))
      .sort(([left], [right]) => right.length - left.length));
  }
  return fragmentCatalogPromise;
}

function splitWhitespace(value) {
  const source = String(value ?? "");
  const leading = source.match(/^\s*/)?.[0] || "";
  const trailing = source.match(/\s*$/)?.[0] || "";
  return { leading, text: source.slice(leading.length, source.length - trailing.length), trailing };
}

function reportMissing(value, context = "text") {
  if (!value || !/[А-Яа-яЁё]/.test(value)) return;
  window.__AXELIO_I18N_MISSING__ ||= new Map();
  const missing = window.__AXELIO_I18N_MISSING__;
  if (!missing.has(value)) missing.set(value, new Set());
  missing.get(value).add(context);
  if (localStorage.getItem("axelio.i18n.debug") === "1") {
    console.warn(`[i18n] missing ${context}:`, value);
  }
}

function hasWordBoundary(value, start, length) {
  const before = value[start - 1] || "";
  const after = value[start + length] || "";
  return !/[А-Яа-яЁё]/.test(before) && !/[А-Яа-яЁё]/.test(after);
}

function translateFragments(value, fragments) {
  let translated = value;
  for (const [source, replacement] of fragments) {
    let index = translated.indexOf(source);
    while (index >= 0) {
      if (hasWordBoundary(translated, index, source.length)) {
        translated = `${translated.slice(0, index)}${replacement}${translated.slice(index + source.length)}`;
        index = translated.indexOf(source, index + replacement.length);
      } else {
        index = translated.indexOf(source, index + source.length);
      }
    }
    if (!/[А-Яа-яЁё]/.test(translated)) break;
  }
  return translated;
}

function translateNow(value) {
  const source = String(value ?? "");
  if (getLocale() !== "en" || !/[А-Яа-яЁё]/.test(source) || !activeCatalog || !activeFragments) return source;
  return translateValue(source, activeCatalog, activeFragments, "dialog");
}

function translateValue(value, catalog, fragments, context) {
  const { leading, text, trailing } = splitWhitespace(value);
  if (!text) return value;
  const translated = catalog[text];
  if (typeof translated === "string" && translated) return `${leading}${translated}${trailing}`;
  const fragmentTranslation = translateFragments(text, fragments);
  if (fragmentTranslation !== text) {
    if (/[А-Яа-яЁё]/.test(fragmentTranslation)) reportMissing(fragmentTranslation, context);
    return `${leading}${fragmentTranslation}${trailing}`;
  }
  reportMissing(text, context);
  return value;
}

function translateElement(element, catalog, fragments) {
  if (!(element instanceof Element) || element.closest("[data-i18n-ignore]")) return;

  for (const attribute of TRANSLATABLE_ATTRIBUTES) {
    if (!element.hasAttribute(attribute)) continue;
    const current = element.getAttribute(attribute) || "";
    element.__axelioI18nAttributes ||= {};
    const previous = element.__axelioI18nAttributes[attribute];
    const source = !previous || current !== previous.translated ? current : previous.source;
    const translated = translateValue(source, catalog, fragments, attribute);
    element.__axelioI18nAttributes[attribute] = { source, translated };
    if (translated !== current) element.setAttribute(attribute, translated);
  }

  for (const node of element.childNodes) {
    if (node.nodeType !== Node.TEXT_NODE) continue;
    const current = node.nodeValue || "";
    if (!node.__axelioI18nState || current !== node.__axelioI18nState.translated) {
      node.__axelioI18nState = { source: current, translated: current };
    }
    const translated = translateValue(
      node.__axelioI18nState.source,
      catalog,
      fragments,
      element.tagName.toLowerCase(),
    );
    node.__axelioI18nState.translated = translated;
    if (translated !== current) node.nodeValue = translated;
  }
}

async function translateTree(root = document) {
  if (getLocale() !== "en" || applying) return;
  applying = true;
  try {
    const catalog = await loadCatalog();
    const fragments = await loadFragmentCatalog();
    activeCatalog = catalog;
    activeFragments = fragments;
    if (root instanceof Element) translateElement(root, catalog, fragments);
    for (const element of root.querySelectorAll?.("*") || []) translateElement(element, catalog, fragments);
  } finally {
    applying = false;
  }
}

export async function applyLocale(root = document) {
  const locale = getLocale();
  document.documentElement.lang = locale;
  if (locale === "en") await translateTree(root);
  return locale;
}

export function observeLocale() {
  if (observer || typeof MutationObserver === "undefined") return;
  observer = new MutationObserver((mutations) => {
    if (getLocale() !== "en") return;
    if (applying) {
      clearTimeout(scheduledTranslation);
      scheduledTranslation = window.setTimeout(() => void translateTree(document), 0);
      return;
    }
    for (const mutation of mutations) {
      if (mutation.type === "characterData") {
        const parent = mutation.target.parentElement;
        if (parent) void translateTree(parent);
        continue;
      }
      if (mutation.type === "attributes") {
        void translateTree(mutation.target);
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node instanceof Element) {
          void translateTree(node);
        } else if (node.nodeType === Node.TEXT_NODE && node.parentElement) {
          void translateTree(node.parentElement);
        }
      }
    }
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: TRANSLATABLE_ATTRIBUTES,
  });
}

function installDialogTranslations() {
  if (window.__axelioI18nDialogsInstalled) return;
  window.__axelioI18nDialogsInstalled = true;
  const originalAlert = window.alert.bind(window);
  const originalConfirm = window.confirm.bind(window);
  const originalPrompt = window.prompt.bind(window);
  window.alert = (message) => originalAlert(translateNow(message));
  window.confirm = (message) => originalConfirm(translateNow(message));
  window.prompt = (message, defaultValue) => originalPrompt(translateNow(message), defaultValue);
}

function addLegalTranslationNotice() {
  if (getLocale() !== "en") return;
  const page = location.pathname.split("/").pop();
  if (!["axelio-offer.html", "axelio-privacy.html", "axelio-subscription.html"].includes(page)) return;
  if (document.querySelector("[data-legal-translation-notice]")) return;
  const main = document.querySelector("main, .legal-page, .container");
  if (!main) return;
  const notice = document.createElement("div");
  notice.dataset.legalTranslationNotice = "true";
  notice.className = "card section-card mt-12";
  notice.setAttribute("role", "note");
  notice.textContent = "This English translation is provided for convenience. If interpretations differ, the Russian version governs.";
  main.prepend(notice);
}

export async function initializeI18n() {
  setLocale(getLocale());
  await applyLocale(document);
  installDialogTranslations();
  addLegalTranslationNotice();
  observeLocale();
  window.setTimeout(() => void translateTree(document), 0);
  window.setTimeout(() => void translateTree(document), 250);
}

window.AxelioI18n = {
  getLocale,
  setLocale,
  applyLocale,
  formatNumber,
  formatDate,
  formatCurrency,
  localeTag,
  translateText,
};
