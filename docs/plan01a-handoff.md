# Plan 01a native implementation handoff

Status: **IMPLEMENTED LOCALLY / DESTINATION ACCEPTANCE PENDING** (2026-09-28).
Base: main `5f01811`, with the reviewed nonprod command-compatibility delta ported separately from
Knowledge v3. This work does not import the intervening Knowledge redesign or change ADO/MCP.
The owner approved a native VS Code extension to own one-operation questions and execution.
Implementation was prepared on `codex/plan01a-host`; the delivery branch is `codex/plan01a-release`
in that isolated checkout. The original dirty checkout is preserved. No completed end-to-end host/live acceptance, publication or merge
is claimed by this status.

## Current implementation scope

- Native tool `sf_harness_run_operation`, Developer reference
  `sf-harness.salesforce-operations/salesforceOperation`, accepting only bounded arguments.
- Private per-invocation session, native org/environment dialogs, production precedence,
  fresh exact-deploy confirmation, identity/config drift checks, cancellation and no durable grant.
- Packaged immutable runtime and dedicated job selection/execution so reviewed latest workflows
  execute the selected job and controlling identity rather than re-reading mutable CLI cache.
  Implemented families: deploy report/resume/cancel/quick, sandbox resume (latest, ID or name).
  Job execution uses CLI 2.151.7 / core 9.2.0 and returns bounded status summaries; arbitrary
  cached options, report files and CLI source-tracking updates are not reproduced.
- Exact-name role/global hook recognition, other-role denial, private terminal invocation denial,
  root-of-trust protection and full-harness CI for extension tests/build/package.
- Scratch-org resume remains denied after SDK review; native latest support is limited to the
  command families the private executor can bind safely. Native sandbox/scratch deletion also
  stops before dialogs because generic CLI reloads a mutable controlling-org relation. Existing
  terminal policy is unchanged; no deletion adapter is introduced. These denials are limitations,
  not evidence of successful resume/deletion.
- Existing nonprod command additions and aliases from the
  [historical command audit](plan01a-command-audit.md); unsupported families still fail closed.

The [native design](plan01a-native-design.md) defines the protocol; the
[installation and use guide](native-salesforce-operations.md) defines the agent/operator boundary.
The existing Knowledge architecture, approval model and nonprod observation containment remain.
Test Strategist's prod restriction remains instruction-only as accepted by the owner. Default-target
interoperability checks remain owner-side; this work does not claim that separate issue fixed.

## Verification state

Final local results below were observed on macOS. Unit/process tests, extension synthetic tests,
VSIX contents, real extension-host UI, Copilot Local hook behavior, each destination OS and live
Salesforce acceptance are separate evidence layers. The activation smoke invokes only invalid
input; it does not prove a successful Salesforce operation or the full native dialog flow.

| Evidence | Current handoff status |
|---|---|
| Python unit/process suite (including native hooks) | PASS: 1,129 tests, one pre-existing platform skip; 45 affected tests rerun after final SDK/Windows fixture changes |
| Safety evals and static validator | PASS: 67 evals, 2,764 assertions |
| Compile, ESLint, formatting and Knowledge gates | PASS; production dependency audit has no high/critical findings |
| Native extension synthetic unit/process tests | PASS: 32 tests, including cancellation, one dispatch, forged/replayed events, UI adapters and hung-child termination |
| SDK adapter tests with injected connections | PASS: 17 Node tests; no real auth/network request |
| Build/package integrity and isolated VSIX install | PASS: ZIP CRC, six runtime hashes/current source equality, successful VS Code install into a disposable profile |
| Actual macOS VS Code 1.138.0 extension host | PASS: manifest discovered, activation, LM tool registration, forged-input denial; zero native process attempts |
| Actual native dialog UX / positive operation through Copilot Local | NOT VERIFIED; synthetic adapters are not full UI acceptance |
| Copilot Local custom-agent role hook invocation | NOT VERIFIED in the destination host; deterministic hook tests pass |
| Actual Windows host | NOT VERIFIED; Windows launcher/environment layouts have synthetic coverage |
| Real bounded production retrieve / permitted read MCP | NOT VERIFIED; owner-side installation acceptance |

Artifact: `extensions/salesforce-operations/dist/salesforce-operations-0.1.0.vsix`.
SHA-256: `9bc79b28e5689fa502e1d0cdc57ecf28f924a085d325968b87ed50ee7d7c5a86`.
The VSIX was installed only into a disposable test profile, not the owner's normal VS Code setup.
Use [the installation guide](native-salesforce-operations.md) for destination acceptance.

Earlier source-branch evidence (734 unit tests, 2,284 static assertions, 71 evals and a Local attempt
stopped by `Language model unavailable`) belongs to the pre-native implementation. It is historical,
not proof for this native package or base. Unknown-target denial alone is not completion of the
one-operation answer flow; tests must show positive dispatch once, cancellation/replay/drift denial,
production precedence, exact deployment confirmation and immutable job selection.
