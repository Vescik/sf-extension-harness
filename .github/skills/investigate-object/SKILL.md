---
name: investigate-object
description: Collect bounded, sanitized evidence about a scoped Salesforce component or package question, report it read-only, and persist org observations only through the governed entry-org-attach lane.
user-invocable: false
---

# Investigate a Salesforce component question

This is a read-only investigation lane: the outcome is a sanitized report, optionally
persisted org-usage numbers via the governed `entry-org-attach` executor. Nothing here
creates citable Knowledge by itself — durable repository facts live in one-file Knowledge
Entries, and semantic org/vendor conclusions belong in the report (or, when
boundary-level, in a Feature Entry's human prose).

## Input

Require the exact question, normalized package/component subject, environment,
criticality, and why current Knowledge/repository evidence is insufficient. When delivery
work raised the investigation, note the work item (`work-items/<id>-<slug>/`) so the
report can be linked from it; a standalone read with no work item is a valid lane and not
a reason to stop.
Reject a generic “inspect the org,” unspecified target, record dump, or component outside
the configured review allowlist. Route record data-shape questions (structure, fill,
distributions) to the governed record reads instead of rejecting them (owner decision
2026-07-30): `review_soql_query` on the facade, or
[investigate-config-records](../investigate-config-records/SKILL.md).

## Procedure

1. Read relevant approved Knowledge Entries plus metadata-repository state (the
   `knowledge_context` tool; re-read any `hydrated: false` row from its entry file before
   relying on it).
2. Classify the source authority required. A package guarantee needs a vendor source;
   business meaning needs reviewed human evidence; live deployed configuration may use
   org observation.
3. Define the smallest factual proposition. For an absence question, report what you
   checked and how — enumeration scope, method, pagination bounds, and limitations — and
   state absence as an observation within those bounds, never as proof. Whether that
   coverage suffices is the reviewer's judgment, not a precondition for reporting.
4. Call `review_org_identity` first. Stop unless it is `VERIFIED` for the exact configured org with `nonProduction: true` (a Developer Edition legitimately reports `isSandbox: false`).
5. Call only the necessary guarded review tool:
   - `review_installed_packages` for package identity/version;
   - `review_object_contract` for an allowlisted object's accessible existence/field contract.
6. Treat MCP/CLI agreement as transport corroboration. On `MISMATCH`, `INCOMPLETE`, truncation,
   schema drift, sensitive-output detection, or scope mismatch, return unresolved.
7. Write the sanitized findings as a report under `output/` (investigation reports are
   documentation, not Knowledge authority). Record limitations, repository drift, package
   version, and missing authority in the report itself.
8. When the finding should outlive the chat and the subject has an approved entry
   (CustomObject, CustomField), persist the numbers through the org-sampling step below
   instead of quoting transcript values.
9. After describing a CustomObject or CustomField entry, consider `entry-org-attach`
   when fill rate or real data shape matters for what the entry is for — it is a
   separate, deliberate step (static drafts carry repository facts only), and it needs a
   configured non-production alias with `expectedOrganizationId`. Skipping it is fine;
   forgetting it should not be.

## Entry-lane org sampling (governed persistence)

When the selected Salesforce review MCP session has started and proven its non-production
identity (successful review tool evidence from this session), org sampling is the
default persistence path for object/field usage numbers. For each target entry whose org lane
is not already `org-fresh` (recompute it with
the `knowledge_entry_status` tool — never from chat history):
compose read-only SOQL probes for the entry's object — aggregates (COUNT, GROUP BY, COUNT(field)
fill counts) plus one bounded row sample (explicit `LIMIT 25`, `ORDER BY CreatedDate DESC`,
at most 20 contract-derived columns; never select Id, Email-type, or long-text values — measure
their fill with aggregate probes instead). Several probes of one kind under different WHERE
criteria are legal and encouraged when data diversity depends on status or record type
(owner decision D-5', 2026-08-03). Write the probes-file under `.cache/org-usage/pending/`
(`{"probes": [{"label", "kind", "query"}]}`) and run
`python scripts/knowledge_store.py entry-org-attach --identity <id> --org <alias>
--probes-file <path>` — the executor re-runs every probe through the governed facade, derives
the closed count/shape vocabulary (row values never persist), and attaches click-free with the
machine attestation the owner approved as the instrument. When no org is configured or
containment refuses, skip silently and report `orgUsage: skipped (<reason>)`. An expired or
superseded org block stays usable as an aged observation: report the number with its age
(“sampled N days ago”), and re-attach or run a live probe when the question needs current
data. `entry-org-detach --identity <id> --org <alias> --rationale <text>` is the rollback.

## Prohibitions

- Never invoke or suggest direct `sf`/`sfdx`, SOSL, an alias, a directory, a Tooling flag, broad
  record retrieval, or an unguarded Salesforce MCP tool; composed read-only SOQL runs only
  through the governed facade's `review_soql_query` tool — never through raw CLI or raw vendor
  tools.
- Never infer inaccessible package internals or treat no returned row/component as proof of absence.
- Never return or persist credentials, usernames, raw org/package/record IDs, URLs, raw vendor
  payloads, labels/help text, picklist values, or unnecessary business data. For configuration
  values held as records in a reference-data table, use the governed exception
  [investigate-config-records](../investigate-config-records/SKILL.md) instead.
- Never call an observation `confirmed` or `verified`, and never present the report as citable
  Knowledge — approved entries ground later work regardless of drift or org-usage age (both
  travel as visible caveats); drafts and revoked entries never do.

## Return

Return `EVIDENCE COLLECTED`, `INFERRED`, or `UNRESOLVED`; the report
path under `output/`; any entry identities with freshly attached org usage; exact scope;
source/reconciliation status; repository drift; limitations; missing authority; and what a
human should verify next. No mutation of Salesforce is permitted.
