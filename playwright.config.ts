import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const python = existsSync(".venv/Scripts/python.exe")
  ? ".venv\\Scripts\\python.exe"
  : existsSync(".venv/bin/python")
    ? ".venv/bin/python"
    : "python";

// A fresh synthetic workspace per run; the fictitious records API listens on port + 2.
export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  timeout: 180000,
  expect: { timeout: 15000 },
  use: {
    baseURL: "http://127.0.0.1:8805",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    // LETRANIX_VIDEO=1 records the real run; scripts/make_demo_gif.py turns it into docs/assets/demo.gif.
    video:
      process.env.LETRANIX_VIDEO === "1"
        ? { mode: "on", size: { width: 1440, height: 900 } }
        : "off",
  },
  reporter: "list",
  webServer: {
    command: `${python} -m letranix serve --data .runtime/browser-${Date.now()}/workspace --port 8805 --with-destination`,
    url: "http://127.0.0.1:8805/api/health",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
