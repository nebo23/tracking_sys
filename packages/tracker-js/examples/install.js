// Initializer of the installation example (specification 005). It is a same-origin module, so
// the page's Content Security Policy needs no 'unsafe-inline' or nonce. Synthetic values only:
// replace the collector origin, public source key and form definition with the values
// registered for your client. Nothing is collected until the visitor makes an explicit choice.

import { createTracker } from "/assets/tracker-0.5.1/tracker.js";

const ANALYTICS = "analytics.first_party";
const tracker = createTracker({
  collector: "https://collect.example.test",
  publicKey: "pk_SYNTHETICSYNTHETICSYNTHETICSYNTHETICSYNTHET",
  forms: {
    lead: {
      fields: [
        { name: "plan", data_class: "form.option", options: ["basic", "pro"] },
        { name: "quantity", data_class: "form.quantity" },
      ],
    },
  },
  bindings: { links: "a[data-track]", forms: { lead: "#lead-form" } },
});

// Your consent platform decides whether the visitor already chose; this example keeps
// its own decision record for the session only.
const banner = document.getElementById("consent-banner");
const decided = sessionStorage.getItem("example-consent-choice");
if (decided === "granted") {
  tracker.resume({ [ANALYTICS]: "granted" }).then((result) => {
    if (result.status === "resumed") tracker.trackPageView();
    else banner.hidden = false; // unknown, withdrawn or expired: ask again
  });
} else if (decided === null) {
  banner.hidden = false;
}

document.getElementById("accept").addEventListener("click", async () => {
  banner.hidden = true;
  sessionStorage.setItem("example-consent-choice", "granted");
  const result = await tracker.grant({ [ANALYTICS]: "granted" });
  if (result.status === "granted") tracker.trackPageView();
});
document.getElementById("reject").addEventListener("click", () => {
  banner.hidden = true;
  sessionStorage.setItem("example-consent-choice", "denied");
});
document.getElementById("withdraw").addEventListener("click", () => {
  sessionStorage.setItem("example-consent-choice", "denied");
  tracker.withdraw();
});
document.getElementById("erase").addEventListener("click", () => {
  sessionStorage.removeItem("example-consent-choice");
  tracker.erase();
});
