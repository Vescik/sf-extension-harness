---
name: git-workflow
description: The team's git conventions — work-item and Feature delivery branches, explicit Work Item commit attribution with native AB# traceability, push-time copyable PR handoff, conflict handling, and merge policy. One source of truth shared by the git agent and developer.
user-invocable: false
---

# Git Workflow

These conventions are the team's, not yours: follow them even when you know a different
way. This skill is loaded by the git agent and the developer alike — the convention holds
no matter who performs the operation.

## Branches — the branch identifies the delivery container

- `work-item/<work-item-id>-<slug>` — one concrete ADO delivery item (User Story, Product
  Backlog Item, Task, Bug, or an owner-approved technical enabler with its own Work Item),
  e.g. `work-item/242850-approval-notifications`. There is no separate `fix/` kind: a Bug is
  a concrete delivery item like any other; its ADO type stays visible in `ado-context.md`.
- `feature/<feature-id>-<slug>` — reserved for an explicitly prepared multi-Story ADO
  Feature delivered as one combined container, e.g. `feature/5000-approval-management`.
- `chore/<short-description>` — maintenance without a work item.

A `work-item/` branch starts from confirmed `origin/main`, or — as a parallel child of a
combined Feature delivery — from the confirmed remote Feature branch. A `feature/` branch
always starts from confirmed `origin/main`. One delivery container per branch.

## Supported operations

```text
start work item <ID>
start feature <Feature ID>
commit work item <ID>
commit feature <Feature ID>
push
prepare PR
```

## Start an ADO-backed work item

Run this bootstrap after `/fetch-ado-item` has persisted a concrete Story/Bug/Task context and
before `/solution-design`.

Input: `start work item <ID>`.

1. Read exactly one `work-items/<ID>-*/ado-context.md`. Stop on zero or multiple matching
   directories. Derive the stable slug from that directory. The persisted item type must be a
   concrete delivery item; a persisted Feature or Epic is not branchable here — a prepared
   Feature uses `start feature <Feature ID>` instead, and an Epic gets no branch at all.
2. Choose and prove the base:
   - default: the current branch is `main`; fetch `origin` when configured, then prove local
     `main` equals the confirmed `origin/main`;
   - explicitly requested parallel child of a combined Feature delivery: the human names the
     Feature; require exactly one prepared `delivery-map.md` matching that Feature which lists
     `<ID>` as included, and base the child on the confirmed **remote** Feature branch — never
     on an unpushed local state, and never inferred without the human's instruction.
   If the base is behind, ahead, diverged, conflicted, or cannot be compared, stop with
   evidence; never pull, rebase, merge, reset, or stash as a shortcut.
3. Allow only the intake set to be dirty:
   - the concrete item's `ado-context.md`;
   - when exactly one prepared `delivery-map.md` includes the ID, that Feature's sibling
     `ado-context.md` and `delivery-map.md` if they are also dirty.
   Any other tracked, staged, or untracked path stops the bootstrap. Never use `git add .`, `-A`,
   or a broad pathspec.
4. Create and switch to `work-item/<ID>-<stable-slug>`. If it already exists locally or remotely,
   stop, report it, and ask the human whether this is a resume or a new delivery slice; never
   delete or silently reuse it.
5. Stage only the exact intake paths established in step 3. Verify the staged diff contains no
   other path, then create one local commit:

   ```text
   [WI-<ID>] add work item context — AB#<ID>
   ```

   An unchanged context needs no empty commit. The raw `AB#<ID>` is link-only: once pushed, the
   existing Azure Boards–GitHub integration links the commit to the Work Item natively, so no
   manual Branch link is required before continuing. Never append a state-transition phrase.
6. Verify the worktree is clean and report the branch, base, committed paths, and commit ID. Do
   not push. End with exactly `/solution-design itemId=<ID>`.

The bootstrap owns Git placement only. It does not fetch ADO, edit context, prepare a Feature,
design, or implement. If `design.md` already exists, this is not a new-work bootstrap; requirement
refresh follows the existing Solution Design reconciliation route on the current work branch.

For parallel Stories whose prepared Feature files are not yet on `main`, do not duplicate or
silently fork the shared context across unrelated branches. Stop and ask the human to choose
sequential delivery after the first Story lands or a separately reviewed context-only handoff.
That exceptional coordination decision is never inferred by the git agent.

## Start a prepared Feature

Input: `start feature <Feature ID>`. A parent relation alone never creates a Feature branch:
an ordinary Story under a reporting Feature or Epic stays a standalone `work-item/` branch.
Every one of these must hold, proven locally, or the bootstrap stops:

1. the persisted root context in `work-items/<Feature ID>-*/ado-context.md` is an ADO
   **Feature** — not a Story, Task, Bug, or Epic;
2. `/prepare-delivery-feature itemId=<Feature ID>` completed: exactly one unambiguous
   `delivery-map.md` exists for the Feature (zero or multiple matching maps stop);
3. the human explicitly selected combined Feature delivery — this operation is that
   selection's execution, never an inference;
4. local `main` exactly matches confirmed `origin/main`, with the same dirty-path rules as the
   work-item bootstrap (only the Feature's own `ado-context.md` and `delivery-map.md` may be
   dirty and staged).

Create `feature/<Feature ID>-<stable-slug>` from that `main`, stage only the two Feature
coordination files, and commit:

```text
[FEATURE-<Feature ID>] add delivery context — AB#<Feature ID>
```

An existing local or remote branch of that name stops the bootstrap exactly as above. Do
not push without approval. The bootstrap does not fetch ADO, edit `ado-context.md` or
`delivery-map.md`, select Feature membership, or fetch any child Story — only the child
currently being started is ever fetched, by the human, through `/fetch-ado-item`.

Sequential delivery on the Feature branch is the default: included child Work Items land as
logically separated `[WI-<ID>]` commits directly on the Feature branch. Do not create a child
`work-item/` branch merely because another included item starts; a child branch is the explicit
concurrency escape hatch (separate reviewer, concurrent work, isolated rollback), requested by
the human, based on the confirmed remote Feature branch, with its PR targeting the Feature
branch. One active writer per shared Salesforce component remains required.

## Commits — the commit identifies the implementation owner

Format for ADO-backed delivery work:

```text
[WI-<work-item-id>] short imperative description — AB#<work-item-id>
```

e.g. `[WI-242850] add notification pref flow — AB#242850`. Feature coordination commits use
`[FEATURE-<feature-id>] … — AB#<feature-id>`. Without a work item: `[chore]` or `[docs]`, no
`AB#` reference. `git log --grep '\[WI-242850\]'` must return the item's full implementation
history — that is the local traceability mechanism, so the prefix is not optional; the raw
`AB#<ID>` gives ADO its native commit link once pushed. Never use a state-transition keyword
(`Fixes`, `Fixed`, `Closes`, `Closed`, `Resolves`) anywhere in a commit message — commits and
PRs never change Work Item state.

### `commit work item <ID>`

On a standalone or child `work-item/<branch-ID>` branch, `<ID>` must equal the branch's ID;
refuse a mismatch and ask which container the change belongs to.

On a `feature/<Feature ID>` branch, the agent cannot infer the active Work Item — the ID is
always explicit, and before committing it must:

1. resolve exactly one prepared `delivery-map.md` whose Feature ID matches the current branch
   (zero or several matching maps stop, with every candidate named — never chosen by title,
   path order, or modification time);
2. confirm `<ID>` is currently listed as `included` — a deferred or absent item is refused with
   its actual map status and the human decides (re-prepare the scope, or deliver standalone);
3. resolve exactly one `work-items/<ID>-*/ado-context.md`;
4. inspect the staged/unstaged diff and refuse mixed, unexplained Work Item scope — the human
   decomposes it; never commit two items' changes under one ID;
5. create the `[WI-<ID>] … — AB#<ID>` commit.

### `commit feature <Feature ID>`

Permitted only for Feature coordination artifacts (the Feature's own `ado-context.md`,
`delivery-map.md`) or genuinely Feature-wide integration documentation. It must never be used
to hide source changes belonging to a child Work Item — those get `commit work item <ID>`.

Merge commits created while synchronizing a shared branch are exempt from the subject-prefix
format but must retain Git's truthful parent history and are never rewritten after push.

## Pull requests

Before opening: branch up to date with its base; history tidy (see below); the PR template
filled in truthfully — a PR whose namespace section contradicts the diff is a defect in
the PR, not a formality.

The description is adaptive, not boilerplate. Write `Summary`, `Changes`, `Validation`,
and `Review focus` from the actual staged/PR diff, the linked work-item context, and the
commands actually run — never invent a passing result. When a qualifying Salesforce mutation
was executed, use the single canonical `org-changes.md` as the traceability source and link it in
the Salesforce impact section; never copy it into PR prose or treat it as proof/approval. When no
qualifying mutation ran, say so explicitly. Keep a conditional section
(Salesforce impact, package namespace, QA handoff, harness changes) only when its subject
appears in the diff or is a real delivery concern; delete the rest instead of filling
them with repeated "N/A".

Azure Boards linking depends on the delivery container. All references are plain raw text,
never in backticks or a code block; Azure Boards creates the native GitHub link from them, and
no ADO MCP call creates or updates anything. State-transition keywords are never used.

- **Standalone or child Work Item PR** (`work-item/<id>-…`): exactly one matching

  ```text
  Azure Boards: AB#<id>
  ```

  A standalone PR targets `main`; a child PR targets its exact Feature branch. Derive the ID
  from the established work-item context and confirm it agrees with the branch name and the
  local `work-items/<id>-<slug>/` directory when those sources exist; if candidate IDs
  disagree, stop and ask the human instead of choosing one.
- **Final Feature PR** (`feature/<feature-id>-…` to `main`):

  ```text
  Azure Boards Feature: AB#<feature-id>
  Included Work Items: AB#<id>, AB#<id>, …
  ```

  The Feature ID comes from the branch and Feature context; the child IDs come mechanically
  from the current `included` set in the matching `delivery-map.md` — never from titles, commit
  prose, or chat. Deferred children are never represented as delivered. Multiple `AB#`
  references are an explicit exception here because this one PR delivers multiple Work Items.
- **`chore/...` without a Work Item**: the explicit "Not applicable — maintenance without an
  ADO Work Item" text.

One PR is one coherent review unit. A Work Item may be delivered through multiple
sequential PRs when each is an independently reviewable slice; every such PR repeats the
same `AB#<id>` reference and links only the one Work Item it delivers.

### After a successful push

Whenever the git agent itself successfully pushes a branch, finish that same turn with a
copyable PR handoff. This is an output contract, not permission to create a PR:

1. Confirm the push succeeded and identify the pushed remote, current branch, and intended base
   (`main` for standalone and Feature branches; the exact Feature branch for a child branch). A
   rejected, failed, or unverified push never produces a success handoff or a claimed PR link.
2. Read `.github/pull_request_template.md`. Build a suggested PR title and a fully completed
   description from the actual `<remote>/<base>...HEAD` diff, its commits, the matching local
   work-item artifacts when present, and checks actually run. Preserve the template's adaptive
   rules: keep exactly one Work Item mode (Work Item or Feature), retain only relevant
   conditional sections, never invent validation, and write `Not verified` where a required
   fact is genuinely unknown.
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

## History hygiene and merge policy

Clean history before review means logical commits — not `wip`, `fix`, `fix2`. Squash
when the local history is chaotic scaffolding; keep separate commits when each step
carries information a reviewer or archaeologist would want. Local history (unpushed) is
yours to rewrite; shared history is not — rewriting a pushed shared branch is never done.

The final Feature PR merges to `main` as a merge commit, preserving the logical `[WI-<ID>]`
commits as durable delivery boundaries. Do not squash the final Feature PR while Work Item
commits carry that traceability; if the target repository permits only squash merges, stop for
an owner decision instead of silently claiming durable commit-level traceability. A child Work
Item PR may be squash-merged into the Feature branch when that produces one truthful
`[WI-<ID>] … — AB#<ID>` commit and the child PR remains as detailed review evidence.

## Hard lines

- Merge conflict → **stop and show the human**; never resolve silently.
- Force-push in any form — including `--force-with-lease` — is never done (the safety
  hook denies it; a genuinely needed lease push is run by a human, by hand).
- Ask before: merging to `main`, pushing anything, touching someone else's commits.
- Versioning, changelogs, tagging, deployment: human decisions, out of scope.
