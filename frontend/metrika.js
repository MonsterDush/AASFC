(function () {
  const COUNTER_ID = 108617620;
  const productionHosts = new Set(["app.axelio.ru"]);
  const enabled = productionHosts.has(String(window.location.hostname || "").toLowerCase());

  window.axelioTrackMetrikaGoal = async function axelioTrackMetrikaGoal() {
    return false;
  };

  if (!enabled) return;

  (function (m, e, t, r, i, k, a) {
    m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
    m[i].l = 1 * new Date();
    for (let j = 0; j < e.scripts.length; j += 1) {
      if (e.scripts[j].src === r) return;
    }
    k = e.createElement(t);
    a = e.getElementsByTagName(t)[0];
    k.async = true;
    k.src = r;
    a.parentNode.insertBefore(k, a);
  })(window, document, "script", `https://mc.yandex.ru/metrika/tag.js?id=${COUNTER_ID}`, "ym");

  window.ym(COUNTER_ID, "init", {
    ssr: true,
    webvisor: true,
    clickmap: true,
    ecommerce: "dataLayer",
    referrer: document.referrer,
    url: window.location.href,
    accurateTrackBounce: true,
    trackLinks: true,
  });

  window.axelioTrackMetrikaGoal = function axelioTrackMetrikaGoal(goalName) {
    const normalizedGoal = String(goalName || "").trim();
    if (!normalizedGoal || typeof window.ym !== "function") return Promise.resolve(false);

    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve(true);
      };

      try {
        window.ym(COUNTER_ID, "reachGoal", normalizedGoal, {}, finish);
      } catch (_error) {
        resolve(false);
        return;
      }
      window.setTimeout(finish, 450);
    });
  };
})();
