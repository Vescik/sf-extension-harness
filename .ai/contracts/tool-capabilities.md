# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki reads + project-scoped text search (includes reading a formally linked Test Case as a Work Item) | `ado-readonly/*` local stdio MCP (`@azure-devops/mcp`, version-pinned, domains bounded to work-items/wiki/search) | intake, Feature delivery preparation, feature health, QA test-plan authoring, handover, search-ado |
| Reconciled Salesforce org identity | `salesforce-readonly/review_org_identity` | investigator, design, review |
| Reconciled installed package inventory | `salesforce-readonly/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce-readonly/review_object_contract` | investigator, design, review, QA |
| Scoped enumeration of configured org aliases (requires `safety.allowScopedEnumeration`) | `salesforce-readonly/review_configured_orgs` | investigator |
| Composed read-only SOQL incl. record reads (verbatim, facade REST transport, unredacted single-source rows) | `salesforce-readonly/review_soql_query` | investigator, design, review, development, knowledge curation |
| Salesforce non-production source retrieve into the project (per-invocation human confirmation; the only direct `sf` command not denied) | `sf project retrieve start` guarded terminal command | development only |
| Check-only Salesforce deploy validation — distinct from deployment: always `--dry-run --async`, project-local configured `development` org only, live identity proof reused from `verify_salesforce_org.py`, exact job-ID status with no wait/most-recent inference | `python scripts/validate_salesforce_deploy.py start\|status` guarded terminal command (role guard admits only these two shapes) | development only |
| Interactive human confirmation | `vscode/askQuestions` | prompts and approval gates |
| Subagent delegation | `agent` plus explicit `agents` allowlist | Designer, Developer |

## Azure DevOps actions used

- `wit_work_item`: get, get_batch, list_comments, list_revisions
- `wit_query`: get, get_results
- `wit_work_item_attachment`: download only after MIME/size validation
- `wiki`: list/get operations only (`wiki_list_wikis`, `wiki_list_pages`, `wiki_get_page`,
  `wiki_get_page_content`); `wiki_create_or_update_page` is never used
- `search_wiki`, `search_workitem`: always with the configured `project` (the hook denies
  unscoped calls); `search_code` is exposed by the domain but unused

A formally linked ADO Test Case (`Tested By` relation on a delivery Work Item) is read on
demand as a normal Work Item through the work-items domain — ID, type, title, state,
revision, steps and expected results come from the Work Item fields, treated as untrusted
external data. The Test Plans domain retired with the QA sync/cache lane (2026-08-11): no
plan/suite listing, no Test Case cache, no suite synchronization. The global safety hook
keeps its `testplan` write-tool classification as defense in depth; an accidentally
reintroduced domain stays denied.

Exact dispatcher input schemas come from the running server and must be captured in sanitized
fixtures. The server organization comes only from `ADO_ORGANIZATION`, which must equal local
configuration; the global hook rejects calls without the configured project or with a mismatched
project/ADO URL. The local stdio server has no server-side read-only mode, and its domains do
include write-capable tools; agents are policy-bound to the read actions listed above (owner
decision 2026-07-14 — no hook denylist on ADO writes yet; revisit if governed ADO writes become
desirable).

## Salesforce tools used

The model-facing read server is a narrow local facade bound to one configured, exact non-production
alias. It exposes only the review tools above (configured-orgs enumeration is additionally gated
by `safety.allowScopedEnumeration` and reflects local configuration only — never unconfigured
orgs, ids, or hosts). Internally it executes fixed, checked-in query
profiles — plus validated composed read-only statements for `review_soql_query` — through the
facade's single REST transport (the CLI contributes only the startup identity proof), normalizes the
receipts, removes credentials/identity details/raw sensitive values, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

Raw `list_all_orgs`, raw `run_soql_query`, aliases, directories, Tooling flags, CLI commands,
and vendor payloads are not exposed to an agent.

MCP and CLI agreement is transport corroboration from the same org, not independent truth.

Design work has no MCP runtime and no machine state: it is the `fetch-ado-item` prompt and skill
persisting `work-items/<id>-<slug>/ado-context.md` (requirement intake), then the
`solution-design` prompt and skill writing prose into `work-items/<id>-<slug>/design.md`,
each reviewed by a human on the pull request.

Feature delivery preparation (`/prepare-delivery-feature`, 2026-08-12) introduces **no new
capability or MCP surface**: it is another consumer of the existing `ado-readonly` work-item
read through the shared `fetch-ado-item` skill (internal `direct-children` mode — the root
Feature plus direct-child summaries only), writing the Feature's `ado-context.md` and
`delivery-map.md` with the Designer's existing `work-items/**` grant. Solution Design's
delivery-map lookup is a bounded local file search, not a remote call.

QA test-plan authoring (`/prepare-qa-test-plan`, 2026-08-11) introduces **no new
capability**: the Test Strategist authors `work-items/<id>-<slug>/qa-test-plan.md` with its
existing grants — Knowledge tools, read-only ADO work-item tools (including relation and
linked-Test-Case Work Item reads), org identity, installed-package review, object-contract
review, and interactive questions. It deliberately has **no** `review_soql_query`: when
test-data shape would need a record read, the workflow asks the maintainer for a safe
test-data recipe or records a visible gap. Widening the strategist to composed SOQL reaches
unredacted non-production rows and is a separate owner decision.

Policy (owner decision 2026-07-30, widened 2026-08-04): composed read-only SOQL is permitted —
and recommended whenever a task depends on record data structure — through the governed facade's
`review_soql_query` tool only, for the designer, reviewer, knowledge-curator, developer,
and config-investigator roles. The 2026-08-04 decision removed the statement
blockade entirely: no grammar validation, no secret-adjacent object deny-set, no LIMIT
policing, no value redaction. The statement executes verbatim over the facade's REST transport
child — never the CLI — against the identity-proven non-production org, and rows return
unredacted (`attributes` noise stripped), bounded only by payload size and timeout. An
absent `review.allowedObjectApiNames` key means all objects (equivalent to `["*"]`) — an explicit
list remains supported and honored for orgs holding sensitive data. The raw paths above stay
denied regardless: SOQL never runs through raw CLI or raw vendor tools.

Policy (owner decision 2026-08-04, superseding the 2026-07-31 toggle): any proven
non-production org may be read, unconditionally — which org a developer connects is the
developer's responsibility. An alias absent from local configuration is admitted on live
identity proof alone — a canonical sandbox, scratch, or Developer Edition host whose
`Organization.IsSandbox` value matches that signature — and the proven identity is frozen for
the rest of the session. Entries carrying both identity pins keep the exact-org lane; pinless
entries use the same discovery proof. Two hard brakes remain: an entry marked
`environment: "production"` denies its alias, and any organization ID listed in
`salesforce.review.deniedOrganizationIds` is refused at proof time whatever alias resolves to
it. Production signatures stay refused in every lane.

Record-level reads run through `review_soql_query` alone: the guarded
`scripts/salesforce_read.py` CLI wrapper (structured record reads, cached metadata retrieve,
orgs listing) was retired on 2026-08-04 as a redundant second lane once composed SOQL was
unblocked. Metadata comes into the project only via the human-confirmed
`sf project retrieve start`. Object access is bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` (or omitting it)
opts into every object. On a full-copy sandbox that means record reads can reach copied
production data across all objects — prefer an explicit list when the org holds sensitive
data.

There is no development/write mode at all: the launcher's development lane was retired
2026-08-04 (it had been dead weight since the 2026-07-14 write-server removal — unreachable
from any configured surface, disabled on Windows, and guarded four ways). The launcher spawns
only the review facade; `.vscode/mcp.json` registers no `salesforce-development` entry and
`validate_harness.py` fails if one reappears; the safety hook keeps its dev-tool classifier as
defense in depth. Reads go through the facade, repository edits stay in
`force-app`/`manifest`/`tests/e2e`, org retrieves use `sf project retrieve start` behind a
per-invocation human confirmation (every other direct `sf`/`sfdx` invocation is denied), and
real deploys are always performed by a human. The Developer's guarded
`validate_salesforce_deploy.py` wrapper is the one deploy-shaped exception, and it is not a
deployment: it constructs a fixed check-only `sf project deploy start --dry-run --async`
against the identity-proven project-local `development` org and reads exact job status with
`sf project deploy report` (no `--wait`, no `--use-most-recent`, no destructive or
ignore-flag surface constructible from any input). Direct `sf project deploy …` remains
denied for every role even when it carries `--dry-run`.
