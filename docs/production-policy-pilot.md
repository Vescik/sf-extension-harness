# Portable production-policy pilot

This is a disposable test workspace, not a Salesforce workspace. No Salesforce account,
authentication file, metadata, MCP server, customer config, or approval is copied. The CLI
stub has no network or subprocess transport. It only returns synthetic identity inventory
and records an operation digest. These fixture aliases never configure a real org.

## Generate on each host

From the template repository, with its Python environment activated and Git on PATH:

```text
python scripts/prepare_salesforce_policy_pilot.py <new-disposable-directory>
```

Choose a new directory, preferably outside the repository. Existing paths are refused.
The generator pins this machine's interpreter and paths, so regenerate on Windows/macOS;
do not transfer a generated pilot as an installed workspace. Copied production hook sources
are byte-identical and fingerprinted in `source-manifest.json`. Only the pilot host config
adds isolated HOME/PATH and a terminal-only Developer agent. It is not full-template acceptance.
The fixture has its own empty Git repository to avoid discovering a parent's workspace.
No runtime policy imports the pilot, and no permission setting is weakened by generation.

Inside the generated directory run:

```text
python scripts/pilot_check.py
```

Expect eight passing process scenarios in `.cache/process-report.json`. Only two retrieve
cases and non-production validation reach the stub. Production query/deploy, unknown target
and flag injection do not; non-production deploy returns `ask` and is not executed by the
driver. This proves the copied processes, not VS Code approval behavior. Every report
deliberately retains `hostAcceptance: NOT VERIFIED`.

## VS Code Local procedure

1. Open the generated directory as a separate VS Code window. Use Local and the pilot
   `developer` custom agent. Inspect Customization Diagnostics for both hooks. An authenticated
   Copilot session is required. Do not connect Salesforce MCP or log in to Salesforce here.
2. Create a **new** integrated terminal using the generated `Policy pilot` profile. In that
   terminal use `command -v sf` (macOS) or `where sf` (Windows cmd). The first result MUST be
   the generated `bin` path. Run `sf --version`: expect `POLICY-PILOT-STUB`. Stop if either
   check fails. Existing terminals can retain another PATH. Never use a real CLI absolute path.
3. Record OS, VS Code/Copilot/real CLI versions and source hashes. The stub is not a real CLI
   compatibility check. Record each prompt, tool call ID, permission UI, decision and new
   `operation` entries in `.cache/executor.jsonl`. Inventory entries do not mean the operation ran.
4. Request one exact command at a time from the matrix. Compare executor log counts before
   and after. Keep evidence outside versioned config; all data here is synthetic.

| Scenario | Exact command | Expected host outcome |
|---|---|---|
| Known prod read | `sf data query -o team-alpha --query SELECT` | Deny; zero new operations |
| Known prod deploy | `sf project deploy start -o team-alpha -m ApexClass:Pilot` | Deny, no overridable deploy question |
| Retrieve | `sf project retrieve start -o team-alpha -m ApexClass:Pilot` | May execute stub within role |
| sfdx shim | `sfdx retrieve metadata -o team-alpha -m ApexClass:Pilot` | Same as retrieve |
| Nonprod deploy | `sf project deploy start -o prod-copy -m ApexClass:Pilot` | Exact target/scope question before stub |
| Nonprod validation | `sf project deploy start -o prod-copy --dry-run -m ApexClass:Pilot` | May execute stub |
| Unknown org | `sf data query -o unconfigured --query SELECT` | Held denied in this terminal-only pilot; native flow is separate |
| Flag-file bypass | `sf project retrieve start -o team-alpha --flags-dir flags` | Deny |

Repeat a nonprod deploy after approving only the first one: a fresh confirmation is required.
While its question is pending, have the **human tester** change one item at a time in the
disposable fixture: arguments, default target, alias identity, or configured classification.
The old approval must not authorize the new operation. Repeat with a new tool call ID and
with broader host approvals, recording their actual scope. Never change permissions for the
real workspace. Do not claim that a chat answer or a model-written `approved`/`environment`
field implements P1-02. This pilot contains no native extension. Use the separate
[native operation guide](native-salesforce-operations.md) and its tests for one-operation dialogs.

## Failure probes (disposable workspace only)

- Put `error`, then `timeout`, into `.cache/inventory-mode.txt`; retry retrieve. Both real
  hook processes must deny before their host deadline. Remove that file to restore the baseline.
- To measure **host** behavior, use a fresh generated pilot. In its global hook JSON and
  custom-agent frontmatter replace only the command with the generated interpreter followed
  by `scripts/pilot_fault.py exit1`, `exit2`, `invalid`, or `timeout`. Preserve each timeout
  and environment. Change both hooks for the total-failure probe; retain one normal hook
  separately to measure layered protection. These are explicit fault injections, not final code.
- Request a known-production command on the stub. Any new operation is a failed acceptance
  result. Record it; do not reinterpret a warning as a block. Restore by generating a new
  pilot. Source edits cause `pilot_check.py` to refuse its baseline proof.

Local documents generic nonzero exits other than 2 as nonblocking; timeout behavior still
needs a measured result. See the [Local hook contract](https://code.visualstudio.com/docs/agents/reference/hooks-reference).

## Template acceptance and installation acceptance

Template evidence covers canonical config, migration, alias identity, hook/process behavior,
transport boundaries, portable paths and simulated failures. Actual host behavior must be measured
on each destination in use; a local process test cannot substitute for Windows/macOS host evidence.
The owner performs installation acceptance where the template is actually used: confirm installed
CLI forms, configure real aliases and pins, then use an explicitly bounded metadata retrieve
and existing read MCP identity/query checks. Never execute forbidden commands on a real prod
org to test rejection. This pilot does not certify real Salesforce access or asynchronous retrieval.

Record unrun/unsupported cases as NOT VERIFIED. The owner approved publication of isolated plan 01
with destination acceptance on their side; passing local processes does not complete that acceptance.
Unknown-org answers and supported latest workflows now use the separate plan 01a native tool;
this terminal pilot cannot establish that tool's host acceptance. Test Strategist's
production prohibition is accepted as an agent instruction, without a new runtime enforcement task.
See `production-read-only-revision-handoff.md` for the release scope and evidence provenance.
