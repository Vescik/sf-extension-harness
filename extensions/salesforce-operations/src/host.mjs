import { spawn } from 'node:child_process';
import { access, readFile, realpath, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { LIMITS, runSession, validateInput } from './protocol.mjs';
import { terminateProcess } from './process.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const contained = (root, candidate) => candidate === root || candidate.startsWith(root + path.sep);
export function cleanEnvironment(env = process.env, { platform = process.platform } = {}) {
  const result = { ...env, FORCE_COLOR: '0', NO_COLOR: '1', CLICOLOR: '0', CLICOLOR_FORCE: '0',
    SF_TEMP_SHOW_SECRETS: 'false', SF_AUTOUPDATE_DISABLE: 'true', SF_DISABLE_TELEMETRY: 'true', PYTHONUTF8: '1' };
  for (const name of Object.keys(result)) {
    if (['NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME'].includes(name.toUpperCase())) delete result[name];
    if (platform === 'win32' && name.toUpperCase() === 'SF_REDIRECTED') delete result[name];
  }
  // Official Windows sf.cmd may redirect to a per-user updated client. Inventory and
  // execution must use the same adjacent installation resolved by cliInvocation.
  if (platform === 'win32') result.SF_REDIRECTED = '1';
  return result;
}

export async function findExecutable(name, { env = process.env, platform = process.platform, workspace } = {}) {
  const suffixes = platform === 'win32' ? ['.exe', '.cmd', '.bat', ''] : [''];
  const directories = String(env.PATH ?? env.Path ?? '').split(platform === 'win32' ? ';' : ':');
  if (platform !== 'win32') directories.push('/usr/local/bin', '/opt/homebrew/bin', '/usr/bin');
  const root = workspace && await realpath(workspace);
  for (const directory of [...new Set(directories)]) {
    if (!directory || !path.isAbsolute(directory)) continue;
    for (const suffix of suffixes) {
      try {
        const candidate = await realpath(path.join(directory, name + suffix));
        if (root && contained(root, candidate)) continue;
        if (!(await stat(candidate)).isFile()) continue;
        await access(candidate, platform === 'win32' ? constants.F_OK : constants.X_OK);
        return candidate;
      } catch { /* Continue through fixed executable candidates. */ }
    }
  }
  throw new Error(`Installed ${name} executable is unavailable outside the workspace.`);
}

/** Windows npm cmd shims never receive arbitrary arguments through cmd.exe. */
export async function cliInvocation(sfExecutable, args, { platform = process.platform, nodeExecutable = process.execPath } = {}) {
  if (!path.isAbsolute(sfExecutable)) throw new Error('Salesforce executable must be absolute.');
  if (platform !== 'win32' || /\.exe$/i.test(sfExecutable)) return { executable: sfExecutable, arguments: args, env: {} };
  if (!/\.(cmd|bat)$/i.test(sfExecutable)) throw new Error('Unsupported Windows Salesforce launcher.');
  const directory = path.dirname(sfExecutable);
  for (const packageRoot of [path.join(directory, 'node_modules', '@salesforce', 'cli'), path.resolve(directory, '..')]) {
    try {
      const manifest = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
      if (manifest.name !== '@salesforce/cli') continue;
      const entry = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.sf;
      if (typeof entry !== 'string' || path.isAbsolute(entry)) continue;
      const root = await realpath(packageRoot);
      const script = await realpath(path.resolve(root, entry));
      if (!contained(root, script) || !/\.(m?js|cjs)$/i.test(script)) continue;
      return { executable: nodeExecutable, arguments: [script, ...args], env: { ELECTRON_RUN_AS_NODE: '1' } };
    } catch { /* Do not parse or execute the shell shim itself. */ }
  }
  throw new Error('Cannot resolve the installed Salesforce Node entrypoint safely on Windows.');
}

export async function runBounded(executable, args, {
  cwd, env = cleanEnvironment(), signal, timeoutMs = LIMITS.executionMs,
  maxBytes = LIMITS.resultBytes, spawnImpl = spawn,
  input,
} = {}) {
  if (signal?.aborted) throw new Error('Operation cancelled before dispatch.');
  return await new Promise((resolve, reject) => {
    let finished = false;
    let size = 0;
    const output = { stdout: [], stderr: [] };
    const child = spawnImpl(executable, args, { cwd, env, shell: false, windowsHide: true, stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'] });
    const stop = message => {
      if (finished) return;
      finished = true;
      terminateProcess(child);
      cleanup();
      reject(new Error(message));
    };
    const cancel = () => stop('Operation cancelled. A command already dispatched may have started; inspect its result before retrying.');
    const timer = setTimeout(() => stop('Execution timed out; inspect the operation before retrying.'), timeoutMs);
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', cancel); };
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) cancel();
    for (const name of ['stdout', 'stderr']) child[name].on('data', chunk => {
      size += chunk.length;
      if (size > maxBytes) stop('Execution output exceeded the bound; output was discarded.');
      else output[name].push(chunk);
    });
    child.on('error', () => stop('Unable to start the reviewed executable.'));
    if (input !== undefined) {
      child.stdin.on('error', () => stop('Private executor input was rejected.'));
      child.stdin.end(input);
    }
    child.on('close', (code, closeSignal) => {
      if (finished) return;
      finished = true; cleanup();
      if (closeSignal) return reject(new Error('Execution ended unexpectedly; inspect the operation before retrying.'));
      resolve({ stdout: Buffer.concat(output.stdout).toString('utf8'), stderr: Buffer.concat(output.stderr).toString('utf8'), exitCode: code ?? 1 });
    });
  });
}

export function sanitizeOutput(value) {
  const secrets = /^(access.?token|refresh.?token|authorization|password|client.?secret|sfdxauthurl|private.?key)$/i;
  const scrub = obj => {
    if (Array.isArray(obj)) return obj.map(scrub);
    if (obj && typeof obj === 'object') return Object.fromEntries(Object.entries(obj).map(([key, item]) => [key, secrets.test(key) ? '[REDACTED]' : scrub(item)]));
    return obj;
  };
  let result = String(value ?? '');
  try { result = JSON.stringify(scrub(JSON.parse(result))); } catch { /* Plain CLI diagnostics remain text. */ }
  return result.replace(/Bearer\s+[^\s"',]+/gi, 'Bearer [REDACTED]')
    .replace(/force:\/\/[^\s"']+/gi, '[REDACTED AUTH URL]')
    .replace(/\b00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?![A-Za-z0-9._-]+/g, '[REDACTED TOKEN]')
    .replace(/((?:access.?token|refresh.?token|password|client.?secret)\s*[:=]\s*)[^\s,;]+/gi, '$1[REDACTED]');
}

export async function verifyRuntime(runtimeRoot) {
  const manifest = JSON.parse(await readFile(path.join(runtimeRoot, 'source-manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || !Array.isArray(manifest.files) || !manifest.files.length) throw new Error('Packaged runtime manifest is invalid.');
  const root = await realpath(runtimeRoot);
  const required = new Set(['salesforce_operation_session.py', 'salesforce_operation_policy.py', 'verify_salesforce_org.py',
    'copilot_safety_hook.py', 'salesforce_job_selection.py', 'salesforce_job_executor.mjs']);
  for (const item of manifest.files) {
    if (!required.has(item.path) || !/^[a-f0-9]{64}$/.test(item.sha256 ?? '')) throw new Error('Packaged runtime manifest is invalid.');
    required.delete(item.path);
    const file = await realpath(path.join(root, item.path));
    if (!contained(root, file) || hash(await readFile(file)) !== item.sha256) throw new Error('Packaged runtime integrity check failed. Rebuild the reviewed extension.');
  }
  if (required.size) throw new Error('Packaged runtime is incomplete.');
}

export async function findPython(workspace, env = process.env) {
  const candidates = [path.join(workspace, '.venv', 'bin', 'python'), path.join(workspace, '.venv', 'Scripts', 'python.exe')];
  for (const name of ['python3', 'python']) {
    try { candidates.push(await findExecutable(name, { env, workspace })); } catch { /* Try next fixed candidate. */ }
  }
  for (const candidate of [...new Set(candidates)]) {
    try {
      if (!(await stat(candidate)).isFile()) continue;
      const result = await runBounded(candidate, ['-E', '-s', '-B', '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'],
        { cwd: workspace, env: cleanEnvironment(env), timeoutMs: 3000, maxBytes: 8192 });
      if (result.exitCode === 0) return candidate;
    } catch { /* Probe errors disclose no interpreter diagnostics. */ }
  }
  throw new Error('Python 3.11+ is required in the workspace .venv or installed PATH.');
}

export async function recheckExecution(execution, workspace, sfExecutable, { signal, run = runBounded, environment = process.env } = {}) {
  const current = await readFile(path.join(workspace, 'config', 'harness.local.json'));
  if (hash(current) !== execution.configDigest) throw new Error('Configuration changed after assessment; no command dispatched.');
  if (!execution.targets.length) return; // Local help/version has no org target.
  const invocation = await cliInvocation(sfExecutable, ['org', 'list', 'auth', '--json']);
  const result = await run(invocation.executable, invocation.arguments, {
    cwd: workspace, signal, timeoutMs: 5000, maxBytes: LIMITS.resultBytes, env: { ...cleanEnvironment(environment), ...invocation.env },
  });
  let data;
  try { data = JSON.parse(result.stdout); } catch { throw new Error('Identity recheck failed; no command dispatched.'); }
  if (result.exitCode !== 0 || data.status !== 0 || !Array.isArray(data.result)) throw new Error('Identity recheck failed; no command dispatched.');
  for (const target of execution.targets) {
    const rows = data.result.filter(row => row.username === target.username);
    if (!rows.length || rows.some(row => {
      try {
        const url = new URL(row.instanceUrl);
        return row.error || String(row.orgId ?? row.id).slice(0, 15) !== target.id.slice(0, 15) ||
          url.protocol !== 'https:' || url.username || url.password || url.port ||
          url.hostname.toLowerCase() !== target.host.toLowerCase() || !['', '/'].includes(url.pathname) || url.search || url.hash;
      } catch { return true; }
    })) throw new Error('Authorized target identity changed; no command dispatched.');
  }
  if (hash(await readFile(path.join(workspace, 'config', 'harness.local.json'))) !== execution.configDigest) {
    throw new Error('Configuration changed during identity recheck; no command dispatched.');
  }
}

export async function nativeOperation(input, { workspace, extensionRoot, ui, contextValid, signal, env = process.env }) {
  validateInput(input); // Reject forged model input before probing any executable or org inventory.
  const runtimeRoot = path.join(extensionRoot, 'runtime');
  await verifyRuntime(runtimeRoot);
  const python = await findPython(workspace, env);
  const sfExecutable = await findExecutable('sf', { env, workspace });
  const childEnv = cleanEnvironment(env);
  // Worker and executor resolve the same installed CLI directory, never workspace scripts.
  childEnv.PATH = path.dirname(sfExecutable) + path.delimiter + (childEnv.PATH ?? '');
  return await runSession(input, {
    contextValid, ui,
    launchWorker: () => spawn(python, ['-E', '-s', '-B', path.join(runtimeRoot, 'salesforce_operation_session.py'), '--workspace', workspace],
      { cwd: workspace, env: childEnv, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] }),
    beforeExecute: async (execution, abortSignal) => {
      await verifyRuntime(runtimeRoot);
      await recheckExecution(execution, workspace, sfExecutable, { signal: abortSignal, environment: childEnv });
    },
    execute: async (execution, abortSignal) => {
      let result;
      if (execution.kind === 'job') {
        const child = await runBounded(process.execPath, [path.join(extensionRoot, 'src', 'job-runner.mjs')], {
          cwd: workspace, signal: abortSignal, env: { ...childEnv, ELECTRON_RUN_AS_NODE: '1' },
          input: JSON.stringify({ execution, workspace, sfExecutable }) + '\n',
        });
        if (child.exitCode !== 0) throw new Error('Job executor failed; inspect the selected job before retrying.');
        try { result = JSON.parse(child.stdout); } catch { throw new Error('Job executor returned an invalid result.'); }
        if (!result || typeof result.stdout !== 'string' || typeof result.stderr !== 'string' || !Number.isInteger(result.exitCode)) {
          throw new Error('Job executor returned an invalid result.');
        }
      } else {
        const invocation = await cliInvocation(sfExecutable, execution.arguments);
        result = await runBounded(invocation.executable, invocation.arguments,
          { cwd: workspace, signal: abortSignal, env: { ...childEnv, ...invocation.env } });
      }
      if (Buffer.byteLength(String(result.stdout ?? '') + String(result.stderr ?? '')) > LIMITS.resultBytes) throw new Error('Execution output exceeded the bound.');
      return { status: result.exitCode === 0 ? 'completed' : 'failed', exitCode: result.exitCode,
        stdout: sanitizeOutput(result.stdout), stderr: sanitizeOutput(result.stderr) };
    },
  }, { signal });
}
