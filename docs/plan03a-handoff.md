# Plan 03a implementation handoff

Date: 2026-09-30. Base: Plan 03b commit `a2ec1fe77f7bb40bcf6a40288f9e39dabbfa5a60`.
Branch: `codex/plan03a-ado-configuration`.

## Result

ADO reads its organization and project from `config/harness.local.json` only. The no-argument
`scripts/start_ado_mcp.mjs` launcher validates these fields and the allowed HTTPS prefixes before
starting the installed `@azure-devops/mcp` 2.8.1. It uses the current Node executable, a fixed
entrypoint, and the existing `work-items`, `wiki`, and `search` domains. It downloads nothing.
Missing or invalid configuration and missing or mismatched dependencies fail locally. Diagnostic
messages identify the field without printing configuration values. The old `ADO_ORGANIZATION`
environment variable does not select scope and is not a fallback.

The launcher keeps the initial scope in memory. It rereads configuration before forwarding
each input or output buffer and while idle. A detected scope change or invalid file stops the
child and latches the refusal for that process. Restart `ado-readonly` after correcting the file.
Unrelated configuration edits and origin reordering do not restart it. Signal, EOF, backpressure,
and forced child shutdown use the existing process boundary, without a session file or MCP parser.
Requests already passed to the vendor before a change are in flight; termination does not undo
an HTTP request. This is not transactional cancellation or proof of atomic host configuration.

The safety hook uses the same pure Python scope validation as onboarding. Calls must include
the configured top-level `project` value or nonempty array. Nested fields and alternate names
cannot stand in for the vendor's parameter. URLs must stay within configured HTTPS prefixes and
the exact organization/project. Ambiguous wiki paths, traversal, and legacy or subdomain ADO
aliases are denied. This preserves one configured project without introducing an ID/name map.
Use the project name consistently, including search filters.
The ADO launcher and shared scope validator are protected control-plane files. Editing them
uses the same Maintainer confirmation boundary as editing the safety hook.

Onboarding preserves the local configuration and unrelated approved HTTPS prefixes. An
organization change replaces previous ADO prefixes. Setup checks the installed vendor package
without starting it. Authentication remains the vendor's default interactive OAuth in VS Code
Local; Azure CLI login is not required and credentials stay outside JSON.

The wiki cache procedure now checks organization/project/wiki/path before freshness. A scope
collision refuses dependent use and preserves the file, including under `onStale=use`. Cache
authoring remains an agent procedure, without a new runtime reader or registry. Local tests do
not prove that a host follows this instruction.

The native Salesforce bundle includes and verifies `ado_config.py`, because its packaged
safety hook imports that helper. It adds no Salesforce operation capability.

## Verification

- Launcher: 15 isolated subprocess tests passed. They cover startup refusal, old environment
  values, separate workspace scopes, spaces in paths, stale input and output, idle termination,
  refusal after restoring a changed file, byte-preserving backpressure, EOF, and signals.
- Hook/configuration/wiring: seven focused tests passed, including regressions found by an
  independent review of the pinned vendor's wiki URL parser and search parameter handling.
- Onboarding: 20 tests passed. Packaged-runtime tests: three passed.
- Full Python suite: 1,268 tests completed in 251.826 seconds, with one existing
  case-insensitive filesystem skip and no failures.
- Static validator: 3,027 assertions passed in a conventional validation checkout.
- Safety evaluations: 82 scenarios passed. Native operation tests: 32 passed.
- Python syntax, JavaScript syntax, ESLint, formatting, and diff checks passed.
- VSIX build/package passed. All eight runtime files match the source and manifest. Extraction
  into an unrelated directory passed isolated Python import and the extension's runtime verifier.

The first full run exposed the new helper missing from the portable pilot's source list.
The pilot and isolated Git import-failure fixture now copy it. The existing policy assertions
remain intact. Fifty targeted regression tests passed before the successful full rerun.
The new cache-collision agent scenario is an acceptance specification, not an executed host test.

The implementation uses a Git worktree. The existing validator requires `.git` to be a directory,
so full verification uses a separate conventional local clone with identical changed-file bytes.
The validator requirement was not weakened. Local logs and source hashes are in the parent
workspace's `work/plan03a-*` files; VSIX evidence is in `work/plan03a-evidence-20260930/`.

## Remaining acceptance and rollout

No real ADO authentication or API request ran. Live Windows/macOS VS Code acceptance remains
NOT VERIFIED. Two temporary processes prove local scope separation, not two live VS Code windows.
The read checks still need one Work Item and one wiki page in the configured project, including
GUI startup, authentication, simultaneous workspaces, and restart after a configuration edit.

Ship the launcher, hook/helper, MCP registration, onboarding, validator, and rebuilt native
extension together. Keep each user's local JSON. Correct only fields named by validation, restart
`ado-readonly`, and perform the bounded read checks. The former environment variable may remain
for other tools. No remote publication, pull request, or merge is included in this implementation.
