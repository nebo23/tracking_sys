// Sends real tracker envelopes from a landing page with extra, prohibited URL content, so the
// backend test can compare the stored payloads with exactly what the browser transmitted
// (specification 005, M2). Driven by backend/tests/integration/test_tracker_journey.py.
// Usage: node parity-page.js '<json options>'.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= "0";
const { chromium } = await import("playwright");

const options = JSON.parse(process.argv[2]);
const SOURCE = fileURLToPath(new URL("../../src/", import.meta.url));
const config = { collector: options.collector, publicKey: options.publicKey, forms: options.forms };
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Offer</title></head>
<body><form id="lead"><select name="plan"><option value="pro" selected>Pro</option></select>
<input name="coupon" value="SPRING-26"><input name="qty" type="number" value="4"></form>
<script type="module">
  import { createTracker } from "/src/tracker.js";
  window.tracker = createTracker(${JSON.stringify(config)});
  window.__ready = true;
</script></body></html>`;

const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (/^\/src\/[a-z]+\.js$/.test(url.pathname)) {
    response.writeHead(200, { "Content-Type": "text/javascript" });
    response.end(await readFile(SOURCE + url.pathname.slice(5)));
    return;
  }
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(html);
});
await new Promise((resolve) => server.listen(options.port, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
const report = { envelopes: [] };
try {
  const page = await browser.newPage();
  page.on("request", (request) => {
    if (request.url().endsWith("/events")) report.envelopes.push(request.postData());
  });
  await page.goto(options.url);
  await page.goto(page.url() + options.suffix);
  await page.waitForFunction(() => window.__ready === true);
  const granted = await page.evaluate(() => window.tracker.grant({ "analytics.first_party": "granted" }));
  if (granted.status !== "granted") throw new Error(`grant ${granted.status}`);
  const done = page.waitForResponse((response) => response.url().endsWith("/events"));
  await page.evaluate(() => window.tracker.trackPageView());
  await done;
  const second = page.waitForResponse((response) => response.url().endsWith("/events"));
  await page.evaluate(() => window.tracker.trackForm("lead", document.getElementById("lead")));
  await second;
} catch (error) {
  report.failure = String(error?.stack ?? error);
} finally {
  await browser.close();
  server.close();
}
process.stdout.write(JSON.stringify(report));
