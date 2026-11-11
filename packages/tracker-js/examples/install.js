// Initializer of the installation example (specification 005). It is a same-origin module, so
// the page's Content Security Policy needs no 'unsafe-inline' or nonce. Synthetic values only:
// replace the collector origin, public source key and form definition with the values
// registered for your client. Nothing is collected until the visitor makes an explicit choice.

import { createTracker } from "/assets/tracker-0.5.3/tracker.js";

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

// Your consent platform decides whether the visitor already chose; this example keeps its own
// decision record for the session only. Session storage may be blocked or full: the record
// then lives in memory for this page, and a storage failure never stops a consent action.
const CHOICE_KEY = "example-consent-choice";
let rememberedChoice; // set once this page records a choice

function readChoice() {
  if (rememberedChoice !== undefined) return rememberedChoice;
  try {
    return window.sessionStorage.getItem(CHOICE_KEY);
  } catch {
    return null;
  }
}

function recordChoice(value) {
  rememberedChoice = value;
  try {
    if (value === null) window.sessionStorage.removeItem(CHOICE_KEY);
    else window.sessionStorage.setItem(CHOICE_KEY, value);
  } catch {
    // Persistence is optional; the in-memory record above serves this page.
  }
}

const banner = document.getElementById("consent-banner");
const decided = readChoice();
if (decided === "granted") {
  tracker.resume({ [ANALYTICS]: "granted" }).then((result) => {
    if (result.status === "resumed") tracker.trackPageView();
    else banner.hidden = false; // unknown, withdrawn or expired: ask again
  });
} else if (decided === null) {
  banner.hidden = false;
}

// Each handler calls the tracker before recording the choice.
document.getElementById("accept").addEventListener("click", async () => {
  banner.hidden = true;
  const granting = tracker.grant({ [ANALYTICS]: "granted" });
  recordChoice("granted");
  const result = await granting;
  if (result.status === "granted") tracker.trackPageView();
});
document.getElementById("reject").addEventListener("click", () => {
  banner.hidden = true;
  recordChoice("denied");
});
document.getElementById("withdraw").addEventListener("click", () => {
  tracker.withdraw();
  recordChoice("denied");
});
document.getElementById("erase").addEventListener("click", () => {
  tracker.erase();
  recordChoice(null);
});
