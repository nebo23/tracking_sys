// Install the Playwright test browsers into this package's node_modules (never a global cache).
// PLAYWRIGHT_BROWSERS_PATH=0 makes Playwright keep browsers next to its own package.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const cli = fileURLToPath(new URL("../node_modules/playwright/cli.js", import.meta.url));
const result = spawnSync(process.execPath, [cli, "install", "chromium", "firefox"], {
  stdio: "inherit",
  env: { ...process.env, PLAYWRIGHT_BROWSERS_PATH: "0" },
});
process.exit(result.status ?? 1);
