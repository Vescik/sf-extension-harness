#!/usr/bin/env node
// Keep the vendor's stdio protocol intact. Scope lives only in the local JSON and
// this process's memory; a changed scope requires a new ADO MCP process.
import { spawn } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { constants } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CONFIG_PATH = resolve(REPO_ROOT, "config/harness.local.json");
const PACKAGE_ROOT = resolve(REPO_ROOT, "node_modules/@azure-devops/mcp");
const VENDOR_ENTRY = resolve(PACKAGE_ROOT, "dist/index.js");
const WIKI_PRELOAD = resolve(REPO_ROOT, "scripts/ado_wiki_preload.mjs");
const VENDOR_VERSION = "2.8.1";
const CONFIG_POLL_MS = 250;
const SHUTDOWN_GRACE_MS = 1000;

function configurationError(message) {
  return new Error(`ADO configuration error: ${message}. Set it in config/harness.local.json.`);
}

function hasControlCharacters(value) {
  return [...value].some((character) => character.codePointAt(0) < 32 || character.codePointAt(0) === 127);
}

function configuredText(ado, key) {
  const value = ado[key];
  const path = `ado.${key}`;
  if (typeof value !== "string") throw configurationError(`${path} must be a string`);
  if (!value.trim()) throw configurationError(`${path} is empty`);
  if (value !== value.trim() || hasControlCharacters(value)) {
    throw configurationError(`${path} contains surrounding whitespace or control characters`);
  }
  if (/[<>]/u.test(value) || /^(?:TODO|TBD|CHANGEME|REPLACE_ME|your-org-slug|your-project-name)$/iu.test(value)) {
    throw configurationError(`${path} contains a placeholder`);
  }
  return value;
}

function readScope() {
  let content;
  try {
    content = readFileSync(CONFIG_PATH, "utf8");
  } catch {
    throw configurationError("config/harness.local.json is missing or unreadable");
  }
  let config;
  try {
    config = JSON.parse(content);
  } catch {
    // JSON parser errors may include source text. Do not print local config data.
    throw configurationError("config/harness.local.json is not valid JSON");
  }
  const ado = config?.ado;
  if (!ado || typeof ado !== "object" || Array.isArray(ado)) {
    throw configurationError("ado must be an object");
  }
  const organization = configuredText(ado, "organization");
  const project = configuredText(ado, "project");
  if (!/^[A-Za-z0-9][A-Za-z0-9-]*$/u.test(organization)) {
    throw configurationError("ado.organization must be an organization slug, not a URL or option");
  }
  if (/[/\\]/u.test(project)) {
    throw configurationError("ado.project must be a project name, not a URL or path");
  }
  const origins = ado.allowedHttpsOrigins;
  const expectedOrigin = `https://dev.azure.com/${organization}`;
  if (!Array.isArray(origins) || !origins.includes(expectedOrigin)) {
    throw configurationError("ado.allowedHttpsOrigins must include https://dev.azure.com/<configured organization>");
  }
  for (const origin of origins) {
    let url;
    try {
      if (typeof origin !== "string" || origin !== origin.trim() || hasControlCharacters(origin) || /[\s\u0085<>\\]/u.test(origin)) {
        throw new Error("invalid origin");
      }
      url = new URL(origin);
      const authority = origin.split("/")[2] ?? "";
      if (!origin.startsWith("https://") || url.protocol !== "https:" || !url.hostname ||
          url.username !== "" || url.password !== "" || url.port !== "" || /:\d*$/u.test(authority) ||
          url.search || url.hash || origin.includes("?") || origin.includes("#") ||
          (url.hostname === "dev.azure.com" && origin !== expectedOrigin) ||
          url.hostname.endsWith(".dev.azure.com") ||
          url.hostname === "visualstudio.com" || url.hostname.endsWith(".visualstudio.com")) {
        throw new Error("invalid origin");
      }
    } catch {
      throw configurationError("ado.allowedHttpsOrigins contains an invalid HTTPS origin or a different ADO organization");
    }
  }
  if (new Set(origins).size !== origins.length) {
    throw configurationError("ado.allowedHttpsOrigins contains duplicates");
  }
  return JSON.stringify([organization, project, [...origins].sort()]);
}

function checkDependency() {
  try {
    const manifest = JSON.parse(readFileSync(resolve(PACKAGE_ROOT, "package.json"), "utf8"));
    if (manifest.name !== "@azure-devops/mcp" || manifest.version !== VENDOR_VERSION ||
        !statSync(VENDOR_ENTRY).isFile()) {
      throw new Error("incorrect vendor dependency");
    }
    for (const file of [WIKI_PRELOAD, ...["ado_wiki_loader.mjs", "ado_wiki_tools.mjs", "ado_wiki_link_tools.mjs"].map(name => resolve(REPO_ROOT, "scripts", name))]) {
      if (!statSync(file).isFile()) throw new Error("Wiki publication adapter unavailable");
    }
  } catch {
    throw new Error(`ADO MCP dependency unavailable: restore the reviewed Wiki adapter and install the pinned @azure-devops/mcp ${VENDOR_VERSION} with npm ci in the workspace.`);
  }
}

function main() {
  if (process.argv.length !== 2) {
    throw new Error("ADO MCP launcher does not accept arguments. Configure ado.organization and ado.project in config/harness.local.json.");
  }
  const initialScope = readScope();
  checkDependency();
  if (readScope() !== initialScope) {
    throw new Error("ADO configuration changed during startup. Restart the ADO MCP server.");
  }
  const [organization] = JSON.parse(initialScope);
  const child = spawn(process.execPath, ["--import", new URL("./ado_wiki_preload.mjs", import.meta.url).href, VENDOR_ENTRY, organization, "-d", "work-items", "wiki", "search"], {
    cwd: REPO_ROOT,
    shell: false,
    stdio: ["pipe", "pipe", "inherit"],
  });
  let stopping = false;
  let exitCode;
  let shutdownTimer;

  function stop(code, signal = "SIGTERM") {
    if (stopping) return;
    stopping = true;
    exitCode = code;
    clearInterval(configTimer);
    process.stdin.destroy();
    child.kill(signal);
    child.stdin.destroy();
    child.stdout.destroy();
    // EOF and signals must not leave a vendor process behind if it fails to exit.
    clearTimeout(shutdownTimer);
    shutdownTimer = setTimeout(() => child.kill("SIGKILL"), SHUTDOWN_GRACE_MS);
  }

  function scopeIsCurrent() {
    if (stopping) return false;
    try {
      if (readScope() === initialScope) return true;
      throw new Error("ADO organization, project, or allowed origin changed");
    } catch (error) {
      process.stderr.write(`${error.message} Restart the ADO MCP server after correcting configuration.\n`);
      stop(2);
      return false;
    }
  }

  // Poll while idle as well as checking synchronously before each forwarded
  // buffer. Atomic file replacement is covered without platform-specific watches.
  const configTimer = setInterval(scopeIsCurrent, CONFIG_POLL_MS);
  process.stdin.on("data", (chunk) => {
    if (!scopeIsCurrent()) return;
    if (!child.stdin.write(chunk)) process.stdin.pause();
  });
  child.stdin.on("drain", () => {
    if (scopeIsCurrent()) process.stdin.resume();
  });
  child.stdout.on("data", (chunk) => {
    if (!scopeIsCurrent()) return;
    if (!process.stdout.write(chunk)) child.stdout.pause();
  });
  process.stdout.on("drain", () => {
    if (scopeIsCurrent()) child.stdout.resume();
  });
  child.stdin.on("error", () => stop(1));
  child.stdout.on("error", () => stop(1));
  process.stdin.on("error", () => stop(1));
  process.stdout.on("error", () => stop(1));
  process.stdin.on("end", () => {
    if (stopping) return;
    child.stdin.end();
    // Allow already-forwarded replies to drain with scope checks still active.
    shutdownTimer = setTimeout(() => stop(1), SHUTDOWN_GRACE_MS);
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => stop(128 + constants.signals[signal], signal));
  }
  child.on("error", () => {
    process.stderr.write("ADO MCP could not start the installed vendor process. Run npm ci in the workspace and restart ADO MCP.\n");
    stop(2);
  });
  child.on("close", (code, signal) => {
    clearInterval(configTimer);
    clearTimeout(shutdownTimer);
    process.stdin.destroy();
    process.exitCode = exitCode ?? code ?? (signal ? 128 + constants.signals[signal] : 1);
  });
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 2;
}
