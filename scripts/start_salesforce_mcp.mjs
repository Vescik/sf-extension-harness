#!/usr/bin/env node
// Thin launcher for the Python REST review facade (salesforce_review_server.py).
//
// Kept (plan-2026-08-09 F-3 deviation, reviewed): .vscode/mcp.json cannot express a
// cross-platform Python interpreter path, and a bare "python" command would run
// whatever interpreter is first on PATH - typically one without the admitted
// `requests` dependency. This launcher resolves the interpreter exactly like the
// knowledge server does (env override -> repo .venv -> py -3 -> python3 -> python,
// probed for the real dependency) and keeps the pre-contact walls that must hold
// before ANY process talks to an org. The old vendor-MCP child and the .mjs review
// server are gone from this launch path; F-4 deletes them from the tree.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "..");
const CONFIG_PATH = resolve(REPO_ROOT, "config", "harness.local.json");
const REVIEW_SERVER = resolve(SCRIPT_DIR, "salesforce_review_server.py");
const PROBE_TIMEOUT_MS = 15_000;

function fail(message) {
  process.stderr.write(`Salesforce MCP startup blocked: ${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      fail("expected --mode review --org <alias>");
    }
    parsed[key.slice(2)] = value;
  }
  return parsed;
}

const { mode, org } = parseArgs(process.argv.slice(2));
// This launcher exposes the structured review facade only. Developer writes deliberately use
// direct sf/sfdx commands, so no write-mode MCP process is launched from here.
if (mode !== "review") {
  fail(`unsupported mode '${mode ?? ""}'; this MCP launcher supports review mode only`);
}
// First never-production wall, pre-contact; the Python server re-checks it and adds
// the live host/org-id/IsSandbox proof before serving any tool call.
if (!org || /(^|[^a-z])(prod|production)([^a-z]|$)/i.test(org)) {
  fail("the org alias is missing or production-like");
}

let config;
if (!existsSync(CONFIG_PATH)) {
  fail(
    "config/harness.local.json is missing; create the ignored local policy from " +
      "config/harness.example.json before starting Salesforce MCP",
  );
}
try {
  config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
} catch (error) {
  fail(`cannot read valid ${CONFIG_PATH}: ${error.message}`);
}

const entry = config?.salesforce?.orgs?.find((candidate) => candidate?.alias === org);
const environment = entry ? String(entry.environment).trim().toLowerCase() : null;
if (environment === "production") {
  fail(`alias '${org}' is marked production in local configuration`);
}
if (entry && !new Set(["development", "qa", "uat"]).has(environment)) {
  fail(`alias '${org}' has an unsupported environment classification`);
}
if (config?.salesforce?.review?.enabled !== true) {
  fail("Salesforce org review is disabled in local configuration");
}

process.stderr.write("Salesforce MCP startup: resolving the Python runtime\n");

// Interpreter ladder (same shape as knowledge_mcp_server.mjs): the probe imports the
// facade's real third-party dependency, so a missing `requests` surfaces here as one
// actionable message instead of a dead server.
function interpreterCandidates() {
  const candidates = [];
  if (process.env.SALESFORCE_MCP_PYTHON) candidates.push([process.env.SALESFORCE_MCP_PYTHON]);
  candidates.push(
    [join(REPO_ROOT, ".venv", "bin", "python")],
    [join(REPO_ROOT, ".venv", "Scripts", "python.exe")],
    ["py", "-3"],
    ["python3"],
    ["python"],
  );
  return candidates;
}

let python = null;
for (const candidate of interpreterCandidates()) {
  const probe = spawnSync(candidate[0], [...candidate.slice(1), "-c", "import requests"], {
    timeout: PROBE_TIMEOUT_MS,
    stdio: "ignore",
  });
  if (!probe.error && probe.status === 0) {
    python = candidate;
    break;
  }
}
if (!python) {
  fail(
    "no Python interpreter with the 'requests' dependency was found (tried " +
      "SALESFORCE_MCP_PYTHON, the repo .venv, py -3, python3, python); run: " +
      "python -m pip install --require-hashes -r requirements-dev.lock",
  );
}

process.stderr.write(
  "Salesforce MCP startup: launching the review facade; CLI authorization and live org validation run before tool discovery\n",
);

const child = spawn(python[0], [...python.slice(1), REVIEW_SERVER, "--org", org], {
  cwd: REPO_ROOT,
  // PYTHONUTF8 forces UTF-8 std streams on Windows, where the default encoding is a
  // legacy code page and the MCP spec mandates UTF-8 frames.
  env: { ...process.env, PYTHONUTF8: "1" },
  stdio: "inherit",
  shell: false,
});

child.on("error", (error) => fail(`failed to start the Python review facade: ${error.message}`));
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
