---
name: feature-health
description: Run the Feature/BRD-to-Story coverage gate before Solution Design.
argument-hint: "itemId=<Feature ID>"
agent: test-strategist
---

Use the [check-feature-coverage skill](../skills/check-feature-coverage/SKILL.md).

Require one numeric `itemId`. Verify the item is a Feature and the ADO result is fresh and
complete. If the ID is missing, ask once with `#tool:vscode/askQuestions`.

Save the report under `output/feature-health/`, return its `PASS`, `WARN`, `BLOCKED`, or
`INCOMPLETE` status, and surface every gap, orphan, ambiguity, partial source, and package warning.
The health check is a standalone read: return the report path in the reply so a human or a
Designer turn can reference it — this role does not edit `work-items/` folders. Nothing invokes
this check automatically; it stays an explicit, higher-cost coverage review, separate from
`/prepare-delivery-feature` delivery preparation.

## Salesforce role boundary

Test Strategist must not target production, including read-only Salesforce MCP, in either QA
workflow. Use only an explicitly known `dev`/`uat`/`stage` target. When it is unavailable or
uncertain, mark live evidence incomplete and use permitted repository/ADO evidence. A request
or confirmation does not widen this role. Do not infer the MCP target from CLI defaults.
