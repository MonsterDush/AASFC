import assert from "node:assert/strict";

function installBrowser({ hostname = "app.axelio.ru", href = "https://app.axelio.ru/owner-summary.html" } = {}) {
  const scripts = [];
  globalThis.window = {
    location: {
      hostname,
      href,
      pathname: new URL(href).pathname,
    },
  };
  globalThis.document = {
    title: "Axelio DEMO",
    referrer: "https://axelio.ru/",
    head: {
      appendChild(script) {
        scripts.push(script);
      },
    },
    createElement(tagName) {
      return {
        tagName,
        attributes: {},
        setAttribute(name, value) {
          this.attributes[name] = String(value);
        },
      };
    },
    querySelector(selector) {
      if (selector !== "script[data-axelio-demo-metrika]") return null;
      return scripts.find((script) => script.attributes["data-axelio-demo-metrika"] === "true") || null;
    },
  };
  return { scripts };
}

function queuedCommands() {
  return Array.from(window.ym?.a || [], (args) => Array.from(args));
}

async function loadScenario(name) {
  return import(`./app/demo-metrika.js?check=${encodeURIComponent(name)}`);
}

{
  const { scripts } = installBrowser({ hostname: "localhost", href: "http://localhost:8765/owner-summary.html" });
  const metrika = await loadScenario("local-host");
  assert.equal(metrika.enableDemoMetrika({ demo_mode: true }), false);
  assert.equal(scripts.length, 0);
  assert.equal(window.ym, undefined);
}

{
  const { scripts } = installBrowser();
  const metrika = await loadScenario("non-demo");
  assert.equal(metrika.enableDemoMetrika({ demo_mode: false }), false);
  assert.equal(scripts.length, 0);
  assert.equal(window.ym, undefined);
}

{
  const { scripts } = installBrowser();
  const metrika = await loadScenario("demo");
  const state = { demo_mode: true, demo_persona: "owner" };

  assert.equal(metrika.enableDemoMetrika(state), true);
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].src, "https://mc.yandex.ru/metrika/tag.js?id=108617620");
  assert.equal(queuedCommands().filter((command) => command[1] === "init").length, 1);
  assert.equal(queuedCommands().filter((command) => command[1] === "hit").length, 1);

  assert.equal(metrika.enableDemoMetrika(state), true);
  assert.equal(scripts.length, 1);
  assert.equal(queuedCommands().filter((command) => command[1] === "init").length, 1);
  assert.equal(queuedCommands().filter((command) => command[1] === "hit").length, 1);

  assert.equal(metrika.trackDemoMetrikaEvent("cta_click", {
    persona: "owner",
    page_path: "/owner-summary.html",
    cta_code: "primary",
  }), true);
  assert.equal(queuedCommands().filter((command) => command[1] === "params").length, 1);
  assert.equal(queuedCommands().filter((command) => command[1] === "reachGoal")[0][2], "demo_cta_click");

  assert.equal(metrika.disableDemoMetrika(), true);
  assert.equal(queuedCommands().at(-1)[1], "destruct");
  assert.equal(metrika.getDemoMetrikaStatus().initialized, false);
}

console.log("demo metrika: production DEMO-only lifecycle verified");
