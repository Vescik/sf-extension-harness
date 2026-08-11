---
name: git-workflow
description: The team's git conventions — branch naming, commit format, PR preparation, conflict handling, squash policy. One source of truth, shared by the git agent and the developer.
user-invocable: false
---

# Git Workflow

These conventions are the team's, not yours: follow them even when you know a different
way. This skill is loaded by the git agent and the developer alike — the convention holds
no matter who performs the operation.

## Branches

- `feature/<work-item-id>-<slug>` — e.g. `feature/242850-approval-notifications`
- `fix/<work-item-id>-<slug>` — defect work tied to an item
- `chore/<short-description>` — maintenance without a work item

Branch from an up-to-date `main`; one work item per branch.

## Commits

Format: `[<work-item-id>] short imperative description` — e.g.
`[242850] add notification pref flow`. Without a work item: `[chore]` or `[docs]`.
`git log --grep '\[242850\]'` must return the item's full implementation history — that
is the entire traceability mechanism, so the prefix is not optional.

## Pull requests

Before opening: branch up to date with `main`; history tidy (see below); the PR template
filled in truthfully — a PR whose namespace section contradicts the diff is a defect in
the PR, not a formality.

The description is adaptive, not boilerplate. Write `Summary`, `Changes`, `Validation`,
and `Review focus` from the actual staged/PR diff, the linked work-item context, and the
commands actually run — never invent a passing result. Keep a conditional section
(Salesforce impact, package namespace, QA handoff, harness changes) only when its subject
appears in the diff or is a real delivery concern; delete the rest instead of filling
them with repeated "N/A".

Azure Boards linking: for `feature/<id>-...` and `fix/<id>-...` branches, the completed
description contains exactly the matching raw `AB#<id>` reference — plain text, never in
backticks or a code block; Azure Boards creates the native GitHub link from it. Derive
the ID from the established work-item context and confirm it agrees with the branch name
and the local `work-items/<id>-<slug>/` directory when those sources exist; if candidate
IDs disagree, stop and ask the human instead of choosing one. A `chore/...` branch
without a Work Item uses the explicit "Not applicable — maintenance without an ADO Work
Item" text. Do not add state-transition keywords (`Fixes`/`Resolves`/`Closes`) and do not
call ADO MCP to create or update the link — the description text is the whole mechanism.

One PR is one coherent review unit. A Work Item may be delivered through multiple
sequential PRs when each is an independently reviewable slice; every such PR repeats the
same `AB#<id>` reference and links only the one Work Item it delivers.

## History hygiene

Clean history before review means logical commits — not `wip`, `fix`, `fix2`. Squash
when the local history is chaotic scaffolding; keep separate commits when each step
carries information a reviewer or archaeologist would want. Local history (unpushed) is
yours to rewrite; shared history is not — rewriting a pushed shared branch is never done.

## Hard lines

- Merge conflict → **stop and show the human**; never resolve silently.
- Force-push in any form — including `--force-with-lease` — is never done (the safety
  hook denies it; a genuinely needed lease push is run by a human, by hand).
- Ask before: merging to `main`, pushing anything, touching someone else's commits.
- Versioning, changelogs, tagging, deployment: human decisions, out of scope.
