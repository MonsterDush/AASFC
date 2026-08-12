const METRIKA_ID = 108617620;

let initialized = false;

function loadMetrikaLibrary() {
  if (window.ym) return;

  window.ym = function () {
    (window.ym.a = window.ym.a || []).push(arguments);
  };
  window.ym.l = 1 * new Date();

  const script = document.createElement("script");
  script.async = true;
  script.src = "https://mc.yandex.ru/metrika/tag.js";
  document.head.appendChild(script);
}

export function enableDemoMetrika() {
  if (initialized) return;

  loadMetrikaLibrary();

  window.ym(METRIKA_ID, "init", {
    clickmap: true,
    trackLinks: true,
    accurateTrackBounce: true,
    webvisor: true,
  });

  initialized = true;
}

export function disableDemoMetrika() {
  if (!initialized || !window.ym) return;

  window.ym(METRIKA_ID, "destruct");
  initialized = false;
}