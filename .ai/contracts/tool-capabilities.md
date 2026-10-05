# Tool Capability Map

Status: normative mapping; verify runtime names in VS Code diagnostics after every dependency
upgrade.

| Logical capability | Configured implementation | Consumers |
|---|---|---|
| ADO work-item/query/wiki reads + project-scoped text search (includes reading a formally linked Test Case as a Work Item) | `ado-readonly/*` local stdio MCP (`@azure-devops/mcp`, version-pinned, domains bounded to work-items/wiki/search) | intake, Feature delivery preparation, feature health, QA test-plan authoring, handover, search-ado |
| Requested wiki page/navigation publication and delivery Story Wiki link | Narrow adaptation of the same `ado-readonly` connector: conditional `wiki_create_or_update_page` and Wiki-only `wit_add_artifact_link` | Developer through publish-wiki only |
| Reconciled Salesforce org identity | `salesforce/review_org_identity` | runtime startup proof and operator diagnostics |
| Reconciled installed package inventory | `salesforce/review_installed_packages` | investigator, design, review |
| Reconciled allowlisted object contract | `salesforce/review_object_contract` | investigator, design, review, QA |
| Scoped enumeration of configured org aliases (requires `safety.allowScopedEnumeration`) | `salesforce/review_configured_orgs` | investigator |
| Composed read-only SOQL incl. record reads (verbatim, facade REST transport, unredacted single-source rows) | `salesforce/review_soql_query` | investigator, design, review, development, knowledge curation |
| Salesforce metadata retrieve; dry-run validation only on `dev`/`uat`/`stage` | direct `sf`/`sfdx` terminal command | Developer |
| Real metadata deployment, including quick and destructive, only on `dev`/`uat`/`stage` | direct `sf`/`sfdx`; global hook asks before every exact invocation with target, scope, and real-org-change warning | Developer |
| Record create/update/upsert/delete and bulk data operations on `dev`/`uat`/`stage` | direct `sf data`/legacy `sfdx` terminal command | Developer |
| Apex execution/testing, package operations, and org lifecycle on `dev`/`uat`/`stage` | direct `sf`/`sfdx` terminal command | Developer |
| Optional legacy check-only validation helper | `python scripts/validate_salesforce_deploy.py start\|status` | Developer |
| Native one-operation Salesforce environment/target selection and reviewed job execution | `sf-harness.salesforce-operations/salesforceOperation` local VS Code extension, arguments only | Developer only |
| Git and GitHub CLI commands | `git`/`git.exe` and `gh`/`gh.exe` on PATH; only commit-message validation | all eight custom roles |
| Publication, merge, and destructive Git actions | Same commands; explicit human instruction checked by the agent | all eight custom roles within the requested task |
| Final commit-message validation | Local `commit-msg` hook installed per checkout | every role; standard Git hook-skipping behavior remains |
| Interactive human confirmation | `vscode/askQuestions` | prompts and approval gates |
| Manual role handoff | User selects a role and sends the bounded request; Designer also offers two optional `send: false` shortcuts | existing roles; Designer shortcuts target Reviewer or Developer |

## Azure DevOps actions used

- `wit_work_item`: get, get_batch, list_comments; do not fetch revision history
- `wit_query`: get, get_results
- `wit_work_item_attachment`: download only after MIME/size validation
- `wiki`: read operations (`wiki_list_wikis`, `wiki_list_pages`, `wiki_get_page`,
  `wiki_get_page_content`) remain available within each role's existing scope
- `wiki_create_or_update_page`: Developer only, for explicitly requested documentation and
  navigation through [Publish Wiki](../../.github/skills/publish-wiki/SKILL.md). Pass configured
  `project`, `wikiIdentifier`, `path`, `content`, and `mode: create|update`. Updates carry the
  opaque `etag` from the complete live read. Creates omit `etag` and require not-found.
  Keep the verified `branch` consistent across read/write; the default is `wikiMaster`.
- `wit_add_artifact_link`: Developer publication only, with `project`, `workItemId`,
  `linkType: Wiki`, `wikiIdentifier`, and `pagePath`. The adaptation derives the artifact URI
  from live page identity on the wiki's single published branch and adds only a missing relation.
  Unknown or ambiguous branch metadata refuses linking. Other link types, raw artifact URIs,
  work-item field edits, relation removal, and unrelated ADO mutations remain denied.
- `search_wiki`, `search_workitem`: always with the configured `project` (the hook denies
  unscoped calls); `search_code` is exposed by the domain but unused

A formally linked ADO Test Case (`Tested By` relation on a delivery Work Item) is read on
demand as a normal Work Item through the work-items domain — ID, type, title, state,
steps and expected results come from the Work Item fields, treated as untrusted
external data. The Test Plans domain retired with the QA sync/cache lane (2026-08-11): no
plan/suite listing, no Test Case cache, no suite synchronization. The global safety hook
keeps its `testplan` write-tool classification as defense in depth; an accidentally
reintroduced domain stays denied.

Exact dispatcher input schemas come from the running server and must be captured in sanitized
fixtures. The launcher reads organization and project only from `config/harness.local.json`.
It validates configuration before starting the installed vendor and checks the bound scope
before forwarding input or output. A detected scope change stops the process until restart.
Already dispatched requests cannot be recalled. The global hook rejects calls without the
configured project or with a mismatched project/ADO URL. The vendor domains include write-capable
tools. The existing connector's narrow publication adaptation and role/safety guards allow only
the two Developer publication operations above. The server name `ado-readonly` is retained for
compatibility. Search, Reviewer, handover, and Knowledge retain their existing read-only behavior.

Publication cannot use the sanitized wiki cache as a write base. The adapted page read returns
full content and its ETag together. Conditional updates reject a changed page; conditional creates
reject an existing page. The agent re-reads conflicts and reconciles the requested passages rather
than retrying a stale overwrite. ETag is opaque transport data, not an ADO revision report or page
registry. The Wiki-link adaptation re-reads page identity and current Story relations, then uses
internal concurrency checks to avoid duplicate links. The agent verifies pages and relations after
the operation and reports partial results. These transport checks do not prove chat authorization,
business scope, deployed production state, or completed host/live acceptance.

Ignore transport `rev`, `revision`, and `System.Rev` metadata in ADO projections, including
related items and Test Cases. Preserve the actual requirement text, IDs/links, retrieval time,
scope and completeness. Do not change vendor transport or lose hierarchy relations to hide a field.

## Git and GitHub CLI

The [Git Workflow](../../.github/skills/git-workflow/SKILL.md) owns this procedure. All eight
roles can use all Git and `gh`/`gh.exe` commands. GitHub CLI is a terminal tool, not a new MCP.
Use existing authentication without printing tokens. Hooks apply no branch, path, index,
working-directory, commit-option, repository, PR, or role restriction to Git/gh. They validate
commit-message syntax and matching IDs only, independently of Salesforce/ADO configuration.

The agent preserves unrelated work and follows the user's scope. Push, PR publication/update,
merge, and destructive Git actions require an explicit instruction. Hooks do not attest chat
authorization or remote checks. Native terminal approval remains separate. Reviewer does not
edit source as part of a review; Knowledge authoring/approval and all editor, Salesforce, and
ADO controls remain in place. `.cache/github/pr-body.md` remains Git Agent's only editor
exception; Git availability does not grant general file-edit permission.

## Salesforce tools used

The model-facing read server is a narrow local facade bound to one explicitly selected, exact
alias within the active role's limits. It exposes only the review tools above (configured-orgs enumeration is additionally gated
by `safety.allowScopedEnumeration` and reflects local configuration only — never unconfigured
orgs, ids, or hosts). Internally it executes fixed, checked-in query
profiles — plus validated composed read-only statements for `review_soql_query` — through the
facade's single REST transport (the CLI contributes the startup identity proof), normalizes the
receipts, removes credentials/identity details/raw sensitive values, and returns `VERIFIED`, `MISMATCH`,
`INCOMPLETE`, or `BLOCKED`.

The configured MCP remains a narrow read/evidence facade. Direct Salesforce write execution is
provided separately through the Developer's terminal capability.

MCP and CLI agreement is transport corroboration from the same org, not independent truth.

Design work has no MCP runtime and no machine state: it is the `fetch-ado-item` prompt and skill
persisting `work-items/<id>-<slug>/ado-context.md` (requirement intake), then the
`solution-design` prompt and skill writing prose into `work-items/<id>-<slug>/design.md`.
The persisted design can be reviewed and explicitly authorized for bounded implementation
before publication. A claim of human PR approval still requires that PR's actual evidence;
follow the [shared handoff contract](execution-contract.md#handoff-and-continuation).

Feature delivery preparation (`/prepare-delivery-feature`, 2026-08-12) introduces **no new
capability or MCP surface**: it is another consumer of the existing `ado-readonly` work-item
read through the shared `fetch-ado-item` skill (internal `direct-children` mode — the root
Feature plus direct-child summaries only), writing the Feature's `ado-context.md` and
`delivery-map.md` with the Designer's existing `work-items/**` grant. Solution Design's
delivery-map lookup is a bounded local file search, not a remote call.

QA test-plan authoring (`/prepare-qa-test-plan`, 2026-08-11) introduces **no new
capability**: the Test Strategist authors `work-items/<id>-<slug>/qa-test-plan.md` with its
existing grants — Knowledge tools, read-only ADO work-item tools (including relation and
linked-Test-Case Work Item reads), startup org identity proof, installed-package review, object-contract
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
child — never the CLI — against the identity-proven org within role limits, and rows return
unredacted (`attributes` noise stripped), bounded only by payload size and timeout. An
absent `review.allowedObjectApiNames` key means all objects (equivalent to `["*"]`) — an explicit
list remains supported and honored for orgs holding sensitive data. The facade remains the
preferred evidence path; the Developer may also use direct CLI when task execution requires it.

The read facade retains its live identity, denylist, allowlist and data limits. It may read
production within existing role permissions. Test Strategist remains prohibited from every
production target, including MCP; the owner accepts this instruction-level restriction.
Direct CLI access follows the shared production policy before any deployment confirmation.
Aliases and technical org types do not grant permissions.

Record-level reads run through `review_soql_query` alone: the guarded
`scripts/salesforce_read.py` CLI wrapper (structured record reads, cached metadata retrieve,
orgs listing) was retired on 2026-08-04 as a redundant second lane once composed SOQL was
unblocked. Metadata may be retrieved through direct CLI. Object access in the read facade is
bounded by `review.allowedObjectApiNames`,
which governs both schema reviews and record reads. Setting it to `["*"]` (or omitting it)
opts into every object. On a full-copy sandbox that means record reads can reach copied
production data across all objects — prefer an explicit list when the org holds sensitive
data.

Developer org execution remains limited to `dev`/`uat`/`stage`: reviewed direct CLI plus the
native operation tool, whose private job executor binds reviewed job operations to an exact org/ID.
The MCP launcher still spawns only the read facade; no write MCP or separate Deployment Agent is introduced.
Every exact real deployment needs fresh target/scope confirmation. Production CLI permits only
verified metadata retrieve; all other production CLI reads and writes are denied, including dry-run
validation and deploy job commands. Internal fixed MCP identity calls grant no direct CLI access.

Configuration uses `dev`, `uat`, `stage`, `prod`; `development` and `production` normalize to their
canonical values, while legacy `qa` requires explicit assignment. Any valid alias is supported and
multiple aliases may share an environment. Missing targets, conflicting identity, errors and timeouts
never authorize execution. Unknown targets and mutable latest selectors remain denied in the
terminal. The native Developer tool owns one-operation org/environment dialogs, rechecks and
execution; it pins supported latest jobs before dispatch. No persistent consent store or
agent-written classification flag is introduced. Its private session/executor is not a terminal
or MCP capability. See `docs/native-salesforce-operations.md` for installation and evidence bounds,
and `docs/production-read-only.md` for retrieve forms and migration.
