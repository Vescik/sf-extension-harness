---
name: check-against-principles
description: Ad-hoc read-only review of a persisted design or implementation against every applicable scoped Principle and its evidence.
argument-hint: "itemId=<ID> [scope=design|implementation] [base=<ref> head=<ref> | commits=<sha1>,<sha2>,...]"
agent: reviewer
---

Use the [check-against-principles skill](../skills/check-against-principles/SKILL.md).

Require the persisted subject — the work item's `work-items/<itemId>-<slug>/design.md` for a
design review (with `ado-context.md` as the requirement snapshot when present), or the exact
repository diff for an implementation review; chat summaries are
not review input.

For an implementation review, the subject is defined by the input, not inferred: a standalone
Work Item review may use the exact confirmed delivery-base-to-HEAD diff when it is unambiguous;
a Work Item review on a shared Feature branch requires explicit `commits=<sha1>,<sha2>,...` (an
explicit, possibly non-contiguous set) or a contiguous `base=<ref> head=<ref>` range. `base` and
`head` appear together and define one contiguous range; never accept both forms in one
invocation. Invalid, missing, unreachable, or ambiguous refs return an incomplete review
subject before any semantic review. This prompt defines input only — the complete procedure,
including Scope alignment, is the skill's. Evaluate it (per `scope`, default: design when a design.md exists)
against every applicable scoped Principle, fresh verified Knowledge, and repository/org
reconciliation.

Review only — never implement fixes, edit files, or weaken a constraint to make the result pass.
Return the verdict (`SAFE`, `INCOMPLETE — NEEDS HUMAN`, or violations found), every violated rule
ID with its evidence, and unresolved gaps. Incomplete or stale evidence can never yield `SAFE`.
