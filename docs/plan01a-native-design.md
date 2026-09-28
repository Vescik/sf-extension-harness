# Plan 01a native operation design

Owner authorization: the current conversation approves implementation of the native VS Code
one-operation environment selector and safe latest-job selection. This adds a small local
extension, not an MCP server, persistent consent ledger or environment registry. It concerns
Developer CLI operations; existing Salesforce read MCP is unchanged.

Base: main merge 5f01811, with the reviewed local 01a nonprod compatibility delta ported separately
from Knowledge v3. The original dirty checkout remains untouched.

## Boundary

The native extension owns user dialogs and execution in one invocation. Model input is only
`arguments: string[]` (Salesforce subcommand and flags, without the executable). No role,
approval, environment or continuation token is accepted from the model. Root is the single
trusted VS Code workspace; it is not model-controlled. Native tool name is
`sf_harness_run_operation`, reference name `salesforceOperation`, Developer exposure only.
Other role hooks deny it; direct terminal invocation of the session/executor remains forbidden.
Installed extension runtime is packaged from reviewed sources, not imported from mutable
workspace scripts. Role restrictions reuse VS Code Local agent hooks; unsupported hosts/default
agent mode must not be advertised as supported or as independently attested by the tool API.

## Private process protocol (never exposed as a model tool)

One Python session process per invocation, `salesforce_operation_session.py --workspace <root>`.
The first stdin JSON line is `{ "arguments": [...] }`; unexpected keys fail closed.
Output JSONL types:
- `selectOrg`: promptId, items [{label, username, id, host}], arguments. Answer: {promptId, value: username}.
- `environment`: promptId, target {username,id,host}, arguments, environments. Answer: {promptId, value: dev|uat|stage|prod}.
- `confirmDeploy`: promptId, target(s), arguments, scope. Answer: {promptId, value: true}.
- `execute`: execution {kind: cli|job, arguments, targets, configDigest, job?}, digest.
- `blocked`: message.
Cancellation, EOF, timeout, malformed/extra reply fields or mismatched promptId => no execute.
No reply survives process exit. Only native dialogs feed stdin. Native tool auto-approval does
not answer those dialogs. There is at most one execute event; the extension executes once and
never returns the execution request or reusable authority to the model.

## Evaluation

Resolve identity through bounded local CLI inventory, then configured environment by Org ID.
Resolve missing target via a native pick. Use an in-memory config overlay only for targets whose
identity is known but environment is missing. Known production, denied IDs, conflicts and
identity errors cannot be overridden. Recheck configuration and selected identities after
human input; drift stops instead of silently reusing the answer. Keep role, production command,
parent/Dev Hub, retrieve grammar and exact deployment-confirmation rules. Rewrite alias/default
targets to the selected explicit username where command semantics support it.

## Latest

Resolve latest exactly once to an immutable Job ID and controlling org. Never dispatch a mutable
latest selector to CLI. Cache-driven operations use the dedicated job executor: it receives
only selected job/options and verified org identity, establishes that exact connection, checks
identity and uses the explicit ID. It must not re-read mutable CLI job/alias cache to pick a target.
No temporary auth copy, global cache rewrite or monkey patch of installed Salesforce CLI.
Use reviewed installed Salesforce SDK entrypoints; unsupported formats/options fail closed.
Implemented: deploy report/cancel/resume/quick and sandbox resume. Scratch resume remains
unsupported because the reviewed public SDK reselects mutable cached Dev Hub/settings. Native
sandbox/scratch deletion is also denied because the generic CLI reloads its controlling-org
relation. Unknown new families/flag files remain denied; no new deletion adapter is added.

## Evidence

Unit/process tests must prove cancellation, forged input/reply, replay, drift during dialogs,
production precedence, role denial, latest cache drift, parent/hub identity, deploy confirmation,
exactly one dispatch, output bounds and packaged-source integrity. Test native UI in an extension
host with synthetic transports and no Salesforce credentials. Live org acceptance remains separate.
