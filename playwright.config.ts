import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const python = existsSync(".venv/Scripts/python.exe")
  ? ".venv\\Scripts\\python.exe"
  : "python";
export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  timeout: 90000,
  use: { baseURL: "http://127.0.0.1:8796", trace: "retain-on-failure" },
  reporter: "list",
  webServer: {
    command: `${python} -m letranix serve --data .runtime/browser-${Date.now()} --port 8796`,
    url: "http://127.0.0.1:8796/api/health",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
