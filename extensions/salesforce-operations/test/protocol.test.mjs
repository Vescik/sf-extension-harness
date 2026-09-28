import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { runSession, validateInput, executionDigest } from '../src/protocol.mjs';

const fixture = fileURLToPath(new URL('./fixtures/worker.mjs', import.meta.url));
const input = { arguments: ['project', 'deploy', 'start', '-m', 'ApexClass:Sample'] };
function service(mode, overrides = {}) {
  const calls = { launch: 0, dispatch: 0, before: 0, ui: [] };
  const services = {
    contextValid: () => true,
    launchWorker: () => { calls.launch++; return spawn(process.execPath, [fixture, mode], { stdio: ['pipe', 'pipe', 'pipe'] }); },
    ui: {
      selectOrg: async () => { calls.ui.push('org'); return 'user@example.test'; },
      environment: async () => { calls.ui.push('environment'); return 'dev'; },
      confirmDeploy: async () => { calls.ui.push('deploy'); return true; },
    },
    beforeExecute: async () => { calls.before++; },
    execute: async () => { calls.dispatch++; return { status: 'completed' }; },
    ...overrides,
  };
  return { calls, services };
}

test('only model arguments accepted; forged consent/environment fields never start worker', async () => {
  for (const bad of [{ ...input, environment: 'dev' }, { ...input, approved: true }, { arguments: [] },
    { arguments: ['x\ny'] }, { arguments: ['x'.repeat(8193)] }, { arguments: Array(129).fill('x') }]) {
    const { calls, services } = service('success');
    await assert.rejects(runSession(bad, services));
    assert.equal(calls.launch, 0); assert.equal(calls.dispatch, 0);
  }
  assert.deepEqual(validateInput({ arguments: ['data', 'query', '-q', 'SELECT Id FROM Account'] }), ['data', 'query', '-q', 'SELECT Id FROM Account']);
});

test('native org/environment/deploy dialogs all run despite generic tool preapproval', async () => {
  const { calls, services } = service('dialogs');
  assert.deepEqual(await runSession(input, services), { status: 'completed' });
  assert.deepEqual(calls.ui, ['org', 'environment', 'deploy']);
  assert.equal(calls.before, 1); assert.equal(calls.dispatch, 1);
});

test('no authority or digest returned to the model result', async () => {
  const { services } = service('success');
  const result = await runSession(input, services);
  assert.equal(JSON.stringify(result).includes('execution'), false);
  assert.equal(JSON.stringify(result).includes('digest'), false);
});

for (const mode of ['empty', 'malformed', 'oversize', 'partial', 'crash', 'duplicate', 'latePrompt', 'badDigest', 'replay']) {
  test(`${mode} worker response dispatches nothing`, async () => {
    const { calls, services } = service(mode);
    await assert.rejects(runSession(input, services));
    assert.equal(calls.dispatch, 0);
  });
}

test('known production blocked result never requests UI or dispatches', async () => {
  const { calls, services } = service('blocked');
  assert.equal((await runSession(input, services)).status, 'blocked');
  assert.equal(calls.dispatch, 0); assert.deepEqual(calls.ui, []);
});

test('cancel each native dialog independently', async () => {
  for (const dialog of ['selectOrg', 'environment', 'confirmDeploy']) {
    const { calls, services } = service('dialogs');
    services.ui[dialog] = async () => undefined;
    await assert.rejects(runSession(input, services), /cancelled/);
    assert.equal(calls.dispatch, 0);
  }
});

test('environment choice must belong to the worker allowlist', async () => {
  const { calls, services } = service('prodOnly');
  await assert.rejects(runSession(input, services), /cancelled/);
  assert.equal(calls.dispatch, 0);
});

test('trust/root drift during native confirmation stops execution', async () => {
  let trusted = true;
  const { calls, services } = service('dialogs', { contextValid: () => trusted });
  services.ui.environment = async () => { trusted = false; return 'dev'; };
  await assert.rejects(runSession(input, services), /trust or root changed/);
  assert.equal(calls.dispatch, 0);
});

test('identity/configuration failure after clean worker EOF stops dispatch', async () => {
  const { calls, services } = service('success', { beforeExecute: async () => { throw new Error('drift'); } });
  await assert.rejects(runSession(input, services), /drift/);
  assert.equal(calls.dispatch, 0);
});

test('session timeout terminates both waiting worker and unresolved native dialog', async () => {
  for (const mode of ['hang', 'hangDialog', 'ignoreTerm']) {
    const { calls, services } = service(mode);
    services.ui.selectOrg = () => new Promise(() => {});
    await assert.rejects(runSession(input, services, { timeoutMs: 200 }), /cancelled|timed out/);
    assert.equal(calls.dispatch, 0);
  }
});

test('cancel token before invocation creates no worker', async () => {
  const controller = new AbortController(); controller.abort();
  const { calls, services } = service('success');
  await assert.rejects(runSession(input, services, { signal: controller.signal }));
  assert.equal(calls.launch, 0);
});

test('dispatch failure is marked separately from a pre-dispatch denial', async () => {
  const { services } = service('success', { execute: async () => { throw new Error('network result unknown'); } });
  await assert.rejects(runSession(input, services), error => error.dispatched === true);
});

test('digest canonicalization escapes non-ASCII compatibly with Python', () => {
  assert.equal(executionDigest({ b: 'ż', a: [true, null, 2] }), '3082f91c745673fa4b0567157aeb662b7ed7d479ae93e7c5c7a45f5cfce009fc');
});
