import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export default function cleanup() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const python = process.env.TEST_PYTHON || path.join(root, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  execFileSync(python, [
    "-m", "integration_tests.cleanup", process.env.ACC_BROWSER_DATABASE, process.env.ACC_TEST_RUN_ID,
  ], { cwd: path.join(root, "backend"), env: process.env, stdio: "inherit", timeout: 20000 });
}
