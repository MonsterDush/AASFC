export function createUiPreferences() {
  const LS_LANG = "axelio.lang";
  const LS_THEME = "axelio.theme";
  const LS_SYS_ROLE = "axelio.system_role";
  const DICT = {
    ru: {
      venue: "Заведение",
      manage_venues: "Управление заведениями",
      leave_venue: "Выйти из заведения",
      settings: "Настройки",
      more: "Ещё",
      adjustments: "Штрафы",
      shifts: "График",
      salary: "Зарплаты",
      report: "Отчёты",
      finance: "Финансы",
      overview: "Обзор",
      revenue: "Выручка",
      summary: "Сводка",
      expenses: "Расходы",
      admin_venues: "Заведения",
      admin_invites: "Инвайты",
    },
    en: {
      venue: "Venue",
      manage_venues: "Manage venues",
      leave_venue: "Leave venue",
      settings: "Settings",
      more: "More",
      adjustments: "Adjustments",
      shifts: "Schedule",
      salary: "Salary",
      report: "Reports",
      finance: "Finance",
      overview: "Overview",
      revenue: "Revenue",
      summary: "Summary",
      expenses: "Expenses",
      admin_venues: "Venues",
      admin_invites: "Invites",
    },
  };

  function getLang() {
    try {
      if (window.AxelioI18n?.getLocale) return window.AxelioI18n.getLocale();
      const stored = localStorage.getItem(LS_LANG);
      const detected = String(stored || navigator.languages?.[0] || navigator.language || "ru").toLowerCase();
      return detected.startsWith("en") ? "en" : "ru";
    } catch {
      return "ru";
    }
  }

  function setLang(lang) {
    const normalized = lang === "en" ? "en" : "ru";
    if (window.AxelioI18n?.setLocale) return window.AxelioI18n.setLocale(normalized);
    try { localStorage.setItem(LS_LANG, normalized); } catch {}
    document.documentElement.lang = normalized;
    return normalized;
  }

  function t(key) {
    const lang = getLang();
    return (DICT[lang] && DICT[lang][key]) || (DICT.ru && DICT.ru[key]) || key;
  }

  function wa() {
    return window.Telegram?.WebApp || null;
  }

  function looksLikeTelegramWebApp() {
    try {
      if (wa()) return true;
      if (typeof window.TelegramWebviewProxy !== "undefined") return true;
      if (typeof window.TelegramGameProxy !== "undefined") return true;
      const raw = `${location.search || ""}&${location.hash || ""}`;
      if (/tgWebApp(Data|Version|Platform|ThemeParams|StartParam|BotInline)/i.test(raw)) return true;
      const ua = String(navigator.userAgent || "");
      if (/Telegram/i.test(ua)) return true;
    } catch {}
    return false;
  }

  async function ensureTelegramWebAppLoaded({ timeoutMs = 2500 } = {}) {
    if (wa()) return wa();
    try {
      const loader = window.AxelioTelegramLoader;
      if (loader && typeof loader.load === "function") {
        return await loader.load({ timeoutMs });
      }
    } catch {}

    if (!looksLikeTelegramWebApp()) return null;

    return await new Promise((resolve) => {
      let settled = false;
      let timer = null;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        resolve(value || wa() || null);
      };
      const existing = document.querySelector('script[data-axelio-telegram="external"]');
      if (existing) {
        const poll = () => {
          if (wa()) return finish(wa());
          if (!settled) setTimeout(poll, 60);
        };
        poll();
      } else {
        const script = document.createElement("script");
        script.async = true;
        script.src = "https://telegram.org/js/telegram-web-app.js";
        script.setAttribute("data-axelio-telegram", "external");
        script.onload = () => finish(wa());
        script.onerror = () => finish(null);
        document.head.appendChild(script);
      }
      timer = setTimeout(() => finish(null), Math.max(300, Number(timeoutMs) || 2500));
    });
  }

  function cacheSystemRole(role) {
    const value = String(role || "").toUpperCase();
    try {
      if (value) localStorage.setItem(LS_SYS_ROLE, value);
      else localStorage.removeItem(LS_SYS_ROLE);
    } catch {}
  }

  function getCachedSystemRole() {
    try { return String(localStorage.getItem(LS_SYS_ROLE) || "").toUpperCase(); } catch { return ""; }
  }

  function isSuperAdminCached() {
    return getCachedSystemRole() === "SUPER_ADMIN";
  }

  function getThemePref() {
    try {
      const value = (localStorage.getItem(LS_THEME) || "system").trim();
      const allowed = ["light", "dark", "system", "hookahplace"].includes(value);
      if (!allowed || (value === "hookahplace" && !isSuperAdminCached())) return "system";
      return value;
    } catch {
      return "system";
    }
  }

  function setThemePref(pref) {
    let value = ["light", "dark", "system", "hookahplace"].includes(pref) ? pref : "system";
    if (value === "hookahplace" && !isSuperAdminCached()) value = "system";
    try { localStorage.setItem(LS_THEME, value); } catch {}
  }

  function ensureThemeMeta() {
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      document.head.appendChild(meta);
    }
    return meta;
  }

  function syncThemeColorMeta() {
    try {
      const meta = ensureThemeMeta();
      const background = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
      if (background) meta.setAttribute("content", background);
    } catch {}
  }

  function applyTheme() {
    const pref = getThemePref();
    const root = document.documentElement;
    if (["light", "dark", "hookahplace"].includes(pref)) root.setAttribute("data-theme", pref);
    else root.removeAttribute("data-theme");
    requestAnimationFrame(syncThemeColorMeta);

    try {
      if (!root.__themeMqlBound) {
        const media = window.matchMedia?.("(prefers-color-scheme: dark)");
        if (media && typeof media.addEventListener === "function") {
          media.addEventListener("change", () => {
            if (getThemePref() === "system") requestAnimationFrame(syncThemeColorMeta);
          });
        }
        root.__themeMqlBound = true;
      }
    } catch {}
  }

  function applyTelegramTheme() {
    applyTheme();
    const webApp = wa();
    const userPill = document.querySelector("[data-userpill]");
    if (!webApp) {
      if (userPill) userPill.textContent = "не в Telegram";
      if (looksLikeTelegramWebApp()) {
        ensureTelegramWebAppLoaded({ timeoutMs: 1800 }).then((loaded) => {
          if (loaded) applyTelegramTheme();
        }).catch(() => {});
      }
      return;
    }

    webApp.ready();
    const user = webApp.initDataUnsafe?.user;
    if (userPill) userPill.textContent = user ? `@${user.username || "без_username"}` : "неизвестно";
  }

  return {
    getLang,
    setLang,
    t,
    wa,
    looksLikeTelegramWebApp,
    ensureTelegramWebAppLoaded,
    cacheSystemRole,
    getCachedSystemRole,
    isSuperAdminCached,
    getThemePref,
    setThemePref,
    applyTheme,
    applyTelegramTheme,
  };
}
