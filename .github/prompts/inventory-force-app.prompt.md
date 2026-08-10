---
name: inventory-force-app
description: Inventory the root force-app as sanitized Knowledge evidence candidates without drafting entries.
argument-hint: "(no arguments — repository inventory)"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal']
---

Use the [inventory-force-app skill](../skills/inventory-force-app/SKILL.md).

The run is a repository inventory — a standalone read, no work record exists or is
required. Inventory the single root `force-app`, report coverage, generic files,
diagnostics, commit/tree digest, and whether source cleanliness permits governed entry drafting.
Do not draft or approve entries.
