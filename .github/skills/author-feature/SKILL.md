---
name: author-feature
description: Interactive Feature Knowledge authoring - staged conversation building curated topology, claims with honest authority classes, and digest-pinned artifact bindings; executor-owned IDs, validation and approval.
user-invocable: false
---

# Author a Feature

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and
contract §13 of the [one-file Knowledge contract](../../../docs/knowledge-one-file-contract.md).
Requires the `knowledge-curator` role.

One canonical document per Feature: typed frontmatter model (nodes, relations, claims,
entry points, questions, bindings — executor-allocated `FN/FR/FC/FQ/FB` ids) plus a human
narrative. You write NOTHING by hand: every change is one batch of typed operations in an
ignored proposal file, applied by the executor.

## The loop

1. **Open or resume** — `python scripts/knowledge_store.py feature-open --slug <slug>
   [--name "<Name>"]`; note the returned `draftVersion` (optimistic concurrency: every
   `feature-record` names it, a stale version reloads instead of overwriting).
2. **Work in reviewable slices** (purpose and boundary → domain model → processing and
   calculation → UI → access → integration/configuration/reporting only when relevant →
   invariants and limitations → evidence review). Convert each user statement into typed
   operations, show the delta, then apply:

   ```text
   python scripts/knowledge_store.py feature-record --slug <slug> \
     --expected-version <N> --operations-file .cache/knowledge-proposals/<slug>-ops.json
   ```

   The file is `{"operations": [{"kind", "op", "data"}...]}` (≤40 per batch); the exact
   `data` shapes per kind are pinned in `schemas/knowledge-feature.schema.json` — read it
   before composing the first batch instead of learning the shapes from rejections, and
   `--validate-only` dry-runs the batch through the same apply path without writing. Kinds:
   `node` (set/remove), `relation` (set/remove), `claim` (set/withdraw), `binding`
   (bind/unbind — you give an entry identity, the EXECUTOR reads the live entry and pins
   the digests; an approved entry is required — `approved-drifted` binds too, drift is a
   visible caveat and the citation verdict downgrades on its own; draft and revoked never
   bind, and a pasted receipt is never accepted),
   `section` (replace one narrative section), `meta` (set name/entryPoints/limitations/
   keywords/sensitivity, add-question, resolve-question). Keywords come from the approved
   taxonomy, exactly like artifact entries.
3. **Existing Knowledge first** — for every name the user mentions: `knowledge_resolve` →
   `knowledge_context` on exact candidates. No `knowledge_entry_status` before binding: the
   executor reads the live entry and pins the digests itself, and a pre-fetched receipt is
   never accepted — its refusal IS the check.
   `NO_ENTRY` is a gap to record, never absence. Order candidates source-exact containment
   first; heuristic candidates go in a separate optional queue; never auto-expand shared
   hubs (User, Account) without the user asking.
4. **Honest authority** — business meaning, boundary, roles, entry points, invariants and
   limitations may be `human-attested`. Data relationships, calculation lineage,
   processing order, access boundaries and integration contracts need `source-exact`
   bindings (or governed org observation). Heuristic material is NEVER citable; the
   executor rejects any batch that pretends otherwise.
5. **Check and review** — `feature-status` for the lane and outstanding problems;
   `feature-review --slug <slug>` renders the exact package (topology, claims with
   authority, binding currency, full narrative) plus the digest-pinned approve command.
6. **Approval is human** — the reviewer confirms
   `feature-approve --feature Feature:<slug>:sha256:<digest>` in chat (SAFE-HUMAN-001
   asks). You never self-approve. Any later material edit returns the document to draft.

## Body sections

Core three are mandatory and gate approval: `Purpose and boundary`, `Domain and data
model`, `Evidence map`. The rest render only when the Feature has real content for them —
an explicit reviewed "Not applicable" is content; silence is not completeness.

Write a paragraph, not a page: when a section grows past ~10–15 sentences, that is the
signal that part of it should be a separate claim (`FC-`) with its own `assurance`, not
sprawling prose — the structure for that detail already exists, use it. And write to be
found: `feature-search` scans the full body prose as its haystack, so the terms a person
would actually search for (the business phrase, the object name, the error message
wording) belong in these sections — a section that never names its subject makes the
whole Feature invisible to a text query.

## Consumers

`feature-search` and `feature-context` serve discovery and architecture reads (never
citable); `feature-verify-citations` is the only producer of a citable, claim-scoped
`featureRef` and checks the transitive artifact bindings on every call.
