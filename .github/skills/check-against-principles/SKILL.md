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
(with `decisions.md` for deviations, and `ado-context.md` when present as the requirement
snapshot) — or the exact repository diff for an implementation —
plus exact proposed/implemented scope, repository revisions, environment proof, rule/entry
references, and current package identity when applicable. When the work item carries a
`qa-test-plan.md` and the subject is an implementation headed to QA, read the plan as review
input: an AC without a case, a case contradicting design/decisions, or a plan step that does
not match the implementation is a finding — the reviewer never edits the plan. Reject unspecified or chat-only
scope: chat summaries are not review input. For ADO-backed designs, check
acceptance-criteria coverage against the context's source snapshot (never the design's own
paraphrase or the unapproved AI understanding), and confirm the design's requirement
baseline names the context's current ADO revision — a newer context revision is a finding,
not something to absorb.

### The exact implementation review subject

An implementation review is of one Work Item's exact diff, never a guessed one.

- For a standalone `work-item/<ID>` delivery, the exact confirmed delivery-base-to-HEAD
  diff may be the subject when it is unambiguous.
- For a Work Item delivered on a shared `feature/<FeatureID>` branch, require an explicit
  subject: either `commits=<sha1>,<sha2>,...` (an explicit, possibly non-contiguous set) or
  a contiguous `base=<ref> head=<ref>` range attributable to that Work Item — and confirm
  the Work Item is listed as included in the current Feature delivery map. Never compare a
  Story design against the whole multi-Story Feature diff.
- `base` and `head` must appear together and define one contiguous range; never accept both
  input forms in one invocation. Missing half of a range, both forms at once, an
  unreachable or invalid ref, or an empty commit set is an incomplete review subject —
  stop before any semantic review.
- If attribution cannot be established, return `Scope alignment: INCOMPLETE`. Never infer
  the subject from commit titles, file proximity, chat, path order, or modification time.
  `[WI-<ID>]`/`AB#<ID>` commit attribution is consistency evidence: a mismatch with the
  supplied subject is a finding, but prose alone never selects the subject.

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

## Design coverage and planned scope (design review)

For a design-only review, assess the design's two compact sections against their contracts in
the solution-design skill:

- Every source AC or human-provided requirement outcome is represented by at least one
  `Acceptance criteria coverage` row against the persisted source criteria; compound sub-rows
  retain their parent source identity, and separate source ACs are never merged. A row marked
  `Covered` without both a named solution and a named planned verification is a finding, as is
  an omitted criterion (it must be `Open`, not absent).
- The `Planned change surface` is complete and internally consistent with the proposed
  solution: missing ownership, a proposed component absent from the table, or a package-owned
  component planned for modification is reported through the normal findings/verdict contract.
- No implementation comparison classification is emitted — there is no implementation subject
  yet.

## Scope Delta (implementation review)

Given the exact implementation subject, compare it with the current design and decisions:

1. resolve the current requirement/design baseline;
2. read the `Planned change surface` and `decisions.md`;
3. map changed files to logical Salesforce or material repository surfaces (metadata may
   decompose into several files — compare stable logical surfaces, with paths as evidence);
4. separate **direct support** from material surface change: tests, generated companions,
   manifests, and work-item documentation whose only purpose is to implement or verify a
   planned surface are support, not scope creep — but a new or modified Apex test class is
   deployable metadata and should normally be a planned surface, and a Permission Set, Custom
   Metadata type/record, Named Credential-related component, new Flow, new Apex class, or new
   integration configuration is material and cannot be hidden as support. A support artifact
   that changes independent behavior is reclassified as a material surface;
5. identify planned, missing, additional, removed, and substituted surfaces. A conditional row
   whose decision is unresolved is not expected work. `Read dependency only` never requires a
   repository diff — and a diff that modifies such a package-owned surface is both a scope
   mismatch and an independent managed-package finding (a `decisions.md` explanation is never
   permission);
6. check whether every material delta has an adequate append-only decision naming
   planned/actual surface and action, the reason, and material verification/rollback/QA
   impact;
7. classify **Scope alignment** before the normal findings/verdict:

   ```text
   Scope alignment: ALIGNED | EXPLAINED DELTA | UNEXPLAINED DELTA | INCOMPLETE
   ```

   - `ALIGNED` — material implementation surfaces match the current design; direct support is
     accounted for.
   - `EXPLAINED DELTA` — every material difference is traceable to an adequate append-only
     decision. **Explained is not safe and not approved**: package constraints, ownership,
     evidence, verification, authority, and all applicable Principles are still checked, and
     `EXPLAINED DELTA` never implies `SAFE`.
   - `UNEXPLAINED DELTA` — at least one material addition, removal, substitution, or action
     change has no adequate decision.
   - `INCOMPLETE` — the exact review subject, component identity, current design baseline, or
     required deviation evidence is unavailable or ambiguous.

Missing planned work is contextual: when the subject claims implementation completion or QA
handoff, a non-conditional planned `Create`/`Modify`/`Remove` surface absent from the
implementation is a `Missing planned implementation` finding; when the subject is explicitly an
in-progress slice, report the same absence as pending scope, not a completed-work defect.

For a final Feature PR review: identify included children from the current Feature
`delivery-map.md`, require every included child's current `design.md` and `decisions.md`,
compare the aggregate planned child surfaces with the final Feature diff, and treat Feature
coordination files separately from Story implementation. Missing or ambiguous child evidence is
reported (`Scope alignment: INCOMPLETE`), never replaced by invented attribution — and no
Feature-level `design.md`, scope file, or decisions log exists or is requested.

## Output

Return a table with: rule source/applicability, rule ID, entry identities, affected artifact,
scope/freshness, reconciliation, finding, and required action. For an implementation review,
state the one `Scope alignment` value before the findings. It never replaces the final
verdict: end with exactly one verdict:

- `SAFE`
- `NEEDS FIXES`
- `INCOMPLETE — NEEDS HUMAN`
- `STOP — TOO RISKY`

State the reviewed subject (work-item/design reference or diff), evidence completeness,
repository/org drift, any claimed review status and its evidence, and that nothing was changed.
