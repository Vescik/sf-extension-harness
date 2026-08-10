---
name: fetch-ado-item
description: Fetch a validated Azure DevOps work item context and begin Solution Design.
argument-hint: "itemId=<ID> [mode=single|hierarchy] [childDetail=summary|full] [includeTestCases=true|false]"
agent: designer
---

Use the [fetch-ado-item skill](../skills/fetch-ado-item/SKILL.md).

Parse the invocation text as `name=value` arguments. `itemId` is required and numeric. Reject an
unknown option or invalid enum before using a tool. If `itemId` is missing, ask once with
`#tool:vscode/askQuestions`; never guess.

Fetch the context, disclose cache freshness/completeness, then continue the Solution Designer
procedure. Fetching context is a read; return the normalized context directly. Delivery work
that follows lands in `work-items/<itemId>-<slug>/` (design.md first) — there is no work
record to create or validate.
Do not merely print raw ADO content and stop; ADO intent is not implementation evidence.
