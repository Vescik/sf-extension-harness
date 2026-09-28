import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm, chmod, realpath } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import vm from 'node:vm';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { buildRuntime, RUNTIME_FILES } from '../build.mjs';
import { createZip } from '../package.mjs';
import { cleanEnvironment, cliInvocation, findExecutable, recheckExecution, runBounded, sanitizeOutput, verifyRuntime } from '../src/host.mjs';

async function temporary(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'sf-native-host-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return await realpath(directory);
}

test('bounded child argv is passed literally without a shell', async () => {
  const literal = 'a & b; $(never) | > < `x` "q"';
  const result = await runBounded(process.execPath, ['-e', 'process.stdout.write(process.argv[1])', '--', literal]);
  assert.equal(result.stdout, literal); assert.equal(result.exitCode, 0);
});

test('oversized output, process timeout and cancellation are bounded', async () => {
  await assert.rejects(runBounded(process.execPath, ['-e', 'process.stdout.write("x".repeat(10000))'], { maxBytes: 100 }), /output exceeded/);
  await assert.rejects(runBounded(process.execPath, ['-e', 'setTimeout(()=>{},10000)'], { timeoutMs: 100 }), /timed out/);
  const controller = new AbortController(); setTimeout(() => controller.abort(), 100);
  await assert.rejects(runBounded(process.execPath, ['-e', 'setTimeout(()=>{},10000)'], { signal: controller.signal }), /cancelled/);
});

test('timeout force-kills a child that ignores SIGTERM', async () => {
  let child;
  await assert.rejects(runBounded(process.execPath, ['-e', 'process.on("SIGTERM",()=>{});setTimeout(()=>{},10000)'], {
    timeoutMs: 300, spawnImpl: (...args) => { child = spawn(...args); return child; },
  }), /timed out/);
  if (child.exitCode === null && !child.signalCode) await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('child survived forced teardown')), 2000);
    child.once('close', () => { clearTimeout(timer); resolve(); });
  });
  assert.ok(child.exitCode !== null || child.signalCode);
});

test('private job child emits one sanitized result and exits despite pending SDK handles', async t => {
  const tmp = await temporary(t);
  await mkdir(path.join(tmp, 'src')); await mkdir(path.join(tmp, 'runtime'));
  for (const name of ['job-runner.mjs', 'host.mjs', 'protocol.mjs', 'process.mjs']) {
    await writeFile(path.join(tmp, 'src', name), await readFile(new URL('../src/' + name, import.meta.url)));
  }
  await writeFile(path.join(tmp, 'runtime', 'salesforce_job_executor.mjs'), `export async function executeJob() { console.log('SDK noise'); setInterval(()=>{},10000); return {stdout:'ok',stderr:'',exitCode:0}; }`);
  const result = await runBounded(process.execPath, [path.join(tmp, 'src', 'job-runner.mjs')], {
    input: JSON.stringify({ execution: {}, workspace: tmp, sfExecutable: process.execPath }) + '\n', timeoutMs: 2000,
  });
  assert.deepEqual(JSON.parse(result.stdout), { stdout: 'ok', stderr: '', exitCode: 0 });
  assert.equal(result.stderr, '');
});

test('obvious auth fields and token forms are removed without logging raw output', () => {
  const text = sanitizeOutput(JSON.stringify({ accessToken: 'secret-a', nested: { password: 'secret-b' }, name: 'Account' }));
  assert.doesNotMatch(text, /secret-a|secret-b/); assert.match(text, /Account/);
  const sample = 'Bearer secret-c force' + '://client:secret@host access_token=secret-d ' + '00D000000000001' + '!secret_e';
  assert.doesNotMatch(sanitizeOutput(sample), /secret-[cd]|secret_e/);
  assert.equal(cleanEnvironment({ NODE_OPTIONS: '--require bad', PythonPath: 'bad', PATH: '/installed' }).PythonPath, undefined);
});

test('resolve executables outside the mutable workspace; ignore relative PATH', async t => {
  const tmp = await temporary(t), root = path.join(tmp, 'workspace'), bin = path.join(tmp, 'installed');
  await mkdir(root); await mkdir(bin);
  const filename = process.platform === 'win32' ? 'sf.exe' : 'sf';
  for (const directory of [root, bin]) { await writeFile(path.join(directory, filename), '#!/bin/sh\nexit 0\n'); await chmod(path.join(directory, filename), 0o755); }
  const actual = await findExecutable('sf', { workspace: root, env: { PATH: ['.', root, bin].join(path.delimiter) } });
  assert.equal(actual, path.join(bin, filename));
});

test('Windows npm shim is resolved to Node entrypoint, never cmd.exe', async t => {
  const tmp = await temporary(t), packageRoot = path.join(tmp, 'node_modules', '@salesforce', 'cli');
  await mkdir(path.join(packageRoot, 'bin'), { recursive: true });
  await writeFile(path.join(tmp, 'sf.cmd'), '@echo off\nmalicious shell text ignored');
  await writeFile(path.join(packageRoot, 'package.json'), JSON.stringify({ name: '@salesforce/cli', bin: { sf: './bin/run.js' } }));
  await writeFile(path.join(packageRoot, 'bin', 'run.js'), '// installed entrypoint');
  const args = ['data', 'query', '-q', 'a&b|c'];
  const resolved = await cliInvocation(path.join(tmp, 'sf.cmd'), args, { platform: 'win32', nodeExecutable: process.execPath });
  assert.equal(resolved.executable, process.execPath);
  assert.deepEqual(resolved.arguments, [path.join(packageRoot, 'bin', 'run.js'), ...args]);
  assert.equal(resolved.env.ELECTRON_RUN_AS_NODE, '1');
  const environment = cleanEnvironment({ Sf_Redirected: '0', LOCALAPPDATA: 'unselected-updated-client' }, { platform: 'win32' });
  assert.equal(environment.SF_REDIRECTED, '1');
  assert.equal(environment.Sf_Redirected, undefined);
  assert.equal(cleanEnvironment({}, { platform: 'linux' }).SF_REDIRECTED, undefined);
  await assert.rejects(cliInvocation(path.join(tmp, 'unsupported.cmd'), [], { platform: 'win32' }).then(result => {
    // Same installation is valid even with an alternate shim name; remove package identity to test denial.
    assert.ok(result.arguments[0]);
    return writeFile(path.join(packageRoot, 'package.json'), '{"name":"unreviewed"}').then(() => cliInvocation(path.join(tmp, 'sf.cmd'), [], { platform: 'win32' }));
  }), /safely on Windows/);
});

test('runtime uses exact packaged bytes and refuses corruption or missing files', async t => {
  const tmp = await temporary(t), repo = path.join(tmp, 'repository'), runtime = path.join(tmp, 'runtime');
  await mkdir(path.join(repo, 'scripts'), { recursive: true });
  for (const name of RUNTIME_FILES) await writeFile(path.join(repo, 'scripts', name), `# ${name}\n`);
  await buildRuntime(repo, runtime); await verifyRuntime(runtime);
  await writeFile(path.join(repo, 'scripts', RUNTIME_FILES[0]), '# mutable workspace changed\n');
  await verifyRuntime(runtime); // Workspace changes are not runtime imports.
  await writeFile(path.join(runtime, RUNTIME_FILES[0]), '# tampered package\n');
  await assert.rejects(verifyRuntime(runtime), /integrity/);
  await buildRuntime(repo, runtime); await rm(path.join(runtime, RUNTIME_FILES[1]));
  await assert.rejects(verifyRuntime(runtime));
});

test('identity/config recheck rejects drift and makes only fixed local inventory command', async t => {
  const tmp = await temporary(t);
  await mkdir(path.join(tmp, 'config'));
  const config = Buffer.from('{"salesforce":{"orgs":[]}}');
  await writeFile(path.join(tmp, 'config', 'harness.local.json'), config);
  const target = { username: 'user@example.test', id: '00D000000000001', host: 'sample.my.salesforce.com', environment: 'prod' };
  const execution = { targets: [target], configDigest: createHash('sha256').update(config).digest('hex') };
  let row = { username: target.username, orgId: target.id + 'AAA', instanceUrl: 'https://' + target.host };
  let calls = 0;
  const executable = path.resolve('/installed/sf.exe');
  const run = async (exe, args) => { calls++; assert.equal(exe, executable); assert.deepEqual(args, ['org', 'list', 'auth', '--json']); return { exitCode: 0, stdout: JSON.stringify({ status: 0, result: [row] }) }; };
  await recheckExecution(execution, tmp, executable, { run });
  row = { ...row, orgId: '00D000000000002AAA' };
  await assert.rejects(recheckExecution(execution, tmp, executable, { run }), /identity changed/);
  assert.equal(calls, 2);
  await writeFile(path.join(tmp, 'config', 'harness.local.json'), '{}');
  await assert.rejects(recheckExecution(execution, tmp, executable, { run }), /Configuration changed/);
  assert.equal(calls, 2);
});

test('native VS Code adapter honors choices and always presents a separate deploy modal', async () => {
  const filename = fileURLToPath(new URL('../src/extension.cjs', import.meta.url));
  const require = createRequire(import.meta.url);
  const calls = [], registrations = [];
  const vscode = {
    CancellationTokenSource: class { constructor() { this.token = {}; } cancel() {} dispose() {} },
    lm: { registerTool: (name, tool) => { registrations.push({ name, tool }); return {}; } },
    window: {
      showInformationMessage: async (message, options, label) => { calls.push({ message, options, label }); return label; },
      showQuickPick: async (items, options) => { calls.push({ items, options }); return items[0]; },
      showWarningMessage: async (message, options, label) => { calls.push({ message, options, label }); return label; },
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(await readFile(filename, 'utf8'), { module, exports: module.exports, require: name => name === 'vscode' ? vscode : require(name), AbortController });
  module.exports.activate({ subscriptions: [] });
  assert.equal(registrations[0].name, 'sf_harness_run_operation');
  assert.match(registrations[0].tool.prepareInvocation().confirmationMessages.message, /does not answer/);
  const ui = module.exports.nativeUi(), controller = new AbortController();
  const target = { username: 'human@example.test', id: '00D000000000001', host: 'sample.my.salesforce.com' };
  assert.equal(await ui.environment({ target, environments: ['prod'], arguments: ['project', 'retrieve', 'start'] }, controller.signal), 'prod');
  assert.equal(calls[0].options.modal, true); assert.match(calls[0].options.detail, /Exact invocation/);
  assert.deepEqual(Array.from(calls[1].items, item => item.label), ['prod']);
  assert.equal(await ui.confirmDeploy({ targets: [target], arguments: ['project', 'deploy', 'start', '-m', 'ApexClass:X'], scope: 'ApexClass:X' }, controller.signal), true);
  assert.equal(calls[2].options.modal, true); assert.match(calls[2].options.detail, /human@example.test/); assert.match(calls[2].options.detail, /ApexClass:X/);
  controller.abort(); assert.equal(await ui.confirmDeploy({ targets: [target], arguments: ['x'], scope: 'x' }, controller.signal), undefined);
  assert.equal(calls.length, 3);
});

test('dependency-free VSIX ZIP is deterministic and excludes traversal', () => {
  const files = [{ name: 'extension/package.json', bytes: Buffer.from('{"name":"sample"}') }];
  assert.deepEqual(createZip(files), createZip(files));
  assert.equal(createZip(files).readUInt32LE(0), 0x04034b50);
  assert.throws(() => createZip([{ name: '../escape', bytes: Buffer.alloc(0) }]), /Invalid archive path/);
});
