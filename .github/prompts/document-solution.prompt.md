---
name: document-solution
description: Create or update three linked Markdown files for an implemented Salesforce solution.
argument-hint: "<solution topic and scope> [itemId=<ID>] [documentationPath=docs/solutions/<slug>/]"
agent: developer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*', 'salesforce/review_org_identity', 'salesforce/review_installed_packages', 'salesforce/review_object_contract', 'salesforce/review_soql_query', 'knowledge/*']
---

Follow the [document-solution skill](../skills/document-solution/SKILL.md) for the supplied
topic and scope. Save or update only `overview.md`, `flows.md`, and `components.md` in the
stable `docs/solutions/<slug>/` directory. Work Item and design context are optional.
Describe available implementation sources, keep material unknowns explicit, and return the
overview link with the local commit outcome. The skill owns discovery, content, and verification.
