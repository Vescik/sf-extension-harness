---
name: check-against-principles
description: Evaluate a scoped design or implementation using Principle rules, approved Knowledge Entries, repository/org reconciliation, and complete evidence. Read-only; never implement fixes.
user-invocable: false
---

# Check against Principles and evidence

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md),
[source authority contract](../../../.ai/contracts/source-authority.md).

## Inputs

Require the persisted subject under review — `work-items/<id>-<slug>/design.md` for a design
(with `decisions.md` for deviations), or the exact repository diff for an implementation —
plus exact proposed/implemented scope, repository revisions, environment proof, rule/entry
references, and current package identity when applicable. Reject unspecified or chat-only
scope: chat summaries are not review input.

## Procedure

1. Validate the persisted review subject, repository revision, affected-artifact list, and —
   when approval is claimed — evidence of the current pull-request review. Never infer approval
   from file presence or chat context.
2. Load `.github/copilot-instructions.md` and every scoped Principle instruction whose `applyTo`
   matches an affected path. Apply precedence only to competing prescriptions.
3. Discover the baseline of facts the subject must address instead of relying only on citations
   supplied by its author. Ground findings in Knowledge first, applying the
   [search-knowledge](../search-knowledge/SKILL.md) retrieval rules verbatim — same tools, lane
   handling, and citation mechanics; do not re-derive them here. Run `knowledge_context` for each
   affected artifact. A row carrying `hydrated: false` is a gap and cannot be cited. Name every
   generic-bucket type in scope as an unchecked class in the findings — silence about it reads as
   a clean review it did not earn.
4. Compare intended customer-owned repository state with the latest complete org-review evidence.
   Report drift instead of selecting one source.
5. Distinguish an observed fact that violates a Principle from evidence that contests a factual
   entry. Principles do not rewrite facts; observations do not weaken rules.
6. Require complete environment proof, package/component ownership, version, supported extension
   point, role compliance, verification, coverage, and manual steps where relevant.
7. Draft, revoked, not-effective, unhydrated, integrity-invalid, scope-mismatched, or materially
   partial evidence cannot support `SAFE`. Approved-drifted remains effective and requires
   disclosure only. An incomplete org review, an ungrounded component, a missing source/version,
   an unverified review claim, or an unresolved blocking question disqualifies `SAFE` the same way.
   Before issuing the verdict, verify every supplied envelope with `python
   scripts/knowledge_store.py entry-verify-citations --envelope <path>`. Invalid citations block
   `SAFE`; approved-drifted produces disclosure only.

## Output

Return a table with: rule source/applicability, rule ID, entry identities, affected artifact,
scope/freshness, reconciliation, finding, and required action. End with exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State the reviewed subject (work-item/design reference or diff), evidence completeness,
repository/org drift, any claimed review status and its evidence, and that nothing was changed.
