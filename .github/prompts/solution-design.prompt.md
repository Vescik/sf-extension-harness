---
name: solution-design
description: Design a work item with the designer agent — thin alias, no logic of its own.
argument-hint: "itemId=<ID> for ADO-backed work, or a written requirement"
agent: designer
---

Use the designer agent for the given input: an ADO work item ID or a written requirement.
Follow the [solution-design skill](../skills/solution-design/SKILL.md); the result is
`work-items/{id}/design.md`.

For an ADO item ID, the persisted requirement context is required first: resolve exactly one
`work-items/<id>-*/ado-context.md`. If none exists, stop and return the recovery command
`/fetch-ado-item itemId=<ID>` — do not fetch-and-design in one turn. If more than one folder
matches the ID, stop with `INCOMPLETE — NEEDS HUMAN`.

For a written requirement without an ADO item, proceed directly — no `ado-context.md` exists or
is fabricated, and the design identifies the requirement as human-provided.
