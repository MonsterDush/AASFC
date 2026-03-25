(function () {
  const SCRIPT_SRC = "https://telegram.org/js/telegram-web-app.js";
  const DEFAULT_TIMEOUT_MS = 2500;

  function hasTelegram() {
    return !!(window.Telegram && window.Telegram.WebApp);
  }

  function urlHasTelegramHints() {
    try {
      const raw = `${location.search || ""}&${location.hash || ""}`;
      return /tgWebApp(Data|Version|Platform|ThemeParams|StartParam|BotInline)/i.test(raw);
    } catch {
      return false;
    }
  }

  function looksLikeTelegramWebApp() {
    try {
      if (hasTelegram()) return true;
      if (typeof window.TelegramWebviewProxy !== "undefined") return true;
      if (typeof window.TelegramGameProxy !== "undefined") return true;
      if (urlHasTelegramHints()) return true;
      const ua = String(navigator.userAgent || "");
      if (/Telegram/i.test(ua)) return true;
    } catch {}
    return false;
  }

  function finish(resolve, value) {
    try {
      if (value) {
        window.dispatchEvent(new CustomEvent("axelio:telegram-ready", { detail: { ok: true } }));
      }
    } catch {}
    resolve(value || (hasTelegram() ? window.Telegram.WebApp : null));
  }

  function load(options) {
    const timeoutMs = Math.max(300, Number(options && options.timeoutMs) || DEFAULT_TIMEOUT_MS);

    if (hasTelegram()) return Promise.resolve(window.Telegram.WebApp);
    if (!looksLikeTelegramWebApp()) return Promise.resolve(null);
    if (window.__axelioTelegramLoadPromise) return window.__axelioTelegramLoadPromise;

    window.__axelioTelegramLoadPromise = new Promise((resolve) => {
      let settled = false;
      let timer = null;
      const done = (value) => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        finish(resolve, value);
      };

      const existing = document.querySelector('script[data-axelio-telegram="external"]');
      if (existing) {
        timer = setTimeout(() => done(null), timeoutMs);
        const poll = () => {
          if (hasTelegram()) return done(window.Telegram.WebApp);
          if (!settled) setTimeout(poll, 60);
        };
        poll();
        return;
      }

      const script = document.createElement('script');
      script.async = true;
      script.src = SCRIPT_SRC;
      script.setAttribute('data-axelio-telegram', 'external');
      script.onload = () => done(window.Telegram?.WebApp || null);
      script.onerror = () => done(null);
      timer = setTimeout(() => done(null), timeoutMs);
      document.head.appendChild(script);
    });

    return window.__axelioTelegramLoadPromise;
  }

  window.AxelioTelegramLoader = {
    load,
    hasTelegram,
    looksLikeTelegramWebApp,
  };

  // Non-blocking warmup only when page already looks like a Telegram WebApp.
  setTimeout(() => {
    load({ timeoutMs: DEFAULT_TIMEOUT_MS }).catch(() => {});
  }, 0);
})();
