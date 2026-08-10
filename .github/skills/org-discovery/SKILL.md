---
name: org-discovery
description: The recipe for investigating the org through the read-only Salesforce MCP facade and knowledge search — what to call, in what order, and what to do when a tool fails.
user-invocable: false
---

# Org Discovery

Org facts come from tools, not memory. This is the standing recipe; scale it to the
question — a one-field question does not need the full sweep.

## The sequence

1. **`review_org_identity` — once per session.** Confirms which org you are reading and
   that it is non-production. Everything after is scoped to this identity.
2. **`review_installed_packages` — once per session.** Establishes the installed VendorPkg
   version. Package-specific facts are version-scoped: note the version in whatever you
   write.
3. **`review_object_contract` — per object you touch.** The contract gives fields,
   relationships, and ownership: the namespace prefix is the ownership signal
   (`VendorNS__` = package-owned; no prefix or your own = subscriber; standard =
   platform).
4. **`knowledge_context` — per subject.** What the team already knows about the artifact,
   including recorded `limitations` — read them before relying on the artifact, they are
   the accumulated burn marks.
5. **`review_soql_query` — when the design depends on data shape.** Structure, fill
   rates, real record shapes: prefer a bounded read over a guess or a blocking question.
   Never paste raw record rows into a design, a knowledge entry, or an ADO artifact —
   derive the counts and shapes you need.

## Knowledge freshness flags

Freshness on a knowledge entry has three different fates, not one. **Drift and expired
org-usage** are not grounds to reject the entry or to redo discovery — they go into the
design/review as an explicit caveat, exactly like `limitations`. **A failed re-read
caused by the file changing since the index was built** — rebuild the index and retry
(`knowledge_search.py build`); a cheap mechanical step, not a caveat and not discovery
from zero. **A failed re-read for any other reason** (file missing, entry does not
parse, identity/digest mismatch) remains a real gap: report it, do not build on that
entry.

## When a tool fails

A failed or unavailable tool is a stated limitation, never permission to imagine the
result (SAFE-TOOL-001). Write the explicit assumption into the design ("assumed X because
review_object_contract was unavailable; verify before implementation") and continue.

## Map versus terrain

`docs/` describes the package as the team last verified it; the org is the live truth.
On conflict the org wins — and the mismatch is worth money: report it as a proposed
correction to `docs/` (MP-MAP-001).
