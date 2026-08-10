---
name: curate-knowledge
description: Procedure for knowledge-curator — health sweep, entry coverage, drafting, description, drift maintenance, and Feature lifecycle, all through the governed executor commands.
user-invocable: false
---

# Curate Knowledge

The single copy of the curation procedure: the `knowledge-curator` agent and the
`/curate-knowledge` prompt both point here and repeat nothing. Scale the lookup to the
question — the Health sweep is a mode, not a session opener; a targeted session
(describe one entry, approve one chunk, check one identity) needs only `entry-status`
for the identities in scope. For read lookups (context, search, impact, explain,
feature surfaces) use the `knowledge_*` tools and read their envelopes by the
[search-knowledge](../search-knowledge/SKILL.md) rules; the maintenance commands below
stay terminal because they are store-side surfaces, not retrieval.

## Health
`python scripts/force_app_knowledge.py inventory`, then
`python scripts/force_app_knowledge.py entry-readiness` and
`python scripts/knowledge_store.py entry-coverage`, plus the `knowledge_edge_health`
tool. Report the counts and worklists, drifted entries, and a prioritized maintenance
recommendation. Read-only — change nothing.

## Entries (coverage check)
`entry-coverage` — per-type lanes, entries missing for profiled source components, and
which types have no entry profile yet. A type with no profile has no Knowledge lane:
report it as a profile gap (`entry-coverage`'s own output names it), never improvise a
side channel. Read-only.

## Build <MetadataType>
`entry-coverage` names the gaps, then
`entry-draft --metadata-type <Type> --full-name <Name>` per artifact — the executor
derives every fact from source; you supply nothing. Drafts land holding
`<AGENT_DESCRIPTION>` — facts extracted, analysis pending. Report the count; do not
describe in the same pass unless asked.

## Describe (the only copy of the authoring guidance)
`entry-readiness` lists `describeNext` (drafted, sentinel still held — distinct from
`documentNext`, components with no entry at all). Per entry:
`entry-context --identity <Identity>` — the artifact's source, its facts, and the
entries that reference it. Write the description from THAT, not from a `description`
element: most components have none, and the half that says what a component is *for*
usually lives in its callers. Then write 1–8 sentences covering four dimensions:

1. **what it is** — the component's behavior, from the source;
2. **why it exists** — the business purpose someone weighs when asking "is this the
   right place to change";
3. **what a consumer should know before relying on it** — the sharp edges, alongside
   the recorded `limitations`;
4. **searchability** — use the terms a person would actually type; Purpose carries 2×
   weight in `knowledge_search`, so a description that never names its subject hides
   the entry.

Worked example (illustrative — replace with a real approved entry's Purpose when one
exists in this repository):

> Routes newly created `VendorNS__Case__c` records to a queue chosen from the active
> routing rules in `VendorNS__RoutingRule__mdt`. Exists so subscriber admins change
> routing by editing CMDT records instead of the packaged flow. Consumers should know
> it fires on create only — an edit that should re-route must be saved through the
> "Re-evaluate routing" quick action. Handles case routing, queue assignment, and the
> "no matching rule" fallback queue.

State only what the source supports; a gap is a gap, not a guess. Store with
`entry-describe --identity <Identity> --purpose <sentences>` (or `--purpose-file` for
longer prep; `--limitation` REPLACES the whole set — re-state every limitation, not
just the new one). Report entries still holding the sentinel as outstanding work, not
failures. Hand the described set to `/approve-drafts-knowledge`.

## Drafts (review surface)
`entry-review` renders outstanding drafts (past the cap it returns
`REVIEW_READY_CHUNKED` rounds); hand each digest-pinned command to
`/approve-drafts-knowledge`. Never approve from this skill.

## Drift (decay maintenance)
`entry-coverage` plus `entry-status`; entries whose source moved sit in
`approved-drifted`. Re-draft and re-describe, route through
`/approve-drafts-knowledge` — no refresh wave, only per-entry re-approval of what
actually changed.

## Feature lifecycle (surrounding commands; authoring itself is /author-feature)
`feature-status` (lanes), `feature-context` (approved architecture, never a citation
receipt), `feature-search` (discovery, never citable), `feature-verify-citations`
(the only citable featureRef producer), `feature-revoke`. Approval goes through
[approve-knowledge-drafts](../approve-knowledge-drafts/SKILL.md): `feature-review`
renders the package and the human confirms
`feature-approve --feature Feature:<slug>:sha256:<digest>` in chat. What approval
binds is the reviewed MODEL and narrative — graph traversal only ever proposes
candidates; a component joins a Feature exclusively through a recorded draft
operation. `feature-check` is a CI gate, not a session step.

## Approval gate (applies to every mode above)
Every approval stops for the human's digest-pinned confirmation (SAFE-HUMAN-001).
Reviewer identity is `knowledge.chatReviewer` in `config/harness.local.json` — a JSON
config file, never probed via `git config`. Missing → report the exact key and file,
stop.

## Stop rules
Dirty tree, partial inventory, executor refusal, or a description ungroundable in
source — pause and report, never improvise.
