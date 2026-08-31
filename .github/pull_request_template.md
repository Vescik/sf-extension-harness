<!--
Compact, adaptive PR description. Fill the universal core; keep a conditional section
only when the diff makes it relevant and DELETE the rest — do not fill sections with
repeated "N/A".

Delivery modes (keep exactly one of the two link sections below, delete the other):
- Work Item PR (standalone work-item/<id> branch to main, or child work-item/<id> branch
  to its Feature branch): replace <id>, <slug>, <title> with real values. The plain
  AB#<id> line (no backticks, no code block) creates the native Azure Boards link — use
  only the one Work Item this PR delivers; a Work Item may span several sequential PRs,
  each repeating the same AB#<id>.
- Final Feature PR (feature/<feature-id> branch to main): link the Feature and the
  included child Work Items. The child IDs come mechanically from the current `included`
  set in the Feature's delivery-map.md — never from titles, commit prose, or chat, and a
  deferred child is never represented as delivered. Multiple AB# references are an
  explicit exception here because this one PR delivers multiple Work Items. Intended
  merge is a merge commit preserving the [WI-<id>] commits.
- Maintenance PR without an ADO Work Item: replace the section content with
  "Not applicable — maintenance without an ADO Work Item". Never invent an ID and never
  leave the placeholder unchanged.

No transition keywords (Fixes/Resolves/Closes) anywhere — PRs never change Work Item state.

Always: record deviations in the work item's decisions.md before the PR claims done;
never include credentials, customer data, caches, or local config in the diff.
-->

## Summary

<One to three sentences: what this PR changes and why.>

## Work item

Azure Boards: AB#<id>
Local context: `work-items/<id>-<slug>/`
Title: <title>

## Feature delivery

<!-- Final Feature PR only — delete for a Work Item or maintenance PR. -->

Azure Boards Feature: AB#<feature-id>
Included Work Items: AB#<id>, AB#<id>
Feature context: `work-items/<feature-id>-<slug>/` (`ado-context.md`, `delivery-map.md`)
Included local contexts: `work-items/<id>-<slug>/`, `work-items/<id>-<slug>/`

- Combined changes and integration behavior: <what the included Work Items deliver together>
- Story-level validation: <per included Work Item — only checks actually run>
- Combined validation: <integration/regression checks actually run on the Feature branch>
- Rollback: <how the combined delivery is rolled back>

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
- Org change log: <path or `None — no qualifying org mutation executed`>

## Package namespace impact

- [ ] Namespace/package ownership and impact are recorded in `design.md`
- [ ] Required evidence, verification, and rollback are recorded

## QA handoff

- QA plan: `work-items/<id>-<slug>/qa-test-plan.md`
- Readiness: READY FOR QA / DRAFT / GAPS

## Harness changes

- Changed surfaces: <agents / prompts / skills / instructions / hooks / configuration>
- Harness validation: <commands and results>
