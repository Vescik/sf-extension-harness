---
name: check-against-principles
description: Evaluate a scoped design or implementation using the governed Principle rules, approved Knowledge Entries, repository/org reconciliation, approval hashes, and complete evidence. Read-only; never implement fixes.
user-invocable: false
---

# Check against Principles and evidence

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md).

## Inputs

Require a valid `recordId`, optional incoming `handoffId`, exact proposed/implemented scope,
repository revisions/diff, environment proof, rule/entry references, current package
identity when applicable, and accepted design/approval hashes. Reject unspecified or chat-only scope.

## Procedure

1. Validate work state, handoff target/revision, approval binding, and affected-artifact list.
2. Load the Principle instruction files and check Tier 1 package constraints, Tier 2 organization
   policy, and Tier 3 Salesforce practice in order. Apply precedence only to competing prescriptions.
3. Discover, then require. First establish the baseline of facts the design must address — do not
   rely only on what the author happened to cite. Query both layers:
   - the `knowledge_context` tool for each affected
     artifact (source-declared facts, parts, dependents, permission grants, in one call;
     `knowledge_resolve` maps bare names and paths to identities). Only
     `parts`, `permissions` and `incoming` are approved-current; the `partsNonCurrent` /
     `permissionsNonCurrent` / `incomingNonCurrent` siblings are opted-in lanes and can never
     make a premise `verified`. `incoming` and `outgoing` are keyed by relation kind, so iterate
     the keys rather than a flat list, and treat an absent kind as silence, not as absence. A row
     carrying `hydrated: false` failed re-reading, so it can never make a premise `verified` —
     record it as a gap;
   - the `knowledge_search` tool with a `relationAnchor` and `direction: incoming`
     for dependents beyond the context pack's depth-1 view. Only generic-bucket
     types (Settings, Letterhead, Group and similar label-only extraction) have no entry and
     no governed dependency lookup — name them explicitly when present, or the result looks
     clean while a whole class went unchecked.
   An empty result from either layer is a recorded gap, never proof that nothing depends on it. Then, for every material factual premise,
   require an `approved`, scope-matched entry — `approved-drifted` counts, carried into the
   review as an explicit caveat, and org-usage numbers count with their age stated
   ("sampled N days ago"). Drafts, revoked entries and model inference are not trusted
   facts. Knowledge freshness has three different fates, not one: drift and expired
   org-usage travel as caveats exactly like `limitations`; a failed re-read caused by the
   file changing since the index was built is a rebuild-and-retry
   (`knowledge_search.py build`), not a finding; a failed re-read for any other reason
   (file missing, entry does not parse, identity/digest mismatch) is a real gap — report
   it, do not build on that entry. When a cited envelope
   carries entry references, `python scripts/knowledge_store.py entry-verify-citations
   --envelope <path>` reports any that no longer resolve to a current approved entry.
4. Compare intended customer-owned repository state with the latest complete org-review evidence.
   Report drift instead of selecting one source.
5. Distinguish an observed fact that violates a Principle from evidence that contests a factual
   entry. Principles do not rewrite facts; observations do not weaken rules.
6. Require complete environment proof, package/component ownership, version, supported extension
   point, role compliance, verification, coverage, and manual steps where relevant.
7. A drifted/revoked/partial entry, incomplete org review, ungrounded component, missing
   source/version, stale approval, or unresolved blocking question makes `SAFE` impossible.

## Output

Return a table with: tier, rule ID, entry identities, affected artifact, scope/freshness,
reconciliation, finding, and required action. End with exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State `recordId`, evidence completeness, repository/org drift, and that nothing was changed.

## Knowledge grounding: two layers

Query both layers through the knowledge tools and read their envelopes by the
[search-knowledge](../search-knowledge/SKILL.md) rules — authorities, lane handling and
citation mechanics live there, once; do not re-derive them here. In short: approved
entries ground intended repository-source facts, cited as `entryRef` via the
`knowledge_entry_status` tool (a search result, a `context` pack and a generated view are
never themselves citable); org usage grounds usage numbers cited with orgKey, observedAt
and their age; runtime behavior, business meaning and vendor guarantees have no governed
Knowledge surface — mark them `UNVERIFIED` with their source. A missing hit is never
proof of absence. An approved entry can still refuse to ground a fact: contract §8.1
grounds only `source-exact`, fully covered sections — check the entry's
`extractionCoverage` and `assurance` (heuristic-derived facts, common across the Apex
layer, are refused). Take the refusal as the answer: report the fact as inferred and name
what would make it groundable — never retry with a different ref shape.
