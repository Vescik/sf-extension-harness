---
name: git-workflow
description: The team's git conventions — start an ADO-backed work item after intake, branch naming, commit format, push-time copyable PR handoff, conflict handling, and squash policy. One source of truth shared by the git agent and developer.
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

## Start an ADO-backed work item

Run this bootstrap after `/fetch-ado-item` has persisted a concrete Story/Bug/Task context and
before `/solution-design`. For a prepared multi-Story Feature, run it only after the selected
Story has also been fetched; the branch is always Story-scoped, never Feature-scoped.

Input: `start work item <ID>`.

1. Read exactly one `work-items/<ID>-*/ado-context.md`. Stop on zero or multiple matching
   directories. Derive the stable slug from that directory and the branch kind from the persisted
   item type (`Bug` → `fix`; every other concrete delivery item → `feature`). A persisted Feature
   or Epic is not branchable here: return the existing Feature/child-selection route.
2. Require the current branch to be `main` and inspect status before changing refs. Fetch `origin`
   when configured, then prove local `main` equals the confirmed `origin/main`. If it is behind,
   ahead, diverged, conflicted, or cannot be compared, stop with evidence; never pull, rebase,
   merge, reset, or stash as a shortcut.
3. Allow only the intake set to be dirty:
   - the concrete item's `ado-context.md`;
   - when exactly one prepared `delivery-map.md` includes the ID, that Feature's sibling
     `ado-context.md` and `delivery-map.md` if they are also dirty.
   Any other tracked, staged, or untracked path stops the bootstrap. Never use `git add .`, `-A`,
   or a broad pathspec.
4. Create and switch to `<kind>/<ID>-<stable-slug>`. If it already exists locally or remotely,
   stop, report it, and ask the human whether this is a resume or a new delivery slice; never
   delete or silently reuse it.
5. Stage only the exact intake paths established in step 3. Verify the staged diff contains no
   other path, then create one local commit:

   ```text
   [<ID>] add work item context
   ```

   When dirty prepared-Feature files are included, use `[<ID>] add delivery context`. An unchanged
   context needs no empty commit.
6. Verify the worktree is clean and report the branch, base, committed paths, and commit ID. Do
   not push. End with exactly `/solution-design itemId=<ID>`.

The bootstrap owns Git placement only. It does not fetch ADO, edit context, prepare a Feature,
design, or implement. If `design.md` already exists, this is not a new-work bootstrap; requirement
refresh follows the existing Solution Design reconciliation route on the current work branch.

For parallel Stories whose prepared Feature files are not yet on `main`, do not duplicate or
silently fork the shared context across unrelated branches. Stop and ask the human to choose
sequential delivery after the first Story lands or a separately reviewed context-only handoff.
That exceptional coordination decision is never inferred by the git agent.

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

### After a successful push

Whenever the git agent itself successfully pushes a branch, finish that same turn with a
copyable PR handoff. This is an output contract, not permission to create a PR:

1. Confirm the push succeeded and identify the pushed remote, current branch, and intended base
   (normally `main`). A rejected, failed, or unverified push never produces a success handoff or
   a claimed PR link.
2. Read `.github/pull_request_template.md`. Build a suggested PR title and a fully completed
   description from the actual `<remote>/<base>...HEAD` diff, its commits, the matching local
   work-item artifacts when present, and checks actually run. Preserve the template's adaptive
   rules: retain only relevant conditional sections, never invent validation, and write
   `Not verified` where a required fact is genuinely unknown.
3. Return, directly in chat:
   - the branch, base, pushed remote, and pushed commit;
   - a suggested PR title;
   - the complete PR description in one copyable Markdown code block;
   - a direct GitHub compare link when the pushed remote can be proven to identify a GitHub
     `<owner>/<repo>`: `https://github.com/<owner>/<repo>/compare/<base>...<branch>?expand=1`.
4. If the pushed remote is not GitHub or its repository identity cannot be derived safely, still
   return the title and completed description, but state that no reliable creation link can be
   generated. Never guess an owner or repository.

Do not require GitHub CLI, call GitHub APIs, open a browser, or create the PR. The human copies
the description, follows the link, reviews the populated form, and submits it. A separately
requested `prepare PR` may draft the same material before a push, but only a confirmed push
triggers the automatic link-bearing handoff above.

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
