// Private packaged process entrypoint. Never exposed as a model tool or workspace command.
import { executeJob } from '../runtime/salesforce_job_executor.mjs';
import { LIMITS } from './protocol.mjs';
import { sanitizeOutput } from './host.mjs';

const controller = new AbortController();
const writeResult = process.stdout.write.bind(process.stdout);
// SDK diagnostics can carry auth data. The private protocol has exactly one result frame.
process.stdout.write = () => true;
process.stderr.write = () => true;
const finish = result => writeResult(JSON.stringify(result) + '\n', () => process.exit(0));
process.on('SIGTERM', () => { controller.abort(); process.exit(2); });
let length = 0;
const chunks = [];
try {
  for await (const chunk of process.stdin) {
    length += chunk.length;
    if (length > LIMITS.protocolBytes) throw new Error('input bound');
    chunks.push(chunk);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (!request || Object.keys(request).sort().join() !== 'execution,sfExecutable,workspace' ||
      typeof request.workspace !== 'string' || typeof request.sfExecutable !== 'string') throw new Error('input shape');
  const result = await executeJob(request.execution, { workspace: request.workspace, sfExecutable: request.sfExecutable,
    signal: controller.signal, maxOutputBytes: LIMITS.resultBytes });
  const output = JSON.stringify({ stdout: sanitizeOutput(result.stdout), stderr: sanitizeOutput(result.stderr), exitCode: result.exitCode });
  if (Buffer.byteLength(output) > LIMITS.resultBytes) throw new Error('output bound');
  finish(JSON.parse(output));
} catch {
  // SDK exception objects can contain connection/auth details; only a fixed diagnosis crosses IPC.
  finish({ stdout: '', stderr: 'Selected job could not complete; inspect its state before retrying.', exitCode: 2 });
}
