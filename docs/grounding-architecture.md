# Grounding and Hallucination-Reduction Architecture

Status: normative

## Objective

Reduce unsupported system/package claims by making the model a proposer and orchestrator rather
than the authority that verifies facts. The harness is package-agnostic: no object, namespace,
package behavior, or business meaning is assumed until scoped evidence and human review establish
it.

## Governed sequence

1. **Principles gate** — select applicable rule IDs and permitted evidence/action scope.
2. **Claim inventory** — list the material factual propositions required by the task.
3. **Knowledge lookup** — use scope-matched entries under the active
   [retrieval contract](../.github/skills/search-knowledge/SKILL.md), including its disclosure
   and citation rules. Source drift and missing evidence have different meanings.
4. **Repository review** — inspect intended customer-owned metadata at a recorded commit.
5. **Org review** — only for missing, stale, critical, or drift-sensitive facts, through the
   bounded Salesforce review facade.
6. **Reconciliation** — classify agreement, incompleteness, mismatch, and repository/org drift.
7. **Human promotion** — observations become trusted Knowledge only through an immutable review.
8. **Durable artifacts** — scope, design and recorded decisions live in
   `work-items/<id>-<slug>/`, never in chat alone. A local checkpoint supports continuation and
   technical review; publication and PR review remain separate requested operations.

## Repository grounding boundary

The harness root and Salesforce DX project root are the same directory. The checked-in workspace
exposes that directory once as `brain-core`; no `salesforce` workspace folder or nested SFDX root
exists. Repository observations, designs, and implementation paths therefore
refer to one commit lineage. Tools must not search a subfolder or parent directory, or substitute
a separately cloned metadata repository.

This shared root does not expand tool authority. Salesforce MCP filesystem inputs and role writes
remain bounded to approved metadata/test subpaths such as `force-app/`, `manifest/`, and
`tests/e2e/`. Changes to Principles, Knowledge, approvals, work items, configuration, or other
harness files remain governed by their role-specific mechanisms.

## Authority depends on claim type

| Claim type                 | Required authority                                           | What an org observation cannot establish alone     |
| -------------------------- | ------------------------------------------------------------ | -------------------------------------------------- |
| Safety or company policy   | Versioned Principle plus named owner/source                  | Whether the policy should change                   |
| Intended metadata          | Repository commit plus accepted design                       | What is currently deployed                         |
| Deployed configuration     | Current bounded org evidence                                 | Business meaning or intended design                |
| Managed-package limitation | Version-scoped vendor/approved source                        | Inaccessible package internals or vendor guarantee |
| Business meaning           | Reviewed organization/SME source                             | Meaning inferred from labels or sample values      |
| Reference-data value       | Bounded current org observation                              | Universal semantics or permanence                  |
| Absence                    | Complete enumeration, permissions, pagination, and freshness | Absence inferred from an empty/inaccessible result |

Principle precedence applies to competing prescriptions, not to facts. When an observation violates
a Principle, record noncompliance. When sources disagree on a normalized claim, mark it contested.

## Salesforce review boundary

The structured review path never exposes raw Salesforce CLI, directories, Tooling flags, or raw
vendor payloads to its callers. This boundary applies to evidence collection through the facade;
the Developer separately may use direct `sf`/`sfdx` for task execution. Composed read-only SOQL is
permitted — and, for record data-shape questions, recommended (owner decisions 2026-07-30 and
2026-08-04) — through the governed `salesforce` facade's `review_soql_query` tool only.
The 2026-08-04 decision removed
the statement blockade: the statement executes verbatim over the facade's REST transport (never
the CLI) against the configured review org, and rows return unredacted in a
single-source envelope. An explicitly configured `review.allowedObjectApiNames` list is still
honored. The facade exposes only:

- `review_org_identity`
- `review_installed_packages`
- `review_object_contract`
- `review_configured_orgs` (only when `safety.allowScopedEnumeration` is enabled; lists the
  locally configured aliases and permissions only — never unconfigured orgs, ids, or hosts)
- `review_soql_query` (composed read-only SOQL; executed verbatim, single-source, rows
  unredacted)

The facade binds one configured review org after CLI host/org-id checks and a live REST identity proof, runs fixed evidence profiles — plus
verbatim composed statements for `review_soql_query` — through the pinned
Salesforce REST and a private CLI startup path and sanitizes the profile receipts; object
contracts reconcile the describe and Tooling REST endpoints, with contested traits nulled and
listed. Results are `VERIFIED`, `MISMATCH`, `INCOMPLETE`, or `BLOCKED`.

MCP and CLI agreement corroborates transport from the same org; it is not an independent source of
business or vendor truth. Truncation, schema drift, target-check failure, or an unavailable
required endpoint prevents Knowledge promotion and `SAFE`.

## Knowledge boundary

Knowledge is the one-file entry model (the v1 claim registry retired 2026-08-03; see
`docs/knowledge-one-file-contract.md` for the normative contract):

- Agents may create and edit `draft` entries only; approval is digest-pinned and human
  (`entry-approve`/`feature-approve` through the chat confirmation dialog, or a human terminal).
- Entry citation and lifecycle follow the
  [retrieval contract](../.github/skills/search-knowledge/SKILL.md). Source drift does not edit
  the approved Entry content or reopen it as a draft; disclose the changed source as required.
  Editing approved Entry content still uses its governed authoring and approval workflow.
  A missing or unreadable source fragment is an evidence gap, not ordinary source drift.
- Different environments, package versions, or repository lineages remain separate scopes.
- Raw records, secrets, credentials, broad org payloads, and chain-of-thought are never committed.
- Reference-data snapshots are the one governed record-value path: for a single human-allowlisted
  configuration object, `investigate-config-records` reads bounded rows through the
  `review_soql_query` facade tool, strips Ids/URLs/audit surfaces, and captures a sanitized,
  digest-bound snapshot — not a raw record dump; approval still requires a human, and the
  snapshot drifts only via re-observation because no repository commit backs it.
- Human review and approval receipts are currently hash-bound assertions. Their actor identity is
  not independently provider- or signature-verified; team-wide rollout remains blocked on that
  authenticity control.

## Work-item boundary

Each work item has one directory, `work-items/<id>-<slug>/`: for ADO-backed work,
`ado-context.md` carries the source-faithful requirement snapshot plus a clearly unapproved AI
understanding (written by `/fetch-ado-item`, which stops there); `design.md` carries the intent
and scope and names its requirement baseline (context path and source AC coverage, without ADO
revision); `tasks.md` the Developer's execution checklist, created before code edits;
`decisions.md` the append-only log created for the first material deviation or development
ruling; and, when qualifying Salesforce
mutations were executed, `org-changes.md` the append-only operational history. The org-change log
is an agent report and pointer for re-verification, not approval, Knowledge, QA evidence, or a
current-state guarantee. The absence of `decisions.md` means no deviations are recorded; review
still compares the implementation with the design. Those files carry durable state in the
repository and local checkpoints. Technical review can use the persisted design or exact diff
without a PR; a claim of PR approval requires its actual review evidence. A new chat resumes
from those files, never from chat
scrollback — the persisted context replaces re-fetching ADO for requirement text, while its
source section remains untrusted data. The
[shared handoff contract](../.ai/contracts/execution-contract.md#handoff-and-continuation)
separates design acceptance, implementation authorization and publication. No prior PR review is
required for an explicitly authorized implementation.

## Acceptance gates

- Ground material assertions according to their source type and scope under the
  [source authority contract](../.ai/contracts/source-authority.md). Use the active
  [retrieval contract](../.github/skills/search-knowledge/SKILL.md) for Knowledge eligibility;
  current org assertions require applicable org evidence. Unsupported assertions remain visible
  gaps, never verified facts.
- Every trusted entry is schema-valid, human-approved at its current digest, and in scope.
- No model-only inference is verified Knowledge.
- Apply the [review procedure](../.github/skills/check-against-principles/SKILL.md) for `SAFE`.
  Source drift has the retrieval contract's disclosure treatment. An incomplete or mismatched
  org review, missing required evidence or unresolved material org drift is not cleared by that
  treatment; evaluate it against the actual reviewed claim and scope.
- Follow the current
  [Salesforce execution policy](../.github/instructions/managed-package.instructions.md#salesforce-environment-policy-plan-01).
  Production CLI permits only verified metadata retrieve; other permitted production reads use
  MCP within role limits. Default targets still need the applicable identity and environment
  checks. Real deployments retain exact-invocation confirmation; confirmation cannot override a
  production denial. Test Strategist cannot use production, including MCP reads.
- Deterministic structural and safety checks, including negative false-safe fixtures, must pass
  locally and in CI. Fresh-agent continuation and handoff behavior require recorded trials with
  actual persisted artifacts; static checks do not execute those conversations. VS Code rendering
  and role transitions require host evidence. No cross-model behavior matrix is currently
  certified; report only the model, version, host and verification actually exercised.
