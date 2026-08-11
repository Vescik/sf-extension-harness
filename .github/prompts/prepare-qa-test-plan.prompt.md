---
name: prepare-qa-test-plan
description: Author or refresh the human-executable QA handoff for one work item — work-items/<id>-<slug>/qa-test-plan.md, written interactively by the Test Strategist.
argument-hint: "itemId=<ID> [optional focus or output language]"
agent: test-strategist
---

Use the [prepare-qa-test-plan skill](../skills/prepare-qa-test-plan/SKILL.md) — it owns the
complete authoring procedure. This prompt only routes and bounds the invocation.

Parse the invocation text: `itemId` is required and must be a positive integer. Free text after
it may state a bounded focus or the output language; reject any other `name=value` option.
If `itemId` is missing, ask once with `#tool:vscode/askQuestions`; never guess an ID.

Resolve exactly one `work-items/<id>-*/` folder. Zero matches: stop and return the recovery
(`/fetch-ado-item itemId=<ID>` then `/solution-design itemId=<ID>` for ADO-backed work, or
`/solution-design` with the written requirement). Multiple matches: stop with
`INCOMPLETE — NEEDS HUMAN` and write nothing.

The one tracked write this command may perform is creating or refreshing
`work-items/<id>-<slug>/qa-test-plan.md`. Never edit `ado-context.md`, `design.md`, `tasks.md`,
or `decisions.md`; never write execution results (PASS/FAIL, testers, dates, screenshots, Test
Run IDs) anywhere; never mutate ADO, Salesforce, or Knowledge.

Return the skill's report: path and created/updated/unchanged; one verdict (`READY FOR QA`,
`DRAFT — IMPLEMENTATION NOT COMPLETE`, `GAPS — ACTION REQUIRED`, or
`INCOMPLETE — NEEDS HUMAN`); the evidence route (custom / managed-package / mixed); AC
coverage; Test Cases by origin; unresolved questions; any reusable-Knowledge recommendation;
and the exact next action.
