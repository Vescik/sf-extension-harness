---
name: pin-knowledge
description: Turn a small pinned or named selection of force-app files into governed Knowledge — mechanical resolution, a human-approved plan, then per-lane draft/describe/propose with one approval pass.
argument-hint: "[files=<path|name,...>]"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce/review_object_contract', 'salesforce/review_soql_query', 'knowledge/*']
---

Use the [selected-files-knowledge skill](../skills/selected-files-knowledge/SKILL.md).

Build the selection from the first non-empty source and never merge sources silently: the
`files=` argument (comma-separated paths or names), else the files pinned/attached to this chat
request, else the file or component names written in the request text. When all three are empty,
ask with `#tool:vscode/askQuestions` — never guess a selection.

Resolve the selection mechanically with `python scripts/force_app_knowledge.py resolve` — never
map a path to a component by eye — and present the resolution plus the per-component plan for
the human's explicit go-ahead before drafting anything. Mixed metadata types are expected and
legal here; a selection beyond 25 components is refused — narrow the selection or split it
type instead, or re-pin at most 25. Documenting existing state needs no work item; when the pinning was raised by delivery
work, link the resulting entries from the relevant `work-items/<id>-<slug>/` folder.
