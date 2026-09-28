import { createInterface } from 'node:readline';
import { executionDigest } from '../../src/protocol.mjs';
const mode = process.argv[2];
if (mode === 'ignoreTerm') process.on('SIGTERM', () => {});
const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]();
const read = async () => JSON.parse((await lines.next()).value);
const emit = event => process.stdout.write(JSON.stringify(event) + '\n');
const request = await read();
if (Object.keys(request).join() !== 'arguments') process.exit(2);
const target = { username: 'user@example.test', id: '00D000000000001', host: 'example--dev.sandbox.my.salesforce.com', environment: 'dev' };
const execution = { kind: 'cli', arguments: ['project', 'retrieve', 'start', '-o', target.username], targets: [target], configDigest: 'a'.repeat(64) };
const terminal = { type: 'execute', execution, digest: executionDigest(execution) };
if (mode === 'empty') process.exit(0);
if (mode === 'malformed') { process.stdout.write('not-json\n'); process.exit(0); }
if (mode === 'oversize') { process.stdout.write('x'.repeat(1048600)); process.exit(0); }
if (['hang', 'ignoreTerm'].includes(mode)) { setTimeout(() => process.exit(0), 10000); }
else if (mode === 'blocked') { emit({ type: 'blocked', message: 'Known production denied.' }); process.exit(0); }
else {
  if (['dialogs', 'cancel', 'replay', 'prodOnly', 'forgedReply', 'hangDialog'].includes(mode)) {
    const first = { type: 'selectOrg', promptId: 'first', items: [{ ...target, label: 'team-alpha' }], arguments: request.arguments };
    emit(first);
    const response = await read();
    if (response.promptId !== 'first' || response.value !== target.username || Object.keys(response).sort().join() !== 'promptId,value') process.exit(2);
    if (mode === 'replay') { emit(first); await read(); process.exit(2); }
    const environment = { type: 'environment', promptId: 'env', target, environments: mode === 'prodOnly' ? ['prod'] : ['dev', 'uat', 'stage', 'prod'], arguments: request.arguments };
    emit(environment);
    const response2 = await read();
    if (response2.promptId !== 'env' || !environment.environments.includes(response2.value)) process.exit(2);
    emit({ type: 'confirmDeploy', promptId: 'deploy', targets: [target], arguments: request.arguments, scope: '--metadata ApexClass:Sample' });
    const response3 = await read();
    if (response3.promptId !== 'deploy' || response3.value !== true) process.exit(2);
  }
  if (mode === 'badDigest') terminal.digest = 'f'.repeat(64);
  if (mode === 'partial') process.stdout.write(JSON.stringify(terminal));
  else emit(terminal);
  if (mode === 'duplicate') emit(terminal);
  if (mode === 'latePrompt') emit({ type: 'environment', promptId: 'late', target, environments: ['dev'], arguments: request.arguments });
  process.exit(mode === 'crash' ? 2 : 0);
}
