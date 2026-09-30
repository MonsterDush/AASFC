import assert from "node:assert/strict";

import { openBillingCheckout } from "./billing-checkout.js";

const checkoutUrl = "https://api.axelio.ru/billing/robokassa/pay?InvId=74";

let openedUrl = "";
let assignedUrl = "";
assert.equal(
  await openBillingCheckout(checkoutUrl, {
    telegramWebApp: {
      openLink: (url, options) => {
        openedUrl = url;
        assert.equal(options.try_instant_view, false);
      },
    },
    locationObject: {
      assign: (url) => {
        assignedUrl = url;
      },
    },
  }),
  true,
);
assert.equal(openedUrl, checkoutUrl);
assert.equal(assignedUrl, "");

assignedUrl = "";
assert.equal(
  await openBillingCheckout(checkoutUrl, {
    telegramWebApp: {
      openLink: () => {
        throw new Error("unavailable");
      },
    },
    locationObject: {
      assign: (url) => {
        assignedUrl = url;
      },
    },
  }),
  true,
);
assert.equal(assignedUrl, checkoutUrl);

openedUrl = "";
assert.equal(
  await openBillingCheckout(checkoutUrl, {
    telegramWebApp: null,
    telegramLoader: {
      load: async () => ({
        openLink: (url) => {
          openedUrl = url;
        },
      }),
    },
    locationObject: {
      assign: (url) => {
        assignedUrl = url;
      },
    },
  }),
  true,
);
assert.equal(openedUrl, checkoutUrl);
assert.equal(
  await openBillingCheckout("javascript:alert(1)", { locationObject: {} }),
  false,
);

console.log("Billing checkout contract checks passed.");
