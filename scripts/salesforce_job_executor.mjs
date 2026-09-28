/** Private native-host adapter. Never spawn a CLI or read a job/alias cache.
 * Reviewed against Salesforce CLI 2.151.7 / @salesforce/core 9.2.0:
 * Connection.metadata checkDeployStatus/cancelDeploy/deployRecentValidation,
 * and Org.create({connection}).resumeSandbox({SandboxProcessObjId}, options).
 * CLI formatters, manifests, source tracking and cached output options are not run.
 */
import { readFile, realpath, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const ORG_ID = /^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$/;
const DEPLOY_ID = /^0Af[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$/;
const SANDBOX_ID = /^0GR[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$/;
const HOST = /^[a-z0-9][a-z0-9-]*(?:--[a-z0-9][a-z0-9-]*)?(?:\.sandbox\.my|\.scratch\.my|\.develop\.my|\.my)?\.salesforce\.com$/;
const FINAL = new Set(["Succeeded", "SucceededPartial", "Failed", "Canceled"]);
const STATUSES = new Set([...FINAL, "Pending", "InProgress", "Canceling", "FinalizingDeploy", "FinalizingFailed"]);

class JobError extends Error {}
function requireCondition(condition, message) {
  if (!condition) throw new JobError(message);
}
function exact(value, keys, name) {
  requireCondition(value && typeof value === "object" && !Array.isArray(value), `Invalid ${name}.`);
  requireCondition(Object.keys(value).sort().join("|") === [...keys].sort().join("|"), `Unexpected ${name} fields.`);
}
const containsControl = (value) => [...value].some((character) => character.charCodeAt(0) < 32);
function identity(value) {
  requireCondition(typeof value.username === "string" && value.username.length <= 254 && !containsControl(value.username) && /^[^\s/\\]+@[^\s/\\]+$/.test(value.username), "Invalid exact username.");
  requireCondition(typeof value.id === "string" && ORG_ID.test(value.id), "Invalid org identity.");
  requireCondition(typeof value.host === "string" && HOST.test(value.host) && !["login.salesforce.com", "test.salesforce.com", "auth.salesforce.com"].includes(value.host), "Invalid Salesforce instance host.");
}

export function validateJobExecution(value) {
  exact(value, ["kind", "arguments", "targets", "job", "configDigest"], "job execution");
  requireCondition(value.kind === "job" && /^[a-f0-9]{64}$/.test(value.configDigest), "Invalid native execution identity.");
  requireCondition(Array.isArray(value.arguments) && value.arguments.length <= 50 && value.arguments.every((item) => typeof item === "string" && item.length <= 512 && !containsControl(item)), "Invalid bound arguments.");
  requireCondition(Array.isArray(value.targets) && value.targets.length === 1, "Exactly one controlling org is required.");
  const target = value.targets[0];
  exact(target, ["username", "id", "host", "environment"], "target");
  identity(target);
  requireCondition(["dev", "uat", "stage"].includes(target.environment), "Native job execution is restricted to nonproduction.");
  const job = value.job;
  exact(job, ["family", "action", "jobId", "username", "id", "host", "options"], "job");
  identity(job);
  requireCondition(job.username === target.username && job.id === target.id && job.host === target.host, "Job and controlling org do not match.");
  requireCondition(typeof job.jobId === "string" && ((job.family === "deploy" && ["report", "resume", "cancel", "quick"].includes(job.action) && DEPLOY_ID.test(job.jobId)) || (job.family === "sandbox" && job.action === "resume" && SANDBOX_ID.test(job.jobId))), "Unsupported job family or ID.");
  const options = job.options;
  exact(options, ["waitMinutes", "async", "apiVersion", "rest"], "job options");
  requireCondition(Number.isInteger(options.waitMinutes) && options.waitMinutes >= 0 && options.waitMinutes <= 120 && typeof options.async === "boolean" && typeof options.rest === "boolean", "Invalid job options.");
  requireCondition(options.apiVersion === null || (job.family === "deploy" && job.action === "quick" && /^[1-9][0-9]{1,2}\.0$/.test(options.apiVersion)), "Unsupported API version option.");
  requireCondition(!options.async || (job.family === "deploy" && ["quick", "cancel"].includes(job.action) && options.waitMinutes === 0), "Unsupported asynchronous job.");
  requireCondition(job.family !== "sandbox" || !options.rest, "Sandbox resume cannot use metadata transport options.");
  // Arguments are a display binding, not code to run. Still require agreement
  // with the selected immutable job and allow only the reviewed flag grammar.
  const prefix = job.family === "deploy" ? ["project", "deploy", job.action] : ["org", "resume", "sandbox"];
  requireCondition(value.arguments.slice(0, 3).join(" ") === prefix.join(" "), "Bound command does not match the job.");
  const parsed = new Map();
  for (let index = 3; index < value.arguments.length; index += 1) {
    const flag = value.arguments[index];
    requireCondition(["--job-id", "--target-org", "--wait", "--api-version", "--json", "--async"].includes(flag) && !parsed.has(flag), "Unsupported bound command option.");
    if (["--json", "--async"].includes(flag)) parsed.set(flag, true);
    else {
      index += 1;
      requireCondition(index < value.arguments.length, "Missing bound option.");
      parsed.set(flag, value.arguments[index]);
    }
  }
  requireCondition(parsed.get("--job-id") === job.jobId && parsed.get("--target-org") === job.username, "Bound job ID or username differs from execution.");
  requireCondition(Boolean(parsed.get("--async")) === options.async, "Bound async option differs from execution.");
  requireCondition(!parsed.has("--wait") || (/^[0-9]{1,4}$/.test(parsed.get("--wait")) && Number(parsed.get("--wait")) === options.waitMinutes), "Bound wait differs from execution.");
  requireCondition(!parsed.has("--wait") || (!options.async && (job.family === "sandbox" || options.waitMinutes >= 1)), "Unsupported bound wait option.");
  const defaultWait = options.async || job.family === "sandbox" || job.action === "report" ? 0 : 33;
  requireCondition(parsed.has("--wait") || options.waitMinutes === defaultWait, "Unbound wait option.");
  requireCondition((parsed.get("--api-version") ?? null) === options.apiVersion, "Bound API version differs from execution.");
  return structuredClone(value);
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}
async function packageJson(root) {
  const filename = path.join(root, "package.json");
  requireCondition((await stat(filename)).size <= 1_000_000, "Oversized SDK package metadata.");
  return JSON.parse(await readFile(filename, "utf8"));
}

async function boundedText(filename) {
  requireCondition((await stat(filename)).size <= 65536, "Oversized CLI launcher.");
  return readFile(filename, "utf8");
}

/** Resolve the selected launcher's own installation, not an unrelated CLI on disk. */
export async function loadInstalledSdk({ sfExecutable, workspace }) {
  requireCondition(typeof sfExecutable === "string" && path.isAbsolute(sfExecutable), "A trusted installed Salesforce CLI path is required.");
  requireCondition(typeof workspace === "string" && path.isAbsolute(workspace), "A trusted workspace is required.");
  const workspaceRoot = await realpath(workspace);
  let executable = await realpath(sfExecutable);
  requireCondition(!isWithin(workspaceRoot, executable), "Workspace Salesforce executables are forbidden.");
  // Match the native host's Windows npm/standalone manifest resolution. A cmd
  // shim is never evaluated and cannot pass arguments to a command processor.
  if (/^sf\.(cmd|bat)$/i.test(path.basename(executable))) {
    const directory = path.dirname(executable);
    let entrypoint;
    for (const candidate of [path.join(directory, "node_modules", "@salesforce", "cli"), path.resolve(directory, "..")]) {
      try {
        const root = await realpath(candidate);
        requireCondition(!isWithin(workspaceRoot, root), "Workspace Salesforce packages are forbidden.");
        const cli = await packageJson(root);
        if (cli.name !== "@salesforce/cli") continue;
        const entry = typeof cli.bin === "string" ? cli.bin : cli.bin?.sf;
        requireCondition(typeof entry === "string" && !path.isAbsolute(entry), "Invalid installed Salesforce entrypoint.");
        const script = await realpath(path.resolve(root, entry));
        requireCondition(isWithin(root, script) && /\.(m?js|cjs)$/i.test(script) && (await stat(script)).isFile(), "Salesforce entrypoint escapes the selected installation.");
        entrypoint = script;
        break;
      } catch (error) {
        if (error instanceof JobError) throw error;
        if (error?.code !== "ENOENT") throw new JobError("Selected Windows Salesforce installation is unavailable.");
      }
    }
    requireCondition(entrypoint, "Cannot resolve the installed Salesforce Node entrypoint safely on Windows.");
    executable = entrypoint;
  }
  // The standalone macOS/Linux launcher redirects to its user client/bin/sf.
  // Resolve that launcher literally; never execute shell text or follow arbitrary
  // package/module search paths. Other launcher formats fail closed below.
  if (["sf", "sfdx"].includes(path.basename(executable))) {
    let source = await boundedText(executable);
    if (source.includes("CLIENT_HOME=${SF_OCLIF_CLIENT_HOME:=$XDG_DATA_HOME/sf/client}") && !process.env.SF_REDIRECTED) {
      const clientHome = process.env.SF_OCLIF_CLIENT_HOME || path.join(process.env.XDG_DATA_HOME || path.join(homedir(), ".local", "share"), "sf", "client");
      requireCondition(path.isAbsolute(clientHome), "Relative Salesforce client roots are forbidden.");
      try {
        const redirected = await realpath(path.join(clientHome, "bin", "sf"));
        requireCondition(!isWithin(workspaceRoot, redirected), "Workspace Salesforce clients are forbidden.");
        if (redirected !== executable) {
          executable = redirected;
          source = await boundedText(executable);
        }
      } catch (error) {
        if (error instanceof JobError) throw error;
        // Missing redirect is the launcher's documented fallback to its own root.
        if (error?.code !== "ENOENT") throw new JobError("Selected Salesforce client is unavailable.");
      }
    }
    const versionRedirect = source.match(/SF_REDIRECTED=1 "\$DIR\/\.\.\/([0-9]+\.[0-9]+\.[0-9]+-[a-zA-Z0-9]+)\/bin\/sf" "\$@"/);
    if (versionRedirect) executable = await realpath(path.join(path.dirname(executable), "..", versionRedirect[1], "bin", "sf"));
  }
  requireCondition(!isWithin(workspaceRoot, executable), "Workspace Salesforce clients are forbidden.");
  let directory = path.dirname(executable);
  for (let count = 0; count < 4; count += 1) {
    try {
      const root = await realpath(directory);
      requireCondition(!isWithin(workspaceRoot, root), "Workspace Salesforce packages are forbidden.");
      const cli = await packageJson(root);
      if (cli.name === "@salesforce/cli") {
        requireCondition(cli.version === "2.151.7", "Selected Salesforce CLI version has not been reviewed for native jobs.");
        const coreRoot = await realpath(path.join(root, "node_modules", "@salesforce", "core"));
        requireCondition(isWithin(root, coreRoot) && !isWithin(workspaceRoot, coreRoot), "Salesforce SDK escapes the selected installation.");
        const core = await packageJson(coreRoot);
        requireCondition(core.name === "@salesforce/core" && core.version === "9.2.0", "Selected Salesforce core version has not been reviewed.");
        const require = createRequire(path.join(root, "package.json"));
        return { ...require(path.join(coreRoot, "lib", "index.js")), sleep: (ms, signal) => delay(ms, undefined, { signal }), now: Date.now };
      }
    } catch (error) {
      if (error instanceof JobError) throw error;
      if (error?.code !== "ENOENT") throw new JobError("Selected installed Salesforce SDK is unavailable.");
    }
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  throw new JobError("The reviewed installed Salesforce CLI 2.151.7 / core 9.2.0 SDK was not found.");
}

function checkCanceled(signal) {
  if (signal?.aborted) throw new JobError("Operation canceled. Any already dispatched server request is not rolled back.");
}
async function boundedRequest(action, controller, timeoutMs) {
  checkCanceled(controller.signal);
  let timer;
  let cancel;
  try {
    return await Promise.race([
      Promise.resolve().then(() => { checkCanceled(controller.signal); return action(); }),
      new Promise((_, reject) => {
        cancel = () => reject(new JobError("Operation canceled. Any already dispatched server request is not rolled back."));
        controller.signal.addEventListener("abort", cancel, { once: true });
        timer = setTimeout(() => {
          reject(new JobError("Salesforce request timed out. Any already dispatched server request is not rolled back."));
          controller.abort();
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
    controller.signal.removeEventListener("abort", cancel);
  }
}
function hostOf(instanceUrl) {
  try {
    const url = new URL(instanceUrl);
    requireCondition(url.protocol === "https:" && !url.username && !url.password && !url.port && !url.search && !url.hash && ["", "/"].includes(url.pathname), "Unexpected connection endpoint.");
    return url.hostname;
  } catch { throw new JobError("Unexpected connection endpoint."); }
}
function sameOrg(actual, expected) {
  return typeof actual === "string" && ORG_ID.test(actual) && actual.slice(0, 15) === expected.slice(0, 15);
}

async function pinnedConnection(job, sdk, signal, request) {
  checkCanceled(signal);
  // AuthInfo's username option is exact; Org alias/default resolution is not used.
  const authInfo = await request(() => sdk.AuthInfo.create({ username: job.username }));
  checkCanceled(signal);
  const fields = authInfo.getFields();
  requireCondition(fields.username === job.username && sameOrg(fields.orgId, job.id) && hostOf(fields.instanceUrl) === job.host, "Selected authorization identity changed.");
  const connection = await request(() => sdk.Connection.create({ authInfo, ...(job.options.apiVersion ? { connectionOptions: { version: job.options.apiVersion } } : {}) }));
  checkCanceled(signal);
  requireCondition(hostOf(connection.instanceUrl) === job.host, "Selected connection host changed.");
  const live = await request(() => connection.singleRecordQuery("SELECT Id FROM Organization LIMIT 1"));
  checkCanceled(signal);
  requireCondition(sameOrg(live?.Id, job.id) && hostOf(connection.instanceUrl) === job.host, "Live organization identity does not match the selected target.");
  return connection;
}

function deploySummary(response, id) {
  requireCondition(response && typeof response === "object" && typeof response.id === "string" && DEPLOY_ID.test(response.id) && response.id.slice(0, 15) === id.slice(0, 15), "Server returned a different deploy job.");
  requireCondition(STATUSES.has(response.status), "Server returned an unrecognized deploy status.");
  const result = { id: response.id, status: response.status };
  for (const key of ["done", "success", "checkOnly"]) if (typeof response[key] === "boolean") result[key] = response[key];
  for (const key of ["numberComponentErrors", "numberComponentsDeployed", "numberComponentsTotal", "numberTestErrors", "numberTestsCompleted", "numberTestsTotal"]) {
    if (Number.isSafeInteger(response[key]) && response[key] >= 0) result[key] = response[key];
  }
  return result;
}

async function deployJob(job, connection, sdk, signal, request) {
  let id = job.jobId;
  const options = job.options;
  const status = async () => {
    checkCanceled(signal);
    const response = await request(() => connection.metadata.checkDeployStatus(id, true, options.rest));
    checkCanceled(signal);
    return deploySummary(response, id);
  };
  if (job.action === "quick") {
    const validation = await status();
    requireCondition(validation.checkOnly === true && validation.success === true && validation.done === true && validation.status === "Succeeded", "Quick deploy requires the selected job to be a successful completed validation.");
    checkCanceled(signal);
    const created = await request(() => connection.metadata.deployRecentValidation({ id, rest: options.rest }));
    id = typeof created === "string" ? created : created?.id;
    requireCondition(typeof id === "string" && DEPLOY_ID.test(id), "Quick deploy returned an invalid job ID.");
    if (options.async) return { id, validationId: job.jobId, status: "Pending" };
  } else if (job.action === "cancel") {
    checkCanceled(signal);
    await request(() => connection.metadata.cancelDeploy(id));
    if (options.async) return { id, status: "Canceling" };
  }
  const deadline = sdk.now() + options.waitMinutes * 60_000;
  let result = await status();
  while (!FINAL.has(result.status) && !result.done && sdk.now() < deadline) {
    await sdk.sleep(Math.min(1000, deadline - sdk.now()), signal);
    result = await status();
  }
  return { ...result, ...(job.action === "quick" ? { validationId: job.jobId } : {}), ...(!FINAL.has(result.status) && !result.done && options.waitMinutes > 0 ? { timedOut: true } : {}) };
}

async function sandboxJob(job, connection, sdk, signal, request) {
  // Passing connection prevents Org.create from resolving any alias/default.
  const org = await request(() => sdk.Org.create({ connection }));
  const deadline = sdk.now() + job.options.waitMinutes * 60_000;
  while (true) {
    checkCanceled(signal);
    try {
      // One status/auth step per call. A zero SDK wait avoids an uncancelable
      // background polling loop; this adapter owns bounded, cancellable polling.
      const response = await request(() => org.resumeSandbox({ SandboxProcessObjId: job.jobId }, {
        wait: { seconds: 0, minutes: 0, milliseconds: 0 },
        interval: { seconds: 30, minutes: 0.5, milliseconds: 30000 },
      }));
      requireCondition(response && typeof response.Id === "string" && SANDBOX_ID.test(response.Id) && response.Id.slice(0, 15) === job.jobId.slice(0, 15), "Server returned a different sandbox process.");
      requireCondition(typeof response.Status === "string" && /^[A-Za-z][A-Za-z ]{0,60}$/.test(response.Status), "Server returned an invalid sandbox process status.");
      return { id: response.Id, status: response.Status };
    } catch (error) {
      if (!["SandboxCreateNotCompleteError", "SandboxAuthNotCompleteError", "SandboxAuthIncompleteError"].includes(error?.name)) throw error;
      if (sdk.now() >= deadline) return { id: job.jobId, status: "InProgress", timedOut: job.options.waitMinutes > 0 };
      await sdk.sleep(Math.min(30000, deadline - sdk.now()), signal);
    }
  }
}

/** dependencies is an internal test seam; never read from execution/model input. */
export async function executeJob(execution, { signal, workspace, sfExecutable, maxOutputBytes = 65536, requestTimeoutMs = 30000, dependencies } = {}) {
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    requireCondition(Number.isInteger(maxOutputBytes) && maxOutputBytes >= 1024 && maxOutputBytes <= 1_048_576, "Invalid output limit.");
    requireCondition(Number.isInteger(requestTimeoutMs) && requestTimeoutMs >= 1 && requestTimeoutMs <= 120000, "Invalid request timeout.");
    const plan = validateJobExecution(execution); // isolate caller mutations before await
    const activeSignal = controller.signal;
    const request = (action) => boundedRequest(action, controller, requestTimeoutMs);
    checkCanceled(activeSignal);
    const sdk = dependencies ?? await loadInstalledSdk({ sfExecutable, workspace });
    const connection = await pinnedConnection(plan.job, sdk, activeSignal, request);
    const result = plan.job.family === "deploy"
      ? await deployJob(plan.job, connection, sdk, activeSignal, request)
      : await sandboxJob(plan.job, connection, sdk, activeSignal, request);
    const stdout = JSON.stringify({ result, target: { id: plan.job.id, username: plan.job.username }, family: plan.job.family, action: plan.job.action });
    requireCondition(Buffer.byteLength(stdout, "utf8") <= maxOutputBytes, "Job output exceeded the allowed limit.");
    const failed = result.timedOut || (plan.job.family === "deploy" && (["Failed", "SucceededPartial"].includes(result.status) || (result.status === "Canceled" && plan.job.action !== "cancel") || (plan.job.action === "cancel" && result.status === "Succeeded")));
    return { stdout, stderr: "", exitCode: failed ? 1 : 0 };
  } catch (error) {
    // SDK errors can contain OAuth URLs/tokens/auth fields. Never forward them.
    return { stdout: "", stderr: error instanceof JobError ? error.message : "Salesforce job request failed; raw SDK diagnostics were withheld.", exitCode: signal?.aborted ? 130 : 1 };
  } finally {
    signal?.removeEventListener("abort", forwardAbort);
    controller.abort();
  }
}
