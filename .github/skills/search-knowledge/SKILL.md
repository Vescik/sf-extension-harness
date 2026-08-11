---
name: search-knowledge
description: Read-only search over governed Knowledge - approved one-file Knowledge Entries for repository-source artifact facts and their unexpired org-usage blocks - reporting effective facts separately from non-effective records with their citations. Never proposes, promotes, or edits Knowledge.
user-invocable: false
---

# Search Knowledge

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md) and the
retrieval rules of the [one-file Entry contract](../../../docs/knowledge-one-file-contract.md).

One store, two kinds of fact — keep their authorities separate in the answer:

| Question | Surface | Authority |
|---|---|---|
| What does this component declare in source? What touches this field? Which Flow emits this message? | **Knowledge Entries** (`approved-current` and `approved-drifted`) | intended repository-source state only |
| How is this object/field used in the org right now? | **Entry `orgUsage` blocks** (unexpired) | governed facade probes, machine-attested |

## Inputs

At least one of: a subject identity (object/field/component API name), a keyword, a free-text
fragment, a dependency lookup, or a pasted user-facing error message. Optional narrowing:
metadata type, namespace, lifecycle state.

## Procedure

1. **Repository-source questions — query entries first.** Never grep entry Markdown by hand.

   **Primary surface — the `knowledge` MCP tools**: `knowledge_context`, `knowledge_search`,
   `knowledge_impact`, `knowledge_resolve` (bare name or file path → identity),
   `knowledge_entry_status` (the citable receipt), plus the deep-dive set
   (`knowledge_explain`, `knowledge_edge_health`, `knowledge_capabilities`) and the
   Feature reads (`knowledge_feature_search`, `knowledge_feature_context`,
   `knowledge_feature_status`). They
   expose exactly the commands below with the same JSON envelopes, so every reading rule in
   this skill applies verbatim to the tool results. The terminal menu below is the
   **operator fallback** for sessions where the MCP server is unavailable (its startup
   failure message names the fix); it is not an agent lane choice.

   <!-- knowledge-search-command-menu — R2 anchor. This skill owns the prose; a phase that adds
        a `knowledge_search.py` subcommand appends ONE line inside these markers and edits
        nothing else. The menu sat three commands stale (`tree`, `feature-drift`,
        `feature-dossier`) because the block each phase was told to append into never existed. -->

   - **everything about one artifact, in one call:**
     `python scripts/knowledge_search.py context --identity <MetadataType>:<ns|c>:<FullName>
     [--top N] [--include-heuristic] [--direction incoming|outgoing]` — purpose, `parts` (what it
     is made of), `permissions`, `incoming`/`outgoing` usage, `chains`, coverage and citations.
     This is the default first lookup; the narrower commands below are follow-ups. `NO_ENTRY`
     means no *entry* exists, not that the artifact does not; `AMBIGUOUS` lists the namespace
     twins and is never resolved by picking the top one. Reading the pack:
     - `parts`, `permissions` and `incoming` hold **effective approved rows only** — both
       `approved-current` and `approved-drifted` — and that is what makes them quotable as
       effective knowledge. Rows from non-effective lanes you opted into with `--state` are
       served in the sibling `partsNonCurrent` / `permissionsNonCurrent` /
       `incomingNonCurrent` keys and are reported separately, never merged back in.
       `--state` REPLACES the default filter rather than adding to it: pass
       `--state draft` alone and you lose every approved row.
     - `incoming`, `incomingNonCurrent` and `outgoing` are **objects keyed by relation kind**
       (`{"writes-field": [...], "operates-on": [...]}`), not flat arrays. Iterate the keys; a
       kind that is absent has no rows, which is not the same as "nothing writes this field".
     - `chains` answers "how does this work" without a second call: each row is
       `{node, hop, path[{from,kind,to,via,assurance}], minAssurance, lifecycle, hydrated}`.
       `--direction outgoing` walks execution order; the traversal needs `--include-heuristic`
       for the same reason `impact` does, and says so in `gaps` when it drops hops.
     - `chainsMeta.limitsHit` and `excludedCounts` say what was cut. A row with
       `hydrated: false` failed re-reading and must not be cited.
     - **Generic-bucket types have no governed dependency lookup at all** — Settings,
       Letterhead, Group, Network, Certificate, Document, Territory2 and similar label-only
       types carry no entry profile, so no lookup can return their dependents. A clean result
       over such a type means nothing was looked up, not that nothing depends on it. Whichever
       artifact a caller is producing — review finding, fix note, coverage matrix, documentation
       — every generic-bucket type in scope is named there as an unchecked class; the consuming
       skill states the exact obligation for its own output.
   - exact artifact: `python scripts/knowledge_search.py search --identity <MetadataType>:<ns|c>:<FullName>`
     (a bare API name that exists in several namespaces returns `AMBIGUOUS` — pass `--namespace`,
     never pick the top score yourself)
   - free text: `python scripts/knowledge_search.py search --text "<terms>" [--metadata-type <Type>] [--top N]`
   - typed facets: `--facet field.required=true`, `--facet flow.trigger.object=<Object>`,
     `--facet family=objects` (storage family — a navigation grouping, never evidence), …
     (`python scripts/knowledge_search.py capabilities --metadata-type <Type>` lists the valid
     facet names, value types, and operators — do not guess field paths)
   - dependencies: `--relation-anchor <Object.Field|Identity> [--relation-kind writes-field]
     [--direction incoming|outgoing]`; heuristic edges stay out unless `--include-heuristic`
   - one artifact in full: `python scripts/knowledge_search.py explain --identity <Identity>
     [--top N]` (facets, outgoing/incoming usage, coverage, limitations). `--top` defaults to 50
     and `incoming` stays a flat array here; when the cap truncates, the result says so in `gaps`
     — report the list as partial rather than as the population.
   - **"what breaks if I change this?"** —
     `impact --identity <Identity> --direction incoming [--depth 1-2]`. The result names its
     `anchorIdentity` and `anchorLifecycle` and always carries an ANCHOR gap stating what the
     anchor was verified against; rows carry `hydrated`, and an unhydrated row is not citable.
   - **"how does this work?"** —
     `impact --identity <Identity> --direction outgoing --depth 2 --include-heuristic`.
     The flag is required, not optional: an execution chain runs along `invokes-class`, which is
     regex-derived, so the default source-exact filter returns no chain at all. Every hop carries
     its own `assurance` and the path carries `minAssurance` — report the chain as inferred, never
     as declared.
   - **Feature reads** — discovery and architecture, never citable:
     `python scripts/knowledge_store.py feature-search [--text ...]` (call with no filters to
     list every approved feature and its slug), `feature-context --slug <slug>` (the approved
     architecture in one read, with per-binding health), `feature-status [--slug <slug>]`
     (lanes). Citations come only from `feature-verify-citations`
     ([author-feature](../author-feature/SKILL.md) documents the authoring loop).
   - `python scripts/knowledge_search.py capabilities` lists the relation kinds, which of them are
     heuristic, the two directions and the per-command depth limits — do not guess them.
   - pasted error message: `search --mode intentional-flow-error --text "<exact message>"` —
     matches only author-declared Flow Custom Errors. `No intentional Flow error matched.` is a
     real answer; it never licenses guessing a fault path or a platform exception.
   - if a command reports `INDEX STALE / REBUILD REQUIRED`, run
     `python scripts/knowledge_search.py build` and retry. Never answer from the previous result,
     from the generated cache, or from model memory.

   <!-- /knowledge-search-command-menu -->

2. **Org usage questions — read the entry's `orgUsage` block.** `entry-status --identity
   <Identity>` reports the org lane; only an unexpired (`org-fresh`) block grounds usage
   numbers, always cited with its orgKey and observedAt. An expired or superseded block is
   absent for grounding: re-attach through the investigate-object org-sampling step or run a
   fresh governed probe. Org state beyond usage numbers needs a fresh facade receipt in the
   same turn — never a remembered value.
3. For vocabulary questions ("what process terms exist?"), read
   `.ai/knowledge/keyword-taxonomy.md` (approved terms) — candidate terms on entries are
   suggestions awaiting human curation, never evidence.
4. Report effective facts with their citations: entries by identity + entry path + digests +
   lifecycle lane; org usage by orgKey + observedAt. Non-effective matches (draft, revoked,
   not-effective, org-expired) go in their own section with the reason. An empty
   result is "no governed Knowledge", never license to answer from memory.

   **Two effective lanes.** `approved-current` and `approved-drifted` are both approved, both
   served by default on all four retrieval surfaces, both citable, and both count toward
   coverage and can support `SAFE`.

   **`approved-drifted` is effective, with disclosure.** Approval binds the reviewed facts
   (`reviewedContentDigest`), not the later immutability of the source bytes — so when a source
   fragment changes, the entry stays approved and `entry-verify-citations` grades it `ok` with a
   `SOURCE_DRIFT` advisory. Report the fact, name the changed path. Do **not** report it as
   unusable, do **not** treat re-approval as required repair, and do **not** demand an index
   rebuild before citing it. A maintainer may choose to refresh it; that is an option surfaced
   once per release cycle by `entry-coverage --review-cycle-days`, never a per-entry blocker.

   **A missing or unreadable source fragment is not drift.** The evidence behind the approval
   cannot be produced at all, so the entry is `not-effective` with
   `SOURCE_FRAGMENT_MISSING` / `SOURCE_FRAGMENT_UNREADABLE`: not citable, and it needs a
   decision rather than a disclosure.

   **Age is not a lane.** An entry is never less effective for being old, and nothing about its
   age changes what you may cite.

   **Org usage is a separate axis.** An expired `orgUsage` block means the org NUMBERS are
   unusable and need a fresh probe; it says nothing about the repository-source Entry, which
   stays effective. Never merge the two into one verdict.

   Cite what the executor gives you, not what the view shows: obtain the citable ref with
   `python scripts/knowledge_store.py entry-status --identity <Identity>`. A search hit, a
   `context` pack and a rendered dossier are never themselves citable — the `citation` block they
   carry is a content digest (`profileDigest`), and an `entryRef` hand-built from it is rejected.
   Row `lifecycle` labels are index-fresh; the store-fresh `entry-status` receipt is the
   citation gate.

## Boundaries

Read-only: never propose, approve, edit entries/features, or grow the keyword
taxonomy from this skill. `build` only refreshes the ignored generated cache — that cache is
never Knowledge authority and is never cited.

Entries ground only positive, source-exact, fully-covered repository facts. Absence
("nothing else writes this field"), runtime behavior, business meaning, package limitations,
and vendor guarantees have no governed Knowledge surface — report the gap and what a human
would have to verify, instead of inferring from a missing search hit.

An entry can be readable, approved and current and still refuse to ground a fact: contract §8.1
grounds only sections marked `source-exact` with `extractionCoverage: full`, and the executor
enforces that when an `entryRef` is bound. **Apex-layer entries generally cannot be cited as
positive grounding** — their facts are regex-derived, so they are honestly marked heuristic.
Measured on the 189-component reference package, 58 entries are not groundable: 48 of 52
ApexClass, 5 of 5 ApexTrigger, 3 of 93 CustomField and 2 of 2 ValidationRule. Read them for
orientation and report them as inferred; when the fact has to be grounded and no groundable
entry exists, say so plainly and name what would make it groundable. A refusal here is the
contract working, not a tooling failure — do not retry it with a different ref shape.

Missing knowledge is a finding: route creation to
[selected-files-knowledge](../selected-files-knowledge/SKILL.md) (`/pin-knowledge`),
`/curate-knowledge build`, or [investigate-object](../investigate-object/SKILL.md).

## Return

Return the filters used, entry hits (identity, lane, match reason, coverage/limitations,
citation digests), unexpired org-usage findings (orgKey, observedAt), non-effective matches
with reasons, dependency hits with relation kind and assurance, index generation when entry
search was used, and suggested next steps for gaps.
