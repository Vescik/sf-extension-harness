# Knowledge Index

Governed Knowledge lives in the one-file entry store
([`docs/knowledge-one-file-contract.md`](../../docs/knowledge-one-file-contract.md)); the v1
claim registry retired on 2026-08-03 (see `.ai/memory/decisions-log.md`).

| Surface | Authority |
|---|---|
| `artifacts/<family>/<MetadataType>/<ns|c>/<FullName>.md` | One-file Knowledge Entries — executor-derived repository facts plus human-attested prose, grouped by storage family (`objects` — laid out per object with `object.md` + member subdirs, `ui`, `access`, `automation`, `code`, `integration`, `configuration`, `reporting`, `shared`; contract §2). Written only by `scripts/knowledge_store.py`; never hand-edited. |
| `artifacts-ledger.jsonl` | Append-only approval ledger; approval binds to `reviewedContentDigest`, latest-wins. |
| `artifacts-org-ledger.jsonl` | Append-only org-usage ledger (`entry-org-attach`/`detach`); entries carry expiring `orgUsage` blocks. |
| `features/<slug>/feature.md` + `features-ledger.jsonl` | Feature Knowledge — curated, human-approved architecture documents (typed topology + claims + digest-pinned artifact bindings); citable claim-by-claim via `featureRef`, never as `entryRef`. |
| [keyword-taxonomy.md](keyword-taxonomy.md) | Separately curated vocabulary; terms are not factual evidence. |

These directories and ledgers materialize on first executor write; their absence on a fresh
clone is normal.

## Retrieval rule

Treat an entry as established when the executor computes an `approved` lane
(`entry-status`/`entry-check` — never a raw file read), and cite only source-exact,
fully-covered sections (contract §8.1). Both approved lanes — `approved-current` and
`approved-drifted` — are effective, served by default and citable (contract §4). An
`approved` entry is usable regardless of drift, of its own age, or of org-usage age; all
three travel with the entry as a visible caveat, never as a block: surface
`approved-drifted` with the changed paths, and cite org usage with orgKey, observedAt
and its age ("sampled N days ago"). Age never expires an approval, and an expired
`orgUsage` block invalidates the org NUMBERS only, not the entry. `draft`, `revoked` and
`not-effective` — including an entry whose approved source fragment is missing or
unreadable — are unusable for grounding. A re-read gap caused by the described file having changed since the index was
built is not evidence of falsehood, but it is not safe to serve with a caveat either —
rebuild the index (`knowledge_search.py build`) and retry before answering; this is a
cheap, mechanical fix, not a return to full discovery. A re-read gap caused by a missing
file, an unparseable entry, or an identity/digest mismatch is an integrity finding, not a
staleness signal — report it as an open gap, do not wave it through and do not silently
retry. Existing Knowledge and generated views never corroborate themselves.

## Maintenance rule

`entry-coverage --review-cycle-days <n>` is the read-only release-cycle summary; adding
`--analyze-facts drifted|all-approved` also re-derives each approved entry's structural facts
from current source and compares them at the `factsDigest` boundary (contract §5.5a). Both are
diagnostics: they write nothing, and neither a `FACTS_CHANGED` result nor an old `reviewedAt`
withdraws an approval, moves a lane or blocks a citation. Read `FACTS_EQUIVALENT` narrowly — it
says the extracted facts did not move, not that the artifact, its Purpose or its org usage are
unchanged. Run `all-approved` after a release that touched the collector, an adapter or the
assurance vocabulary: that divergence moves no source byte and matching collector versions do
not rule it out.

This repository intentionally contains no organization or package facts until real, sanitized
evidence is reviewed. Never seed examples into the live store.
