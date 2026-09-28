import { createInterface } from 'node:readline';
import { createHash } from 'node:crypto';
import { terminateProcess } from './process.mjs';

export const LIMITS = Object.freeze({ argumentBytes: 32768, protocolBytes: 1048576, resultBytes: 1048576, sessionMs: 300000, executionMs: 600000 });

export function validateInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).length !== 1 || !Object.hasOwn(input, 'arguments') ||
      !Array.isArray(input.arguments) || input.arguments.length < 1 || input.arguments.length > 128 ||
      input.arguments.some(x => typeof x !== 'string' || !x || x.length > 8192 || /[\0\r\n]/.test(x)) ||
      Buffer.byteLength(JSON.stringify(input.arguments)) > LIMITS.argumentBytes) {
    throw new Error('Invalid operation input: supply only a bounded arguments array.');
  }
  return [...input.arguments];
}

const text = value => typeof value === 'string' && value.length > 0 && value.length <= 8192 && !/[\0\r\n]/.test(value);
export function validateTarget(target) {
  return target && typeof target === 'object' && text(target.username) &&
    typeof target.id === 'string' && /^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$/.test(target.id) &&
    typeof target.host === 'string' && /^[a-z0-9.-]+$/i.test(target.host) && target.host.endsWith('.salesforce.com');
}

export function executionDigest(execution) {
  const canonical = value => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
    return value;
  };
  const bytes = JSON.stringify(canonical(execution)).replace(/[\u0080-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  return createHash('sha256').update(bytes).digest('hex');
}

function validExecution(execution, digest) {
  if (!execution || !['cli', 'job'].includes(execution.kind) || !/^[a-f0-9]{64}$/.test(digest ?? '') ||
      !/^[a-f0-9]{64}$/.test(execution.configDigest ?? '') ||
      !Array.isArray(execution.targets) || execution.targets.length > 16 ||
      !execution.targets.every(validateTarget)) return false;
  const expectedKeys = ['arguments', 'configDigest', 'kind', 'targets', ...(execution.kind === 'job' ? ['job'] : [])].sort();
  if (JSON.stringify(Object.keys(execution).sort()) !== JSON.stringify(expectedKeys) || executionDigest(execution) !== digest ||
      execution.targets.some(target => !['dev', 'uat', 'stage', 'prod'].includes(target.environment))) return false;
  try { validateInput({ arguments: execution.arguments }); } catch { return false; }
  return execution.kind !== 'job' || (execution.job && typeof execution.job === 'object');
}

/** Host-only protocol. Execution waits for clean EOF; any duplicate or late event invalidates it. */
export async function runSession(input, services, { signal, timeoutMs = LIMITS.sessionMs } = {}) {
  const args = validateInput(input);
  if (!services.contextValid()) throw new Error('A single trusted local Salesforce workspace is required.');
  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) abort.abort();
  const timer = setTimeout(cancel, timeoutMs);
  let child;
  let terminal;
  let protocolFault = false;
  let bytes = 0;
  let newlineTerminated = true;
  let closePromise;
  let lines;
  let kill;
  const prompts = new Set();
  const ask = async operation => {
    let listener;
    const cancelled = new Promise((_, reject) => {
      listener = () => reject(new Error('Operation cancelled or assessment timed out; no command dispatched.'));
      abort.signal.addEventListener('abort', listener, { once: true });
      if (abort.signal.aborted) listener();
    });
    try { return await Promise.race([operation(), cancelled]); }
    finally { abort.signal.removeEventListener('abort', listener); }
  };
  const check = () => {
    if (abort.signal.aborted) throw new Error('Operation cancelled or assessment timed out; no command dispatched.');
    if (!services.contextValid()) throw new Error('Workspace trust or root changed; no command dispatched.');
  };
  try {
    check();
    child = await services.launchWorker(abort.signal);
    check();
    closePromise = new Promise(resolve => {
      child.once('close', (code, closeSignal) => resolve({ code, signal: closeSignal }));
      child.once('error', () => { protocolFault = true; resolve({ code: null }); child.kill(); });
    });
    kill = () => { lines?.close(); terminateProcess(child); };
    abort.signal.addEventListener('abort', kill, { once: true });
    child.stdin.on('error', () => { protocolFault = true; cancel(); });
    child.stderr.on('data', chunk => {
      // Worker diagnostics are neither logged nor exposed: they could contain auth material.
      bytes += chunk.length;
      if (bytes > LIMITS.protocolBytes) { protocolFault = true; cancel(); }
    });
    child.stdout.on('data', chunk => {
      bytes += chunk.length;
      newlineTerminated = chunk.at(-1) === 10;
      if (bytes > LIMITS.protocolBytes) { protocolFault = true; cancel(); }
    });
    child.stdin.write(JSON.stringify({ arguments: args }) + '\n');
    lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
    for await (const line of lines) {
      check();
      if (terminal || !line || Buffer.byteLength(line) > LIMITS.protocolBytes) throw new Error('Invalid operation session protocol.');
      let event;
      try { event = JSON.parse(line); } catch { throw new Error('Invalid operation session protocol.'); }
      if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('Invalid operation session protocol.');
      if (event.type === 'execute') {
        if (!validExecution(event.execution, event.digest)) throw new Error('Invalid execution assessment.');
        terminal = event;
        continue;
      }
      if (event.type === 'blocked') {
        terminal = { type: 'blocked', message: text(event.message) ? event.message : 'Operation denied.' };
        continue;
      }
      if (!['selectOrg', 'environment', 'confirmDeploy'].includes(event.type) || !text(event.promptId) || prompts.has(event.promptId)) {
        throw new Error('Invalid or replayed operation prompt.');
      }
      prompts.add(event.promptId);
      validateInput({ arguments: event.arguments });
      let value;
      if (event.type === 'selectOrg') {
        if (!Array.isArray(event.items) || !event.items.length || event.items.length > 500 || !event.items.every(validateTarget) ||
            new Set(event.items.map(x => x.username)).size !== event.items.length) throw new Error('Invalid target choices.');
        value = await ask(() => services.ui.selectOrg(event, abort.signal));
        if (!event.items.some(x => x.username === value)) value = undefined;
      } else if (event.type === 'environment') {
        if (!validateTarget(event.target) || !Array.isArray(event.environments) || !event.environments.length ||
            event.environments.some(x => !['dev', 'uat', 'stage', 'prod'].includes(x))) throw new Error('Invalid environment target.');
        value = await ask(() => services.ui.environment(event, abort.signal));
        if (!event.environments.includes(value)) value = undefined;
      } else {
        const targets = event.targets ?? (event.target ? [event.target] : []);
        if (!targets.length || !targets.every(validateTarget) || typeof event.scope !== 'string') throw new Error('Invalid deployment confirmation.');
        value = await ask(() => services.ui.confirmDeploy({ ...event, targets }, abort.signal));
        if (value !== true) value = undefined;
      }
      check();
      if (value === undefined) { cancel(); check(); }
      child.stdin.write(JSON.stringify({ promptId: event.promptId, value }) + '\n');
    }
    const closed = await ask(() => closePromise);
    check();
    if (protocolFault || !newlineTerminated || closed.code !== 0 || closed.signal || !terminal) throw new Error('Operation session ended without a valid assessment.');
    if (terminal.type === 'blocked') return { status: 'blocked', message: terminal.message };
    await ask(() => services.beforeExecute(terminal.execution, abort.signal));
    check();
    // This is the sole dispatch point; neither the event nor its digest is returned to a model.
    clearTimeout(timer);
    try { return await services.execute(terminal.execution, abort.signal); }
    catch (error) { error.dispatched = true; throw error; }
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
    if (kill) abort.signal.removeEventListener('abort', kill);
    lines?.close();
    if (child && child.exitCode === null) terminateProcess(child);
  }
}
