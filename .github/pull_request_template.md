<!--
Compact, adaptive PR description. Fill the universal core; keep a conditional section
only when the diff makes it relevant and DELETE the rest — do not fill sections with
repeated "N/A".

Work item modes (exactly one):
- Delivery PR: replace <id>, <slug>, <title> with real values. The plain AB#<id> line
  (no backticks, no code block) creates the native Azure Boards link — use only the one
  Work Item this PR delivers; a Work Item may span several sequential PRs, each repeating
  the same AB#<id>. No transition keywords (Fixes/Resolves/Closes) — PRs never change
  Work Item state.
- Maintenance PR without an ADO Work Item: replace the section content with
  "Not applicable — maintenance without an ADO Work Item". Never invent an ID and never
  leave the placeholder unchanged.

Always: record deviations in the work item's decisions.md before the PR claims done;
never include credentials, customer data, caches, or local config in the diff.
-->

## Summary

<One to three sentences: what this PR changes and why.>

## Work item

Azure Boards: AB#<id>
Local context: `work-items/<id>-<slug>/`
Title: <title>

## Changes

- <specific change>

## Validation

- <what was run or performed, and result — only checks actually run>

## Review focus

- <the important behavior, risk, or decision for reviewer attention>

<!-- Conditional sections — keep only what the diff makes relevant, delete the rest. -->

## Salesforce impact

- Metadata / Apex / Flow impact: <...>
- Deployment, permissions, or rollback consideration: <...>

## Package namespace impact

- [ ] No changes touching `VendorNS__`
- [ ] Impact and evidence recorded in `design.md`

## QA handoff

- QA plan: `work-items/<id>-<slug>/qa-test-plan.md`
- Readiness: READY FOR QA / DRAFT / GAPS

## Harness changes

- Changed surfaces: <agents / prompts / skills / instructions / hooks / configuration>
- Harness validation: <commands and results>
