export async function openBillingCheckout(checkoutUrl, options = {}) {
  const target = String(checkoutUrl || "").trim();
  if (!/^https?:\/\//i.test(target)) return false;

  let telegramWebApp =
    options.telegramWebApp !== undefined
      ? options.telegramWebApp
      : globalThis.window?.Telegram?.WebApp;
  const telegramLoader =
    options.telegramLoader ?? globalThis.window?.AxelioTelegramLoader;
  if (!telegramWebApp && typeof telegramLoader?.load === "function") {
    try {
      telegramWebApp = await telegramLoader.load({ timeoutMs: 500 });
    } catch {}
  }
  try {
    if (typeof telegramWebApp?.openLink === "function") {
      telegramWebApp.openLink(target, { try_instant_view: false });
      return true;
    }
  } catch {}

  const locationObject = options.locationObject ?? globalThis.window?.location;
  if (typeof locationObject?.assign === "function")
    locationObject.assign(target);
  else if (locationObject) locationObject.href = target;
  else return false;
  return true;
}
