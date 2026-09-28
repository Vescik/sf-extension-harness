---
name: document-metadata-change
description: Generate or update a sourced technical-documentation draft for one work item.
argument-hint: "itemId=<ID> [manifestPath=<path>]"
agent: developer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce/review_org_identity', 'salesforce/review_installed_packages', 'salesforce/review_object_contract', 'knowledge/*']
---

Use the [generate-technical-documentation skill](../skills/generate-technical-documentation/SKILL.md).

Require a positive integer work item ID. Resolve its stable folder by ID using the skill:
reuse one match; stop without writes on duplicates; with no match, establish identity from
the already-required current ADO fetch and create only the documentation file. When the item
has a design (`work-items/<itemId>-<slug>/design.md` — the approved-scope surface), confirm the
documented change matches it; without one this
is standalone documentation of existing state, a valid lane named as such. Resolve the
workspace root (labeled `brain-core` in VS Code — a workspace label, not the repository
name) as the one repository/SFDX root; validate the manifest and show detected scope before
generation. Ask for missing manual deployment steps with `#tool:vscode/askQuestions` and
record an explicit `None` when the human confirms there are none.

Save the draft as `work-items/<itemId>-<slug>/technical-documentation.md`, in English/STE
with source quotations preserved. Validate the resolved path, retain human notes on updates,
and keep document review status separate from implementation and test results. Include the
fetched ADO link, relative repository links, rule/entry references, verification, and gaps.
Return the actual path. Publication to ADO remains a separate human action.
