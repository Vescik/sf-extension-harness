const vscode = require('vscode');
const fs = require('node:fs');
const path = require('node:path');

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  if (!vscode.workspace.isTrusted || vscode.env.remoteName || folders?.length !== 1 || folders[0].uri.scheme !== 'file') return undefined;
  const root = fs.realpathSync(folders[0].uri.fsPath);
  if (!fs.existsSync(path.join(root, 'sfdx-project.json'))) return undefined;
  return root;
}

function withToken(signal, action) {
  const source = new vscode.CancellationTokenSource();
  const cancel = () => source.cancel();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) source.cancel();
  return Promise.resolve(action(source.token)).finally(() => { signal.removeEventListener('abort', cancel); source.dispose(); });
}

const invocation = event => `sf ${event.arguments.map(x => JSON.stringify(x)).join(' ')}`;
async function reviewInvocation(event, signal, choice) {
  if (signal.aborted) return false;
  const answer = await vscode.window.showInformationMessage('Review this Salesforce invocation', {
    modal: true,
    detail: `Exact invocation:\n${invocation(event)}\n\n${event.target ? `Target: ${event.target.username} · ${event.target.id} · ${event.target.host}\n\n` : ''}This review does not approve a deployment. Any required deployment confirmation follows separately.`,
  }, choice);
  return !signal.aborted && answer === choice;
}
function nativeUi() {
  return {
    selectOrg: (event, signal) => withToken(signal, async token => {
      if (!await reviewInvocation(event, signal, 'Choose target')) return undefined;
      const selected = await vscode.window.showQuickPick(event.items.map(item => ({
        label: item.label || item.username, description: `${item.id} · ${item.host}`, detail: item.username, username: item.username,
      })), { title: `Salesforce: select ${event.purpose || 'the org'} for this operation`, placeHolder: invocation(event), ignoreFocusOut: true }, token);
      return selected?.username;
    }),
    environment: (event, signal) => withToken(signal, async token => {
      if (!await reviewInvocation(event, signal, 'Choose environment')) return undefined;
      const choices = [
        { label: 'dev', description: 'Development' }, { label: 'uat', description: 'Acceptance testing' },
        { label: 'stage', description: 'Pre-production' }, { label: 'prod', description: 'Production: verified metadata retrieve only through CLI' },
      ];
      const selected = await vscode.window.showQuickPick(choices.filter(x => event.environments.includes(x.label)).map(x => ({ ...x,
        detail: `${event.target.username} · ${event.target.id} · ${event.target.host}`,
      })), { title: 'Classify this org for this operation only', placeHolder: invocation(event), ignoreFocusOut: true }, token);
      return selected?.label;
    }),
    confirmDeploy: async (event, signal) => {
      if (signal.aborted) return undefined;
      const answer = await vscode.window.showWarningMessage('Deploy changes to Salesforce?', {
        modal: true,
        detail: `Changes will be deployed to:\n${event.targets.map(t => `${t.username} · ${t.id} · ${t.host}`).join('\n')}\n\nScope: ${event.scope}\n\nExact invocation:\n${invocation(event)}`,
      }, 'Deploy this invocation');
      return !signal.aborted && answer === 'Deploy this invocation' ? true : undefined;
    },
  };
}

function activate(context) {
  let active = false;
  context.subscriptions.push(vscode.lm.registerTool('sf_harness_run_operation', {
    prepareInvocation() {
      return { invocationMessage: 'Assessing one Salesforce operation', confirmationMessages: {
        title: 'Assess Salesforce operation', message: 'Native target/environment selection and a separate real-deployment confirmation are required when applicable. Allowing this tool does not answer those dialogs.',
      } };
    },
    async invoke(options, token) {
      const root = workspaceRoot();
      if (!root) throw new Error('Open one trusted local Salesforce workspace.');
      if (active) throw new Error('Another Salesforce operation is active. Finish or cancel it first.');
      active = true;
      const controller = new AbortController();
      const cancellation = token.onCancellationRequested(() => controller.abort());
      if (token.isCancellationRequested) controller.abort();
      try {
        const { nativeOperation, sanitizeOutput } = await import('./host.mjs');
        const result = await nativeOperation(options.input, {
          workspace: root, extensionRoot: context.extensionPath, ui: nativeUi(), signal: controller.signal,
          contextValid: () => { try { return workspaceRoot() === root; } catch { return false; } },
        });
        return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(sanitizeOutput(JSON.stringify(result)))]);
      } catch (error) {
        // No output channels, telemetry, tokens, worker stderr or authority are retained.
        const { sanitizeOutput } = await import('./host.mjs');
        return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(JSON.stringify({ status: error.dispatched ? 'failed' : 'blocked', message: sanitizeOutput(error.message).slice(0, 8192) }))]);
      } finally { cancellation.dispose(); active = false; }
    },
  }));
}

module.exports = { activate, workspaceRoot, nativeUi };
