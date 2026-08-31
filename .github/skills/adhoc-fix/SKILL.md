---
name: adhoc-fix
description: Express lane for a small bounded defect fix, including optional confirmed deployment and org verification.
user-invocable: false
---

# Ad-hoc defect fix (express lane)

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
[Managed Package Boundaries](../../instructions/managed-package.instructions.md).

This lane is the owner-approved exception (decision of 2026-07-23) to the developer
accepted-design entry gate. It exists so a diagnosed defect — a broken Flow decision, a wrong
validation formula, a mislabeled field — can be fixed in the repository the moment the diagnosis
is in hand. Everything else about the role's boundaries is unchanged: edits stay inside
`force-app/`, `manifest/`, and `tests/e2e/`; a real deploy follows the Developer's single-use chat
confirmation rule.

## Entry conditions

- A written diagnosis exists: what is broken, in which component, expected vs. actual behavior,
  and the evidence trail (investigation output, error message, or the user's own description).
  Restate it at the top of the fix note; do not start editing from a vague "something is wrong".
- The fix is small and bounded: one defect, the smallest coherent set of components (typically
  one), no new automation, no object/field schema changes, no permission changes. When the fix
  grows beyond that, stop and route through the normal design lane instead of stretching this one.
- Package ownership and namespace are recorded as impact context, not used as a harness-level deny.

## Procedure

1. Retrieve the current org state of the target component before editing, so the fix is based on
   what is deployed, not on a stale local copy:
   `sf project retrieve start --target-org <configured-alias> --metadata <Type:Name>`
   (the target may be explicit or use the normal project/default CLI context).
2. Read the retrieved source and confirm the diagnosis against it — the exact element, formula,
   or connector that is wrong. When the defect plausibly depends on real record shape (field
   fill, picklist values in use, lookup population), probe it through the governed
   `review_soql_query` facade tool — verbatim SOQL over the facade's REST transport — rather
   than assuming — preferred practice per the 2026-07-30/2026-08-04 owner decisions; probed numbers quoted
   in the fix note cite the org alias and observation time. If the retrieved state
   contradicts the diagnosis, stop and report instead of guessing.
3. Consult Knowledge for dependents before touching the component, both layers:
   - the `knowledge_context` tool — who reads, writes and
     grants access to it today, with per-edge assurance (`knowledge_resolve` maps the
     component's name or file path to its identity). `parts`, `permissions` and `incoming`
     hold the effective approved rows; the `*NonCurrent` siblings are opted-in non-effective
     lanes and are reported as unknowns in the fix note, never as dependents you have accounted
     for. A row with `hydrated: false` failed re-reading — it is an unknown in the fix note,
     never a dependent you have accounted for. Lane semantics, bucket rules and the
     generic-bucket types are defined once in
     [search-knowledge](../search-knowledge/SKILL.md); when a generic-bucket type sits in the
     blast radius, name it as an unknown in the fix note.
   An empty result from either layer is a recorded gap and is NEVER proof that nothing depends on
   this component. When the fix note cites a repository fact, cite what the executor gives you,
   not what the view shows: obtain the citable ref with `python scripts/knowledge_store.py
   entry-status --identity <Identity>`; a `context` pack is never itself citable. Apex-layer
   entries generally cannot be cited as positive grounding — contract §8.1 grounds only sections
   marked `source-exact` with full coverage, and Apex facts are regex-derived — so for an Apex
   defect quote the retrieved source you read in step 2 and report the entry as inferred.
4. Make the smallest coherent edit in `force-app/`. Match the existing metadata style; change the
   defective element, not the surrounding structure.
5. Verify what can be verified locally: the XML parses, the changed element is the only
   difference against the retrieved copy, and any referenced fields/labels/subflows exist in the
   local source or verified Knowledge.
6. Write the fix note to `output/documentation/adhoc-fixes/<yyyy-mm-dd>-<component>.md`:
   diagnosis (verbatim), files changed, the exact before → after of the defective element,
   verification performed, the proposed deploy command and component list, and the rollback path.
7. If a real deploy is in scope, state the target and scope, warn that changes will be deployed to
   the org, and ask `Should I run this deployment?` Run the exact command only after an
   unambiguous answer. Record the job and verify org state. After the result, append the
   operation once to the canonical durable log using the
   [Development skill](../development/SKILL.md) — the applicable Work Item/Feature log when one
   exists, otherwise `docs/org-changes/<yyyy-mm-dd>-<slug>.md`. Link that path from the ignored
   fix note; never duplicate the entry or leave the fix note as the sole durable record. Recommend an
   after-the-fact guardrail review — the human opens the reviewer role on the fix note
   and changed files; record the verdict by appending a `Review outcome` section to the note.
8. If the defect or its fix reveals durable facts worth keeping (error surface, config meaning),
   route them through `/pin-knowledge` afterwards; this skill itself writes no Knowledge.

## Prohibitions

- Never run a real deploy without fresh confirmation for that exact target, scope, and command.
- Never fix more than the diagnosed defect in one pass — no drive-by refactors, no "while I'm
  here" cleanups, no scope growth past the bounded-fix entry condition.
- Never edit outside `force-app/`, `manifest/`, `tests/e2e/`, the fix note, and the single
  canonical org-change log; approvals,
  Knowledge, Principles, and records remain out of reach.
- Never present the repository edit as deployed, fixed-in-org, or verified-in-org without a
  successful deploy receipt and explicit verification.

## Return

Return the fix note path; the diagnosis summary; files changed with the before → after of the
defective element; local verification performed; the proposed or executed deploy command and
component list; deployment receipt and org verification when run; the rollback path; and the
canonical org-change-log path (or `none — no qualifying org mutation executed`); and the
recommendation to run the after-the-fact guardrail review.
