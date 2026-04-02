const { execSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const backendDir = path.resolve(__dirname, "backend");
const venvBin = process.platform === "win32"
  ? path.join(backendDir, "venv", "Scripts", "python.exe")
  : path.join(backendDir, "venv", "bin", "python3");

if (!fs.existsSync(venvBin)) {
  console.error(`[!] Python venv not found at: ${venvBin}`);
  console.error("[!] Run start.sh (Mac/Linux) or start.bat (Windows) first to create the venv.");
  process.exit(1);
}

console.log(`[*] Starting backend with: ${venvBin}`);
execSync(`"${venvBin}" -m uvicorn main:app --reload`, {
  cwd: backendDir,
  stdio: "inherit",
});
