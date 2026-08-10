---
name: document-metadata-change
description: Generate reviewed technical documentation for one accepted metadata change.
argument-hint: "itemId=<ID> [manifestPath=<path>]"
agent: developer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract', 'knowledge/*']
---

Use the [generate-technical-documentation skill](../skills/generate-technical-documentation/SKILL.md).

Require a numeric work item ID. When the item has a design
(`work-items/<itemId>-<slug>/design.md` — today's approved-scope surface, replacing the
retired work-record `recordId`), confirm the documented change matches it; without one this
is standalone documentation of existing state, a valid lane named as such. Resolve the
workspace root (labeled `brain-core` in VS Code — a workspace label, not the repository
name) as the one repository/SFDX root; validate the manifest and show detected scope before
generation. Ask for missing manual deployment steps with `#tool:vscode/askQuestions` and
record an explicit `None` when the human confirms there are none.

Save the draft under `output/documentation/`, include rule/entry references, and link the
artifact from the work item's folder when one exists. Publication to ADO remains a human
action.
