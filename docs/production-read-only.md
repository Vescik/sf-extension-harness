# Production Salesforce access

Status: approved policy, isolated release candidate. Destination host/live acceptance remains
owner-side and NOT VERIFIED here. This backport applies the plan 01 production-policy changes to
`0af14c1`; it does not adopt the intervening Knowledge architecture or implement plan 01a.
See [the release handoff](production-read-only-revision-handoff.md) for scope and test evidence.

## Channels

The shared `scripts/salesforce_operation_policy.py` runs before the safety hook's deploy
question and in the Developer role guard. Production permits metadata retrieve through
CLI and existing read-only MCP tools. Every other production CLI operation is denied,
including reads, tests and validation. The removed development MCP remains denied.
No new MCP tool or arbitrary CLI argument transport is added.

The hook obtains only local identity inventory through the fixed `sf org list auth --json`
transport (2 second deadline). It discards credentials, error text and raw output. This is
internal target resolution, not a tool available to the agent. It joins CLI aliases and
usernames by Org ID (15/18 character equivalence), compares configured pins, and denies
conflicting classifications. The read MCP continues to prove live identity independently.
The resolver does not derive environment from an alias prefix or technical environmentType.

Each invocation re-reads configuration and target state. Explicit `--target-org`/`-o`,
legacy `--targetusername`/`-u`, username/Org ID, modern and legacy environment defaults,
project/global defaults, and Dev Hub targets participate. Conflicting defaults are denied.
Use explicit targets. The owner will check default-target behavior on the destination, including
`SF_SFDX_INTEROPERABILITY=false`; no default-resolution fix is claimed by this release. An
already-open terminal can differ in cwd/environment from the hook. Approval/execution binding
still needs owner-side host verification.

## Retrieve allowlist and historical CLI discovery

Historical source-branch discovery used Salesforce CLI and sfdx shim: 2.145.6, Node 22.23.1. The later local recheck found
2.151.7, Node 24.20.0. Its help/source retains the permitted retrieve forms below and still
has no `project retrieve resume` or legacy `force:mdapi:retrieve:report`. This template does
not pin the customer's CLI installation: verify command semantics on the destination host.
New flags such as `--root-type-with-dependencies` remain outside the reviewed allowlist.

- `sf project retrieve start` and `sf retrieve metadata`; the same modern command paths
  are available through the `sfdx` shim. Only the enumerated retrieve flags are permitted.
- Source selection: `--manifest`/`-x`, `--metadata`/`-m`, `--source-dir`/`-d`,
  `--package-name`/`-n`. Target: `--target-org`/`-o`.
- Output: `--output-dir`/`-r`, `--target-metadata-dir`/`-t`, `--zip-file-name`,
  `--unzip`/`-z`, `--single-package`. Other flags: `--api-version`/`-a`,
  `--wait`/`-w`, `--ignore-conflicts`/`-c`, `--json`.
- `project retrieve resume`, `force:source:retrieve`, `force:mdapi:retrieve`, and
  `force:mdapi:retrieve:report` are absent in this installation and are denied on prod.
  No report/resume/cancel exception is inferred from another job family.
- `--flags-dir` is denied because it can introduce an unassessed target or argument.
  Shell wrappers, chaining, substitution and redirects retain their prior restrictions.

A wait timeout is not proof that metadata was downloaded. The asynchronous retrieval
completion flow is NOT VERIFIED for this CLI; do not claim acceptance or substitute a
job command from the deploy family. Local help/version is not production access.

## Configuration migration

1. Keep existing aliases and identity pins. No alias prefix is required.
2. Change `salesforce.orgs[i].environment` from `development` to `dev` and
   `production` to `prod`. Runtime and schemas accept these two legacy spellings during
   migration; emitted MCP evidence uses the canonical value. `uat` stays `uat`.
3. For each old `qa`, explicitly choose `dev`, `uat`, `stage`, or `prod` according to its
   actual purpose. There is no automatic mapping. Diagnostics name the affected entry.
4. New entries use canonical values. Add as many distinct aliases of one type as needed.
   Onboarding updates only an exact alias, preserving neighboring entries. It rejects
   identity drift and attempts to reclassify a known production identity through another alias.
5. Run setup validation, then the three repository checks. Restart/rebind the read MCP
   and prove identity before relying on evidence. Technical `environmentType` and
   the evidence-only `dynamic` classification retain their existing meaning.

Private `harness.local.json` is not rewritten by this implementation. `dynamic` is never
an extra configured environment and never grants non-retrieve CLI access.

## Role and deferred boundaries

Test Strategist remains prohibited from all production targets, including read-only Salesforce
MCP in both QA lanes. The owner accepts the agent instruction as sufficient for this release;
additional MCP role/target runtime enforcement is not required or claimed. Other roles retain
existing read permissions and limits. The existing Knowledge persistence/approval model stays
unchanged; production MCP read permission does not widen its separate org-sampling containment.

The plan 01 backport originally deferred unknown environments and latest-job compatibility.
Plan 01a now adds a [native Developer operation tool](native-salesforce-operations.md) for these
flows. Direct terminal commands still deny unknown targets and mutable latest selectors. Native
selection is one-operation only; no agent-written approval/classification flag, persistent consent
registry, production write exception or new Salesforce MCP tool is introduced. Installation and
host/live evidence remain separate from local implementation.

## Owner-side destination acceptance

Use the [credential-free pilot](production-policy-pilot.md) to check actual VS Code hook invocation,
nonprod deployment approval scope, repeated/changed invocations, errors and timeouts on the target
host. Local/process tests do not establish Windows/macOS host behavior or approval binding.
Then verify the installed CLI forms, real selected aliases and identity pins, one bounded permitted
production metadata retrieve, and existing MCP identity/read tools within role limits. Never run a
forbidden operation against a real production org to test denial. A timed-out retrieve is not
proof of completed download; asynchronous completion remains unverified until checked.

These installation checks belong to the owner. Publication/merge approval does not convert them
into completed technical evidence. The release handoff separates historical source-branch results
from fresh checks of this isolated backport.
