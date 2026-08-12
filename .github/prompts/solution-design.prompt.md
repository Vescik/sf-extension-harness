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

Route by the persisted item type before designing: a Feature is never designed directly — stop
and return `/prepare-delivery-feature itemId=<ID>`; an Epic needs a concrete child
Feature/Work Item named by the human. For a concrete item, require the current branch to be
`feature/<id>-<slug>` or `fix/<id>-<slug>`, agreeing with the persisted folder. If design is
invoked from `main` or an unrelated branch, write nothing and return
`git-agent: start work item <ID>`; the Designer never creates or switches branches. Then follow
the skill's bounded local
delivery-map lookup (exact included ID; zero matches designs standalone, one match reads the
prepared Feature context, several are surfaced and never guessed). Type and local map routing
must complete before reading the package design documents or making any Knowledge or
Salesforce call — the skill's Stage 1 comes first, always.

For a written requirement without an ADO item, proceed directly — no `ado-context.md` exists or
is fabricated, and the design identifies the requirement as human-provided.
