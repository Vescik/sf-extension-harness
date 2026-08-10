---
name: investigate-object
description: Collect bounded, sanitized, reconciled evidence for one Salesforce object or component and report it read-only; persist org numbers only via entry-org-attach.
argument-hint: "objectApiName=<API name>"
agent: config-investigator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'salesforce-readonly/review_org_identity', 'salesforce-readonly/review_installed_packages', 'salesforce-readonly/review_object_contract', 'salesforce-readonly/review_configured_orgs', 'salesforce-readonly/review_soql_query', 'knowledge/*']
---

Use the [investigate-object skill](../skills/investigate-object/SKILL.md).

Require exactly one `objectApiName` (ask once with `#tool:vscode/askQuestions` if missing). The
name must be on the configured review allowlist; evidence stays bounded, sanitized, and
grounded through the guarded review tools (record reads via `review_soql_query`); the facade proves the non-production org identity live at startup, and object facts reconcile the describe and Tooling endpoints with contested traits nulled and listed in `contestedProperties`.

The outcome is a sanitized investigation report under `output/` — never a verified fact and
never citable Knowledge by itself. Numbers worth keeping persist through the skill's governed
`entry-org-attach` step when the subject has an approved entry. Report the report path,
reconciliation status, limitations, and any drift or contested findings. The investigation is a standalone read; when it was raised by delivery work, link the
report from the relevant `work-items/<id>-<slug>/` folder.
