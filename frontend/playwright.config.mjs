import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const frontend = path.dirname(fileURLToPath(import.meta.url));
const repository = path.dirname(frontend);
const python = process.env.TEST_PYTHON || path.join(repository, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const database = process.env.ACC_BROWSER_DATABASE || `acc_test_browser_${Date.now()}_${Math.random().toString(16).slice(2)}`;
const runId = process.env.ACC_TEST_RUN_ID || randomUUID().replaceAll("-", "");
process.env.ACC_BROWSER_DATABASE = database;
process.env.ACC_TEST_RUN_ID = runId;

export default defineConfig({
  testDir: "./e2e",
  globalTeardown: "./e2e/cleanup.mjs",
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 15000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results/browser",
  use: {
    baseURL: "http://127.0.0.1:5181",
    browserName: "chromium",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn integration_tests.server:app --host 127.0.0.1 --port 8001`,
      cwd: path.join(repository, "backend"),
      env: { MONGO_DB_NAME: database, ACC_TEST_RUN_ID: runId, PYTHONUNBUFFERED: "1" },
      url: "http://127.0.0.1:8001/",
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      command: "npm.cmd run dev -- --host 127.0.0.1 --port 5181 --strictPort",
      cwd: frontend,
      env: { VITE_API_BASE_URL: "http://127.0.0.1:8001" },
      url: "http://127.0.0.1:5181",
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
