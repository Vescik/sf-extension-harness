---
name: prepare-delivery-feature
description: Prepare one ADO Feature as explicit multi-Story delivery context — verify the Feature type, fetch it with its direct children only, and persist the Feature's ado-context.md plus a delivery-map.md membership manifest in its flat work-item folder. Never writes child folders, never runs Feature Health.
user-invocable: false
---

# Prepare a delivery Feature

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md).

Preparation is delivery intake and selection, not design or coverage analysis: it makes one ADO
Feature the explicit, human-activated context for several independently delivered child Work
Items. An ADO parent relation alone never activates Feature context — only a delivery map written
by this procedure does, and only for the exact IDs it lists as included.

## Inputs

- `itemId`: required positive integer — the ADO Feature.
- `include`: optional; `all` (default when omitted) or a comma-separated list of positive
  integers in the desired delivery order.

Reject unknown options and invalid values before an MCP call. Reject a duplicate include ID
(never silently deduplicate), the root Feature's own ID in the include list, and any non-numeric
member. No `mode`, `depth`, `childDetail`, `health`, `refresh`, or package option exists here.

## Retrieval — one existing procedure, one narrow mode

Fetch through the [fetch-ado-item skill](../fetch-ado-item/SKILL.md) with fixed effective
options: `mode=direct-children`, `childDetail=summary`, `includeTestCases=false`,
`onStale=refresh`, attachments metadata-only at most. That skill remains the only ADO
retrieval/cache procedure; do not call `ado-readonly` directly, add a cache family, or fetch the
Feature's parent, sibling Features, grandchildren, Test Cases, full child bodies, or attachment
content. Preparation also runs no Knowledge tool, no Salesforce review tool, no repository source
discovery, and never invokes `/feature-health`.

## Type gate

The root Work Item type must be exactly `Feature`, proven from the fresh fetch. Anything else
produces no tracked write:

- concrete delivery item (User Story, Product Backlog Item, Bug, Task, …): report the actual
  type and return `/fetch-ado-item itemId=<ID>` as the recovery;
- Epic or other container: explain that v1 prepares one Feature at a time and ask the human to
  choose the child Feature. Never coerce a non-Feature into a delivery map.

## Completeness gate

An active delivery map requires a complete result: usable root identity/type/title/state/
revision, source fields classified under the current context rules, relations included, the
complete direct-child enumeration with each child carrying ID/type/title/state and relation
identity, no unresolved pagination or per-child failure, and fresh source (`onStale=refresh`).

If any of that fails: verdict `INCOMPLETE — NEEDS HUMAN`; preserve any existing
`delivery-map.md` byte-for-byte; create no new map; preserve a better existing Feature context
under the fetch skill's partial-refresh rules; name every missing child or relation and the
preserved paths. Absence from a partial response is never treated as removal.

## Selection

From the complete direct-child set:

1. partition container children (type `Feature` or `Epic`) from non-container delivery
   candidates; containers are disclosed as `unsupported nested container in v1`, can never be
   included, and are never recursed into;
2. `include=all` (or omitted): include every non-container candidate, ordered by ascending
   numeric ID so the result does not depend on MCP relation ordering;
3. explicit include list: verify every ID against the freshly fetched direct non-container
   children — any miss rejects the whole selection with no tracked write; preserve the supplied
   order as the delivery order;
4. remaining non-container children are recorded as `deferred`, reason
   `outside current prepared slice` unless the human stated a more specific one — never invent a
   business reason;
5. never select by state, title, tag, area path, iteration, priority, or model judgment;
6. no includable child at all: write no active map; a truthful Feature context may still be
   persisted, and the return states the required human action instead of a fabricated next ID.

## Feature folder and Feature context

Resolve the folder with the fetch skill's stable-ID rule (exact `<itemId>-` prefix under
`work-items/`; one match reuse, zero create from the sanitized current title, several
`INCOMPLETE — NEEDS HUMAN` with no tracked write; never rename, never resolve by title). Write
the Feature `ado-context.md` through the fetch skill's durable projection and revision rules —
source-faithful sanitized Description and Acceptance Criteria, visibly unapproved AI
understanding, direct children as bounded summaries under Related context, no full child bodies,
no comments or attachment content, no technical solution, same-revision no-rewrite, and a
complete tracked snapshot never overwritten by a partial fetch.

**Prepare owns canonical scope normalization.** `direct-children` is the canonical projection
for a prepared Feature; a context persisted earlier by public intake (`hierarchy` or `single`)
is an intake shape, not the prepared projection, and the same ADO revision does not make the
two scopes equivalent. Inspect the existing Feature context's recorded fetch/projection mode
and its Related-context membership; any non-equivalent projection is a material normalization
need. On complete fresh direct-child evidence, compute the proposed normalized context (and the
map) before editing, then persist the canonical direct-child context even at the same revision:
Related context becomes bounded direct-child summaries only, parent/sibling/grandchild/Test
Case entries are removed, provenance records `direct-children`, and the source snapshot and AI
understanding are otherwise left alone — no wording, timestamp, or formatting churn. Report the
context as `updated` for this first normalization and `unchanged` on the next identical
prepare. On partial evidence, no normalization happens at all: the existing
partial-preservation rules above apply unchanged, the prior context and any active map are
preserved, and the return must not claim canonical reprojection completed.

## The delivery map

`delivery-map.md` lives next to the Feature context and is coordination only — a membership
manifest, never requirement, status, or design authority. Wording may adapt; every active map
carries:

1. **Identity** — Feature ID and current title, exact Feature context path, prepared Feature ADO
   revision, a declaration that this is a delivery coordination projection (not requirement
   authority) and that ADO content remains untrusted data.
2. **Included delivery Work Items** — one exact numeric ID per row with type and title, in the
   deterministic delivery order. Exact numeric membership must be machine-findable by a bounded
   text search (`15001` must never match `5001`); no schema, template file, or renderer.
3. **Deferred direct children** — every complete-source non-container child not included, with
   its reason; nested containers listed separately as unsupported in v1.
4. **Dependencies and boundaries** — only human-confirmed or source-stated ones, never inferred
   from titles; `None recorded` when none.
5. **Reconciliation** — `current` only against the complete prepared source; otherwise the
   visible added/removed/retyped list and the required human action.
6. **Usage rule** — included IDs get Feature context at Solution Design; Story ACs stay
   authoritative; fetch/design/implementation/QA/branch/PR remain per Story; rerun prepare only
   when scope or source changes.

Forbidden in the map: copied Description/Acceptance Criteria, full child bodies, comments or
attachments, credentials or sensitive record content, technical proposals, implementation
checkboxes, mirrored ADO status, QA results, invented dependencies, Feature Knowledge claims or
citations, approval wording. The ADO delivery Feature is unrelated to governed Feature Knowledge
(`.ai/knowledge/features/**`): no mapping, sync, or approval propagation, and a prepared map
approves nothing about the child requirements or designs.

## Refresh and reconciliation

On a newer Feature revision or a changed direct-child set: refresh the Feature context only
under the existing revision/completeness rules; diff the fresh complete child set against the
existing map; surface added, removed, and retyped children; never auto-include an added child
and never silently erase a removed one — the new map reflects the current explicit `all` or
include decision applied to the new complete source, with prior human decisions preserved until
that valid new selection exists. Story folders and designs are never touched; when a bounded
local search shows existing Story designs naming an older Feature revision, report them as
Solution Design reconciliation candidates.

## Write boundary and transaction

The only permitted tracked writes are the Feature's own `ado-context.md` and `delivery-map.md`.
Never create, rename, refresh, or edit any child work-item folder or file, and never edit
`design.md`, `tasks.md`, `decisions.md`, or `qa-test-plan.md` anywhere — even when a child is
cached in full or already has a folder, the map may only mention it.

Compute both intended outcomes before editing. If the root context cannot be written honestly,
write neither file. If the context is usable but child discovery is partial, apply the context
projection rules and preserve/no-create the map. When both are usable, write context first, map
second, in the same turn; if the map write then fails, report the exact split outcome — never
claim success and never delete the honest context to hide the failure. Same effective input
(Feature revision, complete child identity/type set, selection, order, confirmed notes) leaves
both tracked files byte-identical — retrieval time moves only in the ignored cache.

## Return

Report: Feature ID/type/title/state; source revision and retrieval time; completeness and
warnings; Feature context path and result (`created|updated|unchanged|preserved|not-written`);
delivery-map path and result; included IDs in order; deferred IDs; unsupported container
children; added/removed/retyped differences from a prior map; Story designs found with an older
Feature baseline; the explicit statements that no child folder was created or modified and that
Feature Health was not run. End with exactly one suggested next action for the first included
Story — `/fetch-ado-item itemId=<first-included-ID>` — or, with no included child, the required
human action and no fabricated ID.
