// Run only with VS Code --extensionTestsPath, in disposable user/extensions directories.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const childProcess = require('node:child_process');
const { syncBuiltinESMExports } = require('node:module');
const vscode = require('vscode');

exports.run = async function () {
  const extension = vscode.extensions.getExtension('sf-harness.salesforce-operations');
  assert.ok(extension, 'development extension manifest discovered');
  const declared = extension.packageJSON.contributes.languageModelTools;
  assert.equal(declared.length, 1);
  assert.equal(declared[0].name, 'sf_harness_run_operation');
  assert.equal(declared[0].toolReferenceName, 'salesforceOperation');
  let nativeSpawns = 0;
  let unrelatedSpawns = 0;
  const original = childProcess.spawn;
  childProcess.spawn = () => {
    const caller = new Error().stack?.split('\n')[2] ?? '';
    if (/[/\\]src[/\\](?:host|job-runner)\.mjs:/.test(caller)) nativeSpawns++;
    else unrelatedSpawns++;
    // Built-in extensions can attempt background Git discovery in this same host.
    // Block every attempt, but distinguish those from this extension's direct calls.
    throw new Error('Smoke forbids external processes');
  };
  syncBuiltinESMExports();
  try {
    await extension.activate();
    assert.ok(extension.isActive, 'extension activates');
    assert.ok(vscode.lm.tools.some(tool => tool.name === 'sf_harness_run_operation'), 'native LM tool registered');
    let result;
    try {
      result = await vscode.lm.invokeTool('sf_harness_run_operation', {
        input: { arguments: ['--version'], approved: true }, toolInvocationToken: undefined,
      }, new vscode.CancellationTokenSource().token);
    } catch (error) {
      // VS Code may reject the schema before invoking the extension; both paths must deny.
      assert.match(String(error), /input|argument|schema|additional|Invalid/i);
    }
    if (result) {
      const output = result.content.map(part => part.value ?? '').join('');
      assert.match(output, /Invalid operation input/);
      assert.match(output, /blocked/);
    }
    assert.equal(nativeSpawns, 0, 'forged input never probes Python, auth inventory or Salesforce');
    const report = { status: 'passed', manifest: true, activation: true, registration: true, invalidInputDenied: true,
      nativeProcessAttempts: nativeSpawns, unrelatedProcessAttempts: unrelatedSpawns, spawnedProcesses: 0 };
    if (process.env.SF_HARNESS_SMOKE_REPORT) fs.writeFileSync(process.env.SF_HARNESS_SMOKE_REPORT, JSON.stringify(report) + '\n');
    console.log('Native activation smoke passed; no Salesforce calls.');
  } finally { childProcess.spawn = original; syncBuiltinESMExports(); }
};
