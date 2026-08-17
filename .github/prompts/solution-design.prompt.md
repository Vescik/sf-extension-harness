---
name: solution-design
description: Design a work item with the designer agent — thin alias, no logic of its own.
argument-hint: "itemId=<ID> for ADO-backed work, or a written requirement"
agent: designer
---

Use the designer agent for the given input — an ADO work item ID (`itemId=<ID>`) or a written
requirement. Follow the whole [solution-design skill](../skills/solution-design/SKILL.md), in
its order: the skill's Stage 1 owns context resolution, item-type routing, the delivery
container, and delivery-map membership before any discovery, and its stop/recovery returns are
the ones to use. The result is `work-items/{id}/design.md`.

For a written requirement without an ADO item, no `ado-context.md` exists or is fabricated, and
the design identifies the requirement as human-provided.
