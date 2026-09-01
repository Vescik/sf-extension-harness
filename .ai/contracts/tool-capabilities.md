# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki reads + project-scoped text search (includes reading a formally linked Test Case as a Work Item) | `ado-readonly/*` local stdio MCP (`@azure-devops/mcp`, version-pinned, domains bounded to work-items/wiki/search) | intake, Feature delivery preparation, feature health, QA test-plan authoring, handover, search-ado |
| Reconciled installed package inventory | `salesforce/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce/review_object_contract` | investigator, design, review, QA |
| Scoped enumeration of configured org aliases (requires `safety.allowScopedEnumeration`) | `salesforce/review_configured_orgs` | investigator |
| Composed read-only SOQL incl. record reads (verbatim, facade REST transport, unredacted single-source rows) | `salesforce/review_soql_query` | investigator, design, review, development, knowledge curation |
| Salesforce metadata retrieve and dry-run validation | direct `sf`/`sfdx` terminal command | Developer |
| Real metadata deployment, including quick, destructive, and production deployment | direct `sf`/`sfdx`; global hook asks before every exact invocation with target, scope, and real-org-change warning | Developer |
| Record create/update/upsert/delete and bulk data operations | direct `sf data`/legacy `sfdx` terminal command | Developer |
| Apex execution/testing, package operations, and org lifecycle | direct `sf`/`sfdx` terminal command | Developer |
| Optional legacy check-only validation helper | `python scripts/validate_salesforce_deploy.py start\|status` | Developer |
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
facade's single REST transport (the CLI performs background readiness against configured host/org-id walls), normalizes the
receipts, removes credentials/identity details/raw sensitive values, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

The configured MCP remains a narrow read/evidence facade. Direct Salesforce write execution is
provided separately through the Developer's terminal capability.

CLI readiness binds the REST session to the configured target; it is not independent truth.

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
linked-Test-Case Work Item reads), installed-package review, object-contract
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
child — never the CLI — against the configured review org, and rows return
unredacted (`attributes` noise stripped), bounded only by payload size and timeout. An
absent `review.allowedObjectApiNames` key means all objects (equivalent to `["*"]`) — an explicit
list remains supported and honored for orgs holding sensitive data. The facade remains the
preferred evidence path; the Developer may also use direct CLI when task execution requires it.

The read facade retains its configured host/org-id and non-production host-shape contract. That
constraint applies to the facade only; it is not a global denial for Developer CLI commands.
Direct CLI may target development, QA, UAT, production, scratch orgs, or Developer Edition, using
explicit flags or the normal project/default target context.

Record-level reads run through `review_soql_query` alone: the guarded
`scripts/salesforce_read.py` CLI wrapper (structured record reads, cached metadata retrieve,
orgs listing) was retired on 2026-08-04 as a redundant second lane once composed SOQL was
unblocked. Metadata may be retrieved through direct CLI. Object access in the read facade is
bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` (or omitting it)
opts into every object. On a full-copy sandbox that means record reads can reach copied
production data across all objects — prefer an explicit list when the org holds sensitive
data.

The first cutover uses one canonical write path: direct Salesforce CLI in the Developer role.
The launcher continues to spawn only the read facade; no write MCP or separate Deployment Agent
is required. The global safety hook allows direct `sf`/`sfdx`, including record mutations,
production targets, destructive deploys, package work, and org lifecycle. It returns `ask` only
for commands or future MCP tools that start a real deployment, with the required warning:
`This will be a real deployment of changes to Salesforce org <target>. Scope: <scope>. Should I
run this deployment?` The host confirmation binds to that exact tool invocation, so every new
deploy, quick deploy, or redeploy asks again. Dry runs, retrieve, deploy status/report/resume/
cancel, and record mutations do not use this deployment-specific confirmation gate.
