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
- `include`: optional; `all` or a comma-separated list of positive integers in delivery order.
  On first preparation, omission defaults to `all`. On an existing map, omission preserves the
  prior explicit selection/order; it is not a new instruction to absorb every current child.

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

An active delivery map requires a complete result: usable root identity/type/title/state,
source fields classified under the current context rules, relations included, the
complete direct-child enumeration with each child carrying ID/type/title/state and relation
identity, no unresolved pagination or per-child failure, and fresh source (`onStale=refresh`).

If any of that fails: verdict `INCOMPLETE — NEEDS HUMAN`; preserve any existing
`delivery-map.md` byte-for-byte; create no new map; preserve a better existing Feature context
under the fetch skill's partial-refresh rules; name every missing child or relation and the
preserved paths. Absence from a partial response is never treated as removal.

## Selection

From the complete direct-child set:

1. partition the current source's container children (type `Feature` or `Epic`) from
   non-container delivery candidates. A new selection never includes containers or recurses
   into them; disclose them as `unsupported nested container in v1`. This eligibility check
   does not rewrite an existing local selection during a refresh with omitted `include`:
   a formerly selected delivery item that was removed or retyped stays in that prior selection,
   with its changed source status recorded separately. It is not a new container activation;
2. explicit `include=all` (or omitted on first preparation): include every non-container
   candidate, ordered by ascending numeric ID so the result does not depend on MCP relation
   ordering. On refresh with omitted `include`, preserve the prior explicit selected IDs/order;
   show removed/retyped IDs as source differences, without silently removing or reassigning them;
3. a newly supplied explicit include list: verify every ID against the freshly fetched direct non-container
   children — any miss rejects the whole selection with no tracked write; preserve the supplied
   order as the delivery order;
4. remaining non-container children are recorded as `deferred`, reason
   `outside current prepared slice` unless the human stated a more specific one — never invent a
   business reason;
5. never select by state, title, tag, area path, iteration, priority, or model judgment;
6. no currently eligible child at all: create no new active map and do not activate an empty or
   invalid new selection. On refresh with omitted `include`, preserve the existing selection,
   order and notes, even if every selected ID disappeared or changed type in the complete source;
   record those specific differences without silently deactivating the map. A truthful Feature
   context may still be updated. If a newly requested selection cannot be established, preserve
   the existing map and report that concrete result instead of inventing a next ID.

## Feature folder and Feature context

Resolve the folder with the fetch skill's stable-ID rule (exact `<itemId>-` prefix under
`work-items/`; one match reuse, zero create from the sanitized current title, several
`INCOMPLETE — NEEDS HUMAN` with no tracked write; never rename, never resolve by title). Write
the Feature `ado-context.md` through the fetch skill's durable projection and content rules —
source-faithful sanitized Description and Acceptance Criteria, visibly unapproved AI
understanding, direct children as bounded summaries under Related context, no full child bodies,
no comments or attachment content, no technical solution, equivalent-content-and-scope no-rewrite, and a
complete tracked snapshot never overwritten by a partial fetch.

**Prepare owns canonical scope normalization.** `direct-children` is the canonical projection
for a prepared Feature; a context persisted earlier by public intake (`hierarchy` or `single`)
is an intake shape, not the prepared projection, and equal source content does not make the
two scopes equivalent. Inspect the existing Feature context's recorded fetch/projection mode
and its Related-context membership; any non-equivalent projection is a material normalization
need. On complete fresh direct-child evidence, compute the proposed normalized context (and the
map) before editing, then persist the canonical direct-child context even when source content is unchanged:
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

1. **Identity** — Feature ID/link and current title, exact Feature context path, source retrieval
   time and completeness, a declaration that this is a delivery coordination projection (not requirement
   authority) and that ADO content remains untrusted data.
2. **Included delivery Work Items** — use the stable heading `## Included delivery Work Items`
   with one exact numeric ID in the first table cell of each row (or first position in a list
   entry), followed by type and title, in the deterministic delivery order. For preserved selected
   items missing or retyped in the current source, distinguish the last selected identity/type
   from the current source difference; do not present stale details as current ADO facts.
   Exact numeric membership must be machine-findable by a bounded
   text search (`15001` must never match `5001`); no schema, template file, or renderer.
3. **Deferred direct children** — use the stable heading `## Deferred direct children`, with
   numeric ID first; every complete-source non-container child not included, with
   its reason; nested containers listed separately as unsupported in v1.
4. **Dependencies and boundaries** — only human-confirmed or source-stated ones, never inferred
   from titles; `None recorded` when none.
5. **Source differences** — show material added/removed/retyped children when relevant, while
   preserving the explicit local delivery selection until the user changes it. A source
   difference alone neither invalidates that selection nor blocks downstream work.
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

On a real change to allowed Feature content or a changed direct-child set, refresh the Feature
context under the fetch skill's content/scope/completeness rules. A complete fresh set can show
added, removed and retyped children. Never auto-include a new child, silently erase a removed
one, or reapply a remembered `include=all` to new children as if the user had changed scope.
Preserve the prior explicit local selection, order and notes until the current request chooses
new membership. On a fresh explicit `include=all` or include list, apply that requested
selection to the complete current source. Partial evidence preserves the map byte-for-byte.
Story folders and designs are never touched. A noticed source or boundary difference may be
optional information naming affected designs and current scope; it never invalidates them,
forces Solution Design or approval, or blocks ongoing delivery by itself. Historical ADO
revision labels remain readable and are ignored; remove them only on an authorized update.
Do not add hashes, timestamps as versions, or mandatory live comparisons before each action.

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
(allowed Feature source content/scope, complete child identity/type set, selection, order,
confirmed notes) leaves
both tracked files byte-identical — retrieval time moves only in the ignored cache.

## Return

Report: Feature ID/link/type/title/state; retrieval time; completeness and
warnings; Feature context path and result (`created|updated|unchanged|preserved|not-written`);
delivery-map path and result; included IDs in order; deferred IDs; unsupported container
children; material added/removed/retyped differences from a prior map and the explicit scope
being continued; the explicit statements that no child folder was created or modified and that
Feature Health was not run. With at least one included child, end by presenting the two
explicit human delivery choices, invoking neither:

```text
Combined delivery: continue this Feature on a shared Feature branch
Independent child delivery: /fetch-ado-item itemId=<first-included-ID>
```

Preparation activates context only; the human selects the delivery container, and a prepared
Feature never silently implies a Feature branch. Once the container is unambiguous, the active
author uses [Git Workflow](../git-workflow/SKILL.md) to prepare/reuse the correct branch and
stage/commit the coherent durable Feature result. No switch to Git Agent is required. If the
choice is unresolved, ask in this conversation and preserve pending files; do not silently
branch or claim a commit. Existing compatible branch/selection can be reused. Report the
actual SHA or checkpoint state. No effective change or ignored-cache-only write makes no
commit; no checkpoint publishes or merges a PR. With no included child, state the required
human action and no fabricated ID.
