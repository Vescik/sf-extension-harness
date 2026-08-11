# Legacy Knowledge migration — operator guide (TEMPORARY)

**What it is:** a one-time, manual importer (`migrate_legacy_knowledge.py`, repository root)
that plans and stages the migration of legacy one-file Knowledge into this repository's
governed store. It never runs in normal agent workflows, registers no MCP/hook/prompt, and is
**removed together with this guide before the final Knowledge-only commit**. Only
`scripts/knowledge_store.py` writes Knowledge; this tool orchestrates it and creates **drafts
only** — old approvals never bypass target review.

## Prerequisites

- clean target branch and worktree (`git status` empty);
- the repo virtual environment with dev dependencies installed (`.venv`);
- a readable legacy checkout, plus a backup of that checkout;
- no Salesforce/ADO access needed — the tool makes no org or ADO calls.

## 1. Plan (read-only)

```bash
python migrate_legacy_knowledge.py
```

Supply the legacy path at the prompt (quotes are fine). The tool detects the layout, shows a
count-only summary, asks before writing, and writes only an ignored report:

```text
output/knowledge-migration/<run-id>/report.md
output/knowledge-migration/<run-id>/manifest.json
```

Inspect both. Nothing under `.ai/knowledge/**` changes in plan mode. `Ctrl+C` is safe at any
prompt. Re-runnable form: `python migrate_legacy_knowledge.py plan --legacy-root <path>`.

## 2. Interpret the classes

| Class | Meaning | What stage does |
|---|---|---|
| `EXACT_REVIEW_CANDIDATE` | identity + source match the target exactly | creates a target draft |
| `REAPPROVAL_CANDIDATE` | intelligible, but source/profile/digest differs | creates a draft, flagged for review |
| `ORG_REFRESH_ONLY` | only legacy org usage is transferable | nothing — schedule a fresh org investigation |
| `ALREADY_PRESENT` | matching effective target entry exists | nothing |
| `CONFLICT` | target differs or identity is ambiguous | nothing — human decision |
| `QUARANTINE` | invalid/unsupported/missing source | nothing — manifest record only |

## 3. Pilot, then waves

Stage **five** selected IDs first (cover at least two metadata types and one previously
approved entry), inspect the created drafts, and only then continue in waves of at most 25
prose-bearing entries per review batch:

```bash
python migrate_legacy_knowledge.py stage --manifest output/knowledge-migration/<run-id>/manifest.json
```

Stage refuses a dirty worktree, a changed HEAD/`force-app`/collector, a changed legacy corpus,
an edited manifest, or a missing typed confirmation. It never branches, commits, or pushes —
you own git. On a per-entry failure it stops the wave and leaves created drafts intact; the
next run detects them and skips (no duplicates, no deletions).

## 4. Review and approve (human lane, unchanged)

```bash
python migrate_legacy_knowledge.py prepare-review --manifest output/knowledge-migration/<run-id>/manifest.json
```

This renders the normal `entry-review` surface and prints the digest-pinned `entry-approve`
command — **it never runs the approval**. Old approval history is provenance in the report
only; every entry needs the current human confirmation.

## 5. Verify after each approved wave

```bash
python scripts/knowledge_store.py entry-status
python scripts/knowledge_store.py entry-check
```

Rebuild/read the search index by the documented route (`python scripts/knowledge_search.py
build`, then a `search`/`context` read) and confirm a representative entry's citation is
target-generated. Only then stage the next wave.

## 6. Features and org usage — later, separately

Feature documents are listed in the manifest but never staged by the artifact pilot; rebuild
them against approved target artifact bindings and approve them through the Feature flow
afterwards. Never copy legacy org-usage numbers: run a fresh org investigation for entries the
report marks `ORG_REFRESH_ONLY`.

## 7. Stop / rollback

- `Ctrl+C` before staging is always safe (`CANCELLED`, nothing written).
- Do not delete created drafts by hand; revert the migration commit, or use the governed
  `entry-revoke` path with a human rationale.
- The legacy checkout is never modified by this tool.

## 8. Troubleshooting

| Symptom | Meaning / fix |
|---|---|
| re-prompt on path | blank/missing/unreadable path — paste the checkout root |
| refuses the path | target repo itself, inside it, or wrapping it — use a separate checkout |
| `UNSUPPORTED_LAYOUT` | not the known one-file layout — stop; amend the master plan first |
| "empty corpus" note | valid: recognized layout with no artifact entries |
| stage refuses: dirty worktree | commit/stash target changes, re-run `plan` |
| stage refuses: HEAD/source/collector changed | target moved since the plan — re-run `plan` |
| stage refuses: manifest digest mismatch | manifest edited/truncated — re-run `plan` |
| `CONFLICT` rows | resolve by human decision; the tool never overwrites |

## 9. Cleanup (required)

Archive `output/knowledge-migration/` outside the repository if you want a retained migration
record, then **delete `migrate_legacy_knowledge.py`, this guide, and the disposable tests
before committing migrated Knowledge**. The final commit contains only migrated Knowledge and
its target ledgers.
