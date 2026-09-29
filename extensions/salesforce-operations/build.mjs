import { readFile, writeFile, mkdir, mkdtemp, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

export const RUNTIME_FILES = Object.freeze([
  'salesforce_operation_session.py', 'salesforce_operation_policy.py', 'verify_salesforce_org.py',
  'copilot_safety_hook.py', 'git_workflow_policy.py', 'salesforce_job_selection.py', 'salesforce_job_executor.mjs',
]);
const extensionRoot = path.dirname(fileURLToPath(import.meta.url));
export async function buildRuntime(repositoryRoot = path.resolve(extensionRoot, '../..'), destination = path.join(extensionRoot, 'runtime')) {
  const sources = await Promise.all(RUNTIME_FILES.map(async name => ({ name, bytes: await readFile(path.join(repositoryRoot, 'scripts', name)) })));
  await mkdir(path.dirname(destination), { recursive: true });
  const temporary = await mkdtemp(path.join(path.dirname(destination), '.runtime-build-'));
  try {
    const files = [];
    for (const source of sources) {
      await writeFile(path.join(temporary, source.name), source.bytes);
      files.push({ path: source.name, sha256: createHash('sha256').update(source.bytes).digest('hex') });
    }
    await writeFile(path.join(temporary, 'source-manifest.json'), JSON.stringify({ schemaVersion: 1, files }, null, 2) + '\n');
    await rm(destination, { recursive: true, force: true });
    await rename(temporary, destination);
    return files;
  } finally { await rm(temporary, { recursive: true, force: true }); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const files = await buildRuntime();
  process.stdout.write(`Built ${files.length} reviewed runtime files.\n`);
}
