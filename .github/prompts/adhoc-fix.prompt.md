---
name: adhoc-fix
description: Bounded defect fix express lane — edit, optionally deploy after confirmation, verify, and write a fix note.
argument-hint: "component=<Type:Name> [org=<alias>] plus the diagnosis or a pointer to it"
agent: developer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_soql_query']
---

Use the [adhoc-fix skill](../skills/adhoc-fix/SKILL.md).

Require a named target component and a written diagnosis (ask once with
`#tool:vscode/askQuestions` if either is missing). This lane replaces the accepted-design entry
gate only for a small bounded defect fix; retrieve the current org state first, make the smallest
coherent edit in `force-app/`, and write the fix note under
`output/documentation/adhoc-fixes/`.

Report the fix note path, the before → after of the defective element, local verification, and the
proposed deployment scope. If a real deploy is needed, ask with the target, scope, and explicit
org-change warning, then run only the exact confirmed command and verify the result. If the fix
stops being small and bounded, route through the normal design lane.
