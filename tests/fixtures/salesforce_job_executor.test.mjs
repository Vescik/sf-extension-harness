import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { executeJob, loadInstalledSdk } from "../../scripts/salesforce_job_executor.mjs";

const JOB = "0Af000000000001AAA";
const NEXT = "0Af000000000002AAA";
const ORG = "00D000000000001";
const USER = "dev@example.test";
const HOST = "example--dev.sandbox.my.salesforce.com";
const clone = (value) => structuredClone(value);

function plan(action = "report", family = "deploy") {
  const id = family === "sandbox" ? "0GR000000000001AAA" : JOB;
  return {
    kind: "job", configDigest: "a".repeat(64),
    arguments: [...(family === "deploy" ? ["project", "deploy", action] : ["org", "resume", "sandbox"]), "--job-id", id, "--target-org", USER],
    targets: [{ username: USER, id: ORG, host: HOST, environment: "dev" }],
    job: { family, action, jobId: id, username: USER, id: ORG, host: HOST,
      options: { waitMinutes: action === "report" || family === "sandbox" ? 0 : 33, async: false, apiVersion: null, rest: false } },
  };
}
function fake(overrides = {}) {
  const calls = [];
  let clock = 0;
  const auth = { getFields: () => ({ username: USER, orgId: ORG, instanceUrl: `https://${HOST}`, accessToken: "private-token" }) };
  const connection = {
    instanceUrl: `https://${HOST}`,
    singleRecordQuery: async (query) => { calls.push(["identity", query]); return { Id: ORG }; },
    metadata: {
      checkDeployStatus: async (id, details, rest) => { calls.push(["status", id, details, rest]); return { id, status: "Succeeded", checkOnly: true, success: true, done: true, accessToken: "private-token", details: { huge: "x".repeat(100000) } }; },
      cancelDeploy: async (id) => { calls.push(["cancel", id]); },
      deployRecentValidation: async ({ id, rest }) => { calls.push(["quick", id, rest]); return NEXT; },
    },
  };
  const sdk = {
    AuthInfo: { create: async (options) => { calls.push(["auth", clone(options)]); return auth; } },
    Connection: { create: async (options) => { calls.push(["connection", options]); return connection; } },
    Org: { create: async (options) => {
      calls.push(["org", options]);
      return { resumeSandbox: async (request, options) => {
        calls.push(["sandbox", clone(request), clone(options)]);
        return { Id: request.SandboxProcessObjId, Status: "Completed", accessToken: "private-token" };
      } };
    } },
    sleep: async (ms) => { clock += ms; }, now: () => clock,
  };
  Object.assign(sdk, overrides);
  return { sdk, calls, auth, connection };
}
const mutations = (calls) => calls.filter(([kind]) => ["quick", "cancel", "sandbox"].includes(kind));

test("exact username and live org proof precede fixed job report", async () => {
  const fixture = fake();
  const response = await executeJob(plan(), { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 0, response.stderr);
  assert.deepEqual(fixture.calls[0], ["auth", { username: USER }]);
  assert.deepEqual(fixture.calls[2], ["identity", "SELECT Id FROM Organization LIMIT 1"]);
  assert.deepEqual(fixture.calls[3], ["status", JOB, true, false]);
  assert(!response.stdout.includes("private-token"));
  assert(response.stdout.length < 1024);
});

test("report and resume poll the fixed ID without restarting any deployment", async () => {
  for (const action of ["report", "resume"]) {
    const fixture = fake();
    const value = plan(action);
    if (action === "report") {
      value.arguments.push("--wait", "1");
      value.job.options.waitMinutes = 1;
    }
    let count = 0;
    fixture.connection.metadata.checkDeployStatus = async (id) => {
      fixture.calls.push(["status", id]);
      count += 1;
      return { id, status: count === 1 ? "InProgress" : "Succeeded", done: count > 1 };
    };
    const response = await executeJob(value, { dependencies: fixture.sdk });
    assert.equal(response.exitCode, 0, response.stderr);
    assert.deepEqual(fixture.calls.filter(([name]) => name === "status"), [["status", JOB], ["status", JOB]]);
    assert.equal(mutations(fixture.calls).length, 0);
  }
});

test("cancel dispatches exactly one request for the frozen job", async () => {
  const fixture = fake();
  const value = plan("cancel");
  value.arguments.push("--async");
  value.job.options.async = true;
  value.job.options.waitMinutes = 0;
  const response = await executeJob(value, { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 0, response.stderr);
  assert.deepEqual(mutations(fixture.calls), [["cancel", JOB]]);
});

test("quick validates selected ID then executes that ID once and reports new ID", async () => {
  const fixture = fake();
  const value = plan("quick");
  value.arguments.push("--api-version", "66.0");
  value.job.options.apiVersion = "66.0";
  const response = await executeJob(value, { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 0, response.stderr);
  assert.deepEqual(mutations(fixture.calls), [["quick", JOB, false]]);
  assert.equal(JSON.parse(response.stdout).result.id, NEXT);
  assert.equal(JSON.parse(response.stdout).result.validationId, JOB);
  assert.deepEqual(fixture.calls.find(([name]) => name === "connection")[1].connectionOptions, { version: "66.0" });
});

test("quick never silently skips a newest nonvalidation or failed validation", async () => {
  for (const fields of [{ checkOnly: false }, { status: "Failed" }, { done: false }, { success: false }]) {
    const fixture = fake();
    fixture.connection.metadata.checkDeployStatus = async (id) => ({ id, status: "Succeeded", checkOnly: true, done: true, success: true, ...fields });
    const response = await executeJob(plan("quick"), { dependencies: fixture.sdk });
    assert.equal(response.exitCode, 1);
    assert.equal(mutations(fixture.calls).length, 0);
  }
});

test("production and forged extra authority fields are rejected before auth", async () => {
  for (const mutate of [
    (value) => { value.targets[0].environment = "prod"; },
    (value) => { value.approved = true; },
    (value) => { value.job.options.target = "production"; },
    (value) => { value.job.username = "prod@example.test"; },
    (value) => { value.job.jobId = NEXT; },
    (value) => { value.arguments.push("--use-most-recent"); },
    (value) => { value.arguments.push("--flags-dir", "flags"); },
    (value) => { value.job.options.waitMinutes = 120; },
    (value) => { value.job.options.async = true; },
    (value) => { value.job.options.waitMinutes = "0"; },
  ]) {
    const fixture = fake();
    const value = plan();
    mutate(value);
    assert.equal((await executeJob(value, { dependencies: fixture.sdk })).exitCode, 1);
    assert.deepEqual(fixture.calls, []);
  }
});

test("auth username/org/host drift and live org mismatch prevent mutations", async () => {
  for (const fields of [{ username: "other@example.test" }, { orgId: "00D000000000099" }, { instanceUrl: "https://elsewhere.my.salesforce.com" }]) {
    const fixture = fake();
    fixture.auth.getFields = () => ({ username: USER, orgId: ORG, instanceUrl: `https://${HOST}`, ...fields });
    assert.equal((await executeJob(plan("quick"), { dependencies: fixture.sdk })).exitCode, 1);
    assert.equal(mutations(fixture.calls).length, 0);
  }
  const fixture = fake();
  fixture.connection.singleRecordQuery = async () => ({ Id: "00D000000000099" });
  assert.equal((await executeJob(plan("cancel"), { dependencies: fixture.sdk })).exitCode, 1);
  assert.equal(mutations(fixture.calls).length, 0);
});

test("caller/latest-cache mutations cannot alter frozen job or target after dispatch begins", async () => {
  const fixture = fake();
  const value = plan("quick");
  const original = fixture.sdk.AuthInfo.create;
  fixture.sdk.AuthInfo.create = async (options) => {
    value.job.username = "production@example.test";
    value.job.jobId = NEXT;
    value.targets[0].environment = "prod";
    return original(options);
  };
  const response = await executeJob(value, { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 0, response.stderr);
  assert.deepEqual(fixture.calls[0], ["auth", { username: USER }]);
  assert.deepEqual(mutations(fixture.calls), [["quick", JOB, false]]);
});

test("sandbox resume uses the pinned parent connection and concrete process ID", async () => {
  const fixture = fake();
  const value = plan("resume", "sandbox");
  const response = await executeJob(value, { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 0, response.stderr);
  assert.equal(fixture.calls.find(([name]) => name === "org")[1].connection, fixture.connection);
  assert.deepEqual(mutations(fixture.calls)[0][1], { SandboxProcessObjId: value.job.jobId });
  assert.equal(mutations(fixture.calls)[0][2].wait.seconds, 0);
  assert(!response.stdout.includes("private-token"));
});

test("scratch does not invoke the mutable-cache SDK", async () => {
  const fixture = fake();
  const value = plan("resume", "sandbox");
  value.job.family = "scratch";
  value.arguments[2] = "scratch";
  assert.equal((await executeJob(value, { dependencies: fixture.sdk })).exitCode, 1);
  assert.deepEqual(fixture.calls, []);
});

test("cancel before execution or between live proof and quick prevents dispatch", async () => {
  for (const before of [true, false]) {
    const fixture = fake();
    const controller = new AbortController();
    if (before) controller.abort();
    else fixture.connection.singleRecordQuery = async () => { controller.abort(); return { Id: ORG }; };
    const response = await executeJob(plan("quick"), { dependencies: fixture.sdk, signal: controller.signal });
    assert.equal(response.exitCode, 130);
    assert.equal(mutations(fixture.calls).length, 0);
    if (before) assert.deepEqual(fixture.calls, []);
  }
});

test("bounded polling stops without another deployment", async () => {
  const fixture = fake();
  const value = plan("resume");
  value.arguments.push("--wait", "1");
  value.job.options.waitMinutes = 1;
  fixture.connection.metadata.checkDeployStatus = async (id) => ({ id, status: "InProgress", done: false });
  const response = await executeJob(value, { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 1);
  assert.equal(JSON.parse(response.stdout).result.timedOut, true);
  assert.equal(mutations(fixture.calls).length, 0);
});

test("request timeout returns promptly and a late identity result cannot dispatch", async () => {
  const fixture = fake();
  let release;
  fixture.connection.singleRecordQuery = () => new Promise((resolve) => { release = resolve; });
  const response = await executeJob(plan("quick"), { dependencies: fixture.sdk, requestTimeoutMs: 10 });
  assert.equal(response.exitCode, 1);
  assert.match(response.stderr, /timed out/);
  release({ Id: ORG });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(mutations(fixture.calls).length, 0);
});

test("the native host's 1 MiB output limit is supported", async () => {
  const fixture = fake();
  const response = await executeJob(plan(), { dependencies: fixture.sdk, maxOutputBytes: 1_048_576 });
  assert.equal(response.exitCode, 0, response.stderr);
});

test("SDK credential-bearing exceptions and oversized fields never escape", async () => {
  const fixture = fake();
  fixture.connection.singleRecordQuery = async () => { throw new Error("OAuth accessToken=private-token refreshToken=secret"); };
  const response = await executeJob(plan("cancel"), { dependencies: fixture.sdk });
  assert.equal(response.exitCode, 1);
  assert(!JSON.stringify(response).includes("private-token"));
  assert(!JSON.stringify(response).includes("refreshToken"));
  assert.equal((await executeJob(plan(), { dependencies: fixture.sdk, maxOutputBytes: 2 })).exitCode, 1);
});

test("SDK loader rejects executable within the workspace before loading packages", async () => {
  const workspace = await mkdtemp(path.join(tmpdir(), "sf-job-loader-"));
  try {
    const executable = path.join(workspace, "sf");
    await writeFile(executable, "not executed");
    await assert.rejects(loadInstalledSdk({ workspace, sfExecutable: executable }), /Workspace Salesforce executables are forbidden/);
  } finally { await rm(workspace, { recursive: true, force: true }); }
});

test("Windows npm and standalone shims resolve the same manifest SDK without executing cmd", async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "sf-sdk-layout-"));
  try {
    const workspace = path.join(temporary, "workspace");
    await mkdir(workspace);
    for (const layout of ["npm", "standalone"]) {
      const install = path.join(temporary, layout);
      const cliRoot = layout === "npm" ? path.join(install, "node_modules", "@salesforce", "cli") : install;
      const binRoot = layout === "npm" ? install : path.join(install, "bin");
      const coreRoot = path.join(cliRoot, "node_modules", "@salesforce", "core");
      await mkdir(path.join(cliRoot, "bin"), { recursive: true });
      await mkdir(path.join(coreRoot, "lib"), { recursive: true });
      await writeFile(path.join(cliRoot, "package.json"), JSON.stringify({ name: "@salesforce/cli", version: "2.151.7", bin: { sf: "./bin/run.js" } }));
      await writeFile(path.join(cliRoot, "bin", "run.js"), "throw new Error('CLI must not execute');");
      await writeFile(path.join(coreRoot, "package.json"), JSON.stringify({ name: "@salesforce/core", version: "9.2.0" }));
      await writeFile(path.join(coreRoot, "lib", "index.js"), `module.exports = { fixture: ${JSON.stringify(layout)} };`);
      const sfExecutable = path.join(binRoot, "sf.cmd");
      await writeFile(sfExecutable, "@echo off\nexit /b 99\n");
      const sdk = await loadInstalledSdk({ workspace, sfExecutable });
      assert.equal(sdk.fixture, layout);
      // A missing/unreviewed selected installation must not pick another CLI.
      await writeFile(path.join(cliRoot, "package.json"), JSON.stringify({ name: "@salesforce/cli", version: "2.1.0", bin: { sf: "./bin/run.js" } }));
      await assert.rejects(loadInstalledSdk({ workspace, sfExecutable }), /version has not been reviewed/);
    }
  } finally { await rm(temporary, { recursive: true, force: true }); }
});
