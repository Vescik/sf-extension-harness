# Salesforce Harness Operations

This local VS Code extension exposes `sf_harness_run_operation` (`#salesforceOperation`) for
the harness Developer agent. It owns native org/environment selection, a separate modal for
every real deployment, and exactly one command dispatch after successful assessment.
The model can supply only Salesforce arguments; it cannot supply an environment, approval,
role, worker response or continuation token. VS Code's generic tool “Always Allow” does not
answer these native dialogs.
Before a native target or environment choice, a modal shows the complete exact invocation.
Continuing that review does not approve a deployment; deployment has its own confirmation.

Use a single trusted local Salesforce workspace, the harness custom Developer agent and
Python 3.11+ in `.venv` or installed PATH. Salesforce CLI must be installed outside the workspace.
Remote/virtual/multi-root workspaces are refused. Other roles retain their hook restrictions;
the stable language-model API does not attest a caller role, so this extension does not claim
independent role authentication. Built-in/default Agent mode is unsupported.

## Build and install

From the repository root, with Node 22+:

```sh
node --test extensions/salesforce-operations/test/*.test.mjs
node extensions/salesforce-operations/build.mjs
node extensions/salesforce-operations/package.mjs
```

No npm install or external packaging dependency is needed. The package command creates
`extensions/salesforce-operations/dist/salesforce-operations-0.1.0.vsix`. Inspect the source
and tests before using VS Code **Extensions: Install from VSIX**. Reload VS Code after install
or update, then enable the tool for the Developer custom agent. Packaging does not install
anything, contact Salesforce, publish an extension or change a VS Code profile.

The build copies an explicit list of reviewed Python modules and the job executor into the
extension's `runtime/`, with a SHA-256 source manifest. Invocation verifies those bytes; it never
imports a workspace session/policy/executor script. Rebuild and repackage after source changes.
The existing Python interpreter and installed Salesforce CLI remain trusted dependencies;
the hashes are corruption/source-consistency evidence, not code signing or a hostile-user sandbox.
The job adapter loads reviewed SDK entrypoints from the installed Salesforce CLI, never from
the workspace's `node_modules`. It runs in a disposable child with a cleaned environment;
SDK diagnostics are discarded and the child exits after its one bounded result frame.

For an isolated manual extension-host check, launch VS Code with a disposable `--user-data-dir`,
`--extensions-dir` and `--extensionDevelopmentPath` pointing here after building. Use only a
synthetic Salesforce executable/auth inventory. Do not use your normal profile or real credentials
for denial/fault tests. The node tests exercise native UI adapters with a VS Code mock and worker
processes; they do not establish real VS Code UI acceptance on macOS or Windows.
The `test/vscode-smoke.cjs` extension-host fixture verifies manifest discovery, activation,
LM tool registration and forged-input denial with all child-process spawning trapped. Supply
it through `--extensionTestsPath` and a synthetic workspace containing `sfdx-project.json`;
set `SF_HARNESS_SMOKE_REPORT` to a disposable report path if a JSON result is needed.
This fixture does not automate human target/environment/deployment UI acceptance.

## Execution boundary

The host receives private JSONL from a new worker per invocation. It accepts one terminal event
only, waits for clean process exit, then rechecks workspace trust, configuration digest and
the selected usernames' local authorization identities before dispatch. Cancellation, timeout,
malformed output, duplicate/replayed prompts, abnormal EOF or drift during assessment means
zero dispatch. No consent registry, raw log, token cache or authority is returned to the model.
Environment selection is in-memory and expires when the invocation ends.

CLI uses explicit argv without a shell. Windows npm `.cmd` launchers are resolved to their
installed Salesforce JavaScript entrypoint and run directly; unsupported layouts fail closed.
Windows inventory disables the standalone launcher's per-user update redirect (`SF_REDIRECTED=1`),
so inventory and execution use that same adjacent installation. For dedicated jobs, that base
installation must provide the reviewed Salesforce CLI 2.151.7 / core 9.2.0; an independently
updated per-user client does not substitute for it.
Cache-driven jobs use an explicit Job ID/connection in the job adapter and never reselect the
latest job at execution. Unsupported SDK/command forms remain blocked.

Command output is bounded to 1 MiB and obvious authentication fields/tokens are redacted.
Output bounds and redaction are not a general business-data anonymizer. No output channel or
telemetry is created. The assessment timeout is five minutes, command timeout ten minutes.
Cancellation after a command has been dispatched cannot undo an already submitted Salesforce
operation; inspect its actual result before retrying. Local auth inventory is a local identity
binding, not live Salesforce proof; the dedicated job executor separately proves its connection.

Production CLI remains limited to verified metadata retrieve. Production data/schema reads use
the existing read-only MCP, subject to its existing role limits. This extension does not change
Knowledge architecture or the Salesforce MCP role contract.

API reference: [VS Code Language Model Tools](https://code.visualstudio.com/api/extension-guides/ai/tools).
