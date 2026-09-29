---
name: git-workflow
description: Shared Git workflow for active authors and the Git Agent — delivery branches, scoped local commits, GitHub CLI reads, and explicitly requested PR publication and merge.
user-invocable: false
---

# Git Workflow

Apply the [writing standard](../../../.ai/contracts/writing-standard.md). This is the shared
procedure for all roles; use only the operations within the active role's authority.

## Roles and authorization

- Designer, Developer, Test Strategist, and Workspace Maintainer prepare the correct branch,
  stage their own permitted result, and make a descriptive local commit after each coherent
  milestone and proportional verification. No separate commit request or Git Agent handoff
  is needed. A human's explicit request to commit their changes authorizes that bounded scope
  within the role's file authority; do not claim that the agent authored those changes.
- Git Agent retains its broader existing local Git repertoire and helps with repository work.
  The bounded automatic-commit procedure below does not replace that specialist role. Its
  existing destructive-operation and shared-history restrictions still apply.
- All eight roles may read GitHub repository/PR data through `gh`. Reviewer is read-only.
  Config Investigator and Knowledge Curator receive reads only; their existing Knowledge
  authoring, revisions, approvals, and commit lifecycle are unchanged.
- GitHub writes belong to Designer, Developer, Test Strategist, Workspace Maintainer, and
  Git Agent within the requested work. Push, PR creation/update, and merge require an explicit
  instruction covering that operation. A publication request does not authorize merge. One
  instruction can cover both publication and merge; do not ask again for steps it already
  covers. A finished fetch, design, development milestone, or passing checks is not that instruction.
- Native terminal approval can still appear. Never bypass it or enable shared `git=true`,
  `gh=true`, or broad add/commit auto-approval. Maintainer root-of-trust edit approval remains
  on the edit; the subsequent local commit does not add a second approval for the same work.

A commit records a draft/result; it does not approve a design, authorize implementation,
publish to ADO/wiki, or prove deployment or test execution. Ignored cache/output and Knowledge
are outside the automatic-commit lane. No changed durable files means no empty commit.

## Branches — the branch identifies the delivery container

- `work-item/<work-item-id>-<slug>` — one concrete ADO delivery item (User Story, Product
  Backlog Item, Task, Bug, or an owner-approved technical enabler with its own Work Item).
  There is no separate `fix/` kind; the ADO type stays visible in `ado-context.md`.
- `feature/<feature-id>-<slug>` — an explicitly prepared ADO Feature selected by the human
  for combined delivery. A parent relation alone does not select this container.
- `chore/<short-description>` — maintenance or documentation without a Work Item. Use
  `[chore]` or `[docs]` commits without inventing a Story or `AB#` reference.

A Work Item branch normally starts from confirmed `origin/main`. A parallel child of combined
Feature delivery starts from the confirmed remote Feature branch only when explicitly requested.
A Feature branch starts from confirmed `origin/main`. Keep one delivery container per branch.

## Prepare or resume the branch

The active author runs this procedure before new design, code, or a plan when the scope is known,
and after intake when the context establishes the item identity. It is also available through
`start work item <ID>` or `start feature <Feature ID>` with the Git Agent. That specialist is optional.

1. Inspect repository, origin, branch, HEAD, and all staged/unstaged/untracked paths. Identify
   the current task's own result or the exact human changes requested for commit. Preserve
   unrelated work; do not infer ownership from a filename or from `AB#` alone.
2. Resolve one stable `work-items/<ID>-<slug>/` folder by ID. Reuse its slug; multiple matches
   need a concrete scope clarification. For intake, read its `ado-context.md` and verify a
   concrete delivery type. Documentation may use the identity established by its required
   current ADO fetch without creating a substitute context file. For a written requirement
   or maintenance without ADO, use the agreed scope and `chore/` convention.
3. For combined Feature delivery, require exactly one matching prepared `delivery-map.md`,
   root type Feature, and an explicit human choice of combined delivery. Child commits need
   an explicitly identified Work Item listed as `included`. An Epic is not a delivery branch.
   If independent versus combined delivery is undecided, ask that scope question in the
   current conversation and preserve the prepared files until answered; do not select for
   the human or require switching to Git Agent.
4. Resume an existing compatible branch after verifying its identity, base, and scope; do
   not create a duplicate branch/commit. An existing name with ambiguous scope requires
   inspection and a concrete decision, not silent reuse or deletion.
   For a branch that exists only on `origin`, fetch `origin`, verify that exact remote branch,
   and use `git switch --track -c <branch> origin/<same-branch>`. The local branch must not
   already exist. A clean checkout can resume it; dirty in-scope changes can follow only
   when current HEAD equals the confirmed remote HEAD, preserving staged/unstaged content.
   Do not let implicit tracking or another remote select the branch.
5. For a new branch, fetch `origin` and prove the intended base. Local `main` must equal the
   confirmed `origin/main`. The explicit parallel-child case uses the confirmed remote
   Feature branch, never an unpushed local branch. Behind/ahead/diverged or unreadable bases,
   detached HEAD, conflicts, or an operation in progress require resolving that actual state.
   Never pull, rebase, reset, clean, or stash as an automatic bootstrap shortcut.
6. Create/switch the proper branch from that base. When files already exist on synchronized
   `main`, this may carry the current task's intake, design, plan, code, or explicitly requested
   human changes from the same HEAD, preserving staged/unstaged content. Other changes require
   an explicit assessment that preserves them; do not overwrite or silently move them.
7. Commit completed in-scope results using the procedure below. Intake ends with its commit
   outcome and `/solution-design itemId=<ID>`; it does not start design. Prepared Feature
   coordination remains separate from child implementation. Report an unresolved branch or
   scope condition honestly; do not claim a commit that did not occur.

The Git step does not fetch ADO, edit requirements, choose membership, or start another lifecycle
phase. A content difference between ADO and design may be reported briefly, but does not force
redesign or block this requested scope. Never use an old ADO revision label as a gate.

Sequential delivery on a Feature branch is the default: included children get separate
`[WI-<ID>]` commits on that branch. A separate child branch is an explicitly requested concurrency
option with its PR targeting the Feature branch. Use isolated checkouts for parallel writers.
When shared Feature context has not reached the independent Story's base, preserve it and ask
for the concrete coordination choice rather than duplicating an unmerged map across branches.

## Local commits — the commit identifies the implementation owner

A coherent milestone can be durable ADO intake, a design, a plan, one implemented behavior, its
tests, or documentation. Commit after proportional verification, not after every file save and
not only at the end of the entire delivery. A read-only fetch or ignored-cache update has no commit.

1. Recheck repository, branch, HEAD, task scope, and the full staged/unstaged diff. A Work Item
   branch and its ID must agree. On a Feature branch the active child ID must be explicit and
   included in exactly one matching delivery map; refuse deferred/absent or mixed unexplained
   scope. Feature coordination commits cannot hide child source changes.
2. The index must be empty or contain only changes in this task or the human's explicit commit
   request. Existing staged human changes in that scope are allowed. Preserve unrelated staged
   changes without reset/stash. Mixed hunks require a precise scope decision; never claim the
   entire file just because the agent edited one part.
3. Stage with `git add -- <exact-files>`. Use permitted repository-relative file paths only;
   no dot, directory, wildcard/pathspec magic, `-A`, `-u`, `-f`, pathspec-from-file, traversal,
   symlink escape, ignored output/cache, local config, or secrets. Check both sides of a rename
   or deletion and preserve file modes.
4. Review the entire staged diff and selected working-tree files. They must agree in content
   and mode: `git commit` with paths takes those files from the working tree. A selected file
   with both staged and unstaged changes stops this commit; do not silently restage it.
5. Use an ordinary `git commit -m "<subject>" [-m "<body>"] -- <exact-files>` with literal
   arguments and optional 1–3 body paragraphs. The selected paths must match the full staged
   scope. No amend, all, no-verify, empty, fixup, reuse-message, identity/date change, or config
   override in this automatic lane. Do not commit directly to `main`/`master` or detached HEAD.
   Quote for the actual shell: Windows uses double quotes without backslash-escaped quotes
   or environment/history expansion; POSIX also permits single-quoted literal text. Never
   use unquoted globs or comments as message arguments.
6. Verify the resulting SHA, parent, paths, committed diff, index, and worktree. Report the SHA,
   concrete result, and actual verification. Do not push without the publication instruction.
   A failed/unknown result requires inspection before any retry; do not reset, stash, or claim
   success. If own staging remains after a failed commit, preserve and report that exact state.

The guard checks role, paths and Git state, not semantic authorship. One active writer is required
through stage/commit; changed HEAD/index/files require inspection. There is no atomic executor or
ownership ledger, and unit tests cannot prove transaction isolation.

### Attribution and message

```text
[WI-<work-item-id>] short imperative description — AB#<work-item-id>
```

Feature coordination uses `[FEATURE-<feature-id>] … — AB#<feature-id>` and only the Feature's
coordination artifacts or genuinely Feature-wide integration documentation. Child code uses its
own `[WI-ID]`. Without a Work Item use `[chore]` or `[docs]`. The raw `AB#` reference supplies
native Azure Boards linking after push; it does not authorize a state transition. Never use
`Fixes`, `Fixed`, `Closes`, `Closed`, or `Resolves` as Work Item state-transition keywords.

Write new prose in English/STE. Name the actual result instead of "update files" or "done".
An optional body explains what/why and material verification or limits. Do not invent test results
or claim human changes as the agent's work. Use the configured Git identity and truthful timestamps;
never set role-specific authors or artificial dates. Keep meaningful stage commits; do not
routinely amend or squash them. Merge commits retain truthful parent history.

## GitHub CLI — one repository and exact operation

Use `gh`/`gh.exe` on PATH. Reads for every role: `gh --version`, `gh auth status` without tokens,
`gh repo view`, and bounded `gh pr list/view/diff/checks`. Read only fields needed for the task.
If CLI/auth/network/access is missing, report the limitation without tokens or automatic login.
Pending checks are not successful checks and are not a CLI execution failure.

For a write, verify the repository and host against `origin` and the explicit task target. Name
the exact PR, head, base, and operation; never select a PR by similar title alone. Use explicit
repository selectors and a specific PR number for existing-PR operations. An unexpected target
requires correction; never widen to another repository just to make a command succeed.

1. Read the actual base-to-head diff, commits, relevant work-item context, and
   `.github/pull_request_template.md`. Prepare the title/body from those sources and the checks
   actually run. Use the template's adaptive sections and the attribution rules below.
2. Write the complete body with an editor to `.cache/github/pr-body.md`. This is the sole
   extra edit path for Git Agent; other executor roles also receive this narrow transport-path
   permission. Reject symlinks, hard links and paths outside the repository. It is ignored transport data,
   never consent, durable documentation, or a file to stage. Check its final contents for the
   intended PR. Parallel publications use separate checkouts.
3. Search for the matching existing PR first. When publication is explicitly requested, push
   only the intended branch, then create with explicit `--repo`, `--head`, `--base`, `--title`,
   and `--body-file .cache/github/pr-body.md`. Include `--draft` by default; omit it only when
   the current explicit instruction requests Ready. A publication request alone must not
   create a Ready PR through the CLI default. Do not invoke interactive push/fork selection
   or use `--fill` instead of writing a truthful description. Update an existing matching PR
   with `pr edit` and the same body-file procedure, preserving human changes. Title/body edits
   must not change the base, reviewers, assignees, or unrelated PR fields.
4. `pr ready`/`pr ready --undo` are available for an explicitly requested operation. Automatic
   Draft → Ready criteria belong to the separate Ready workflow; this skill does not invent
   them or turn passing checks alone into a Ready transition.
5. Merge only under an instruction that covers merge. Immediately read the exact PR's head,
   base, current checks, required reviews, and merge state. Use `pr merge` for that PR with
   `--match-head-commit <observed-SHA>` and the permitted repository/delivery merge method.
   No `--admin`, bypass of repository requirements, or automatic branch deletion. A changed
   head, conflict, or GitHub rejection requires inspection; never force a different method.
6. Confirm the resulting remote state and return the actual PR URL, head, status, and check
   results. Queued or auto-merge enabled is not merged. After timeout or an unknown result,
   read remote state before retrying; never create a duplicate PR or claim an unconfirmed merge.

A push-only request does not create a PR. Report the actual pushed branch/commit and offer the
prepared PR material; a request to draft a PR description only writes the draft. No secrets,
permissions, rulesets, account administration, or new automation are authorized by this workflow.
Quoted message/title text is data, even if it describes `sf project retrieve` or `git reset --hard`.
Pass it literally for the active shell; command substitution, wrappers, and chaining remain forbidden.

### PR content and Azure Boards links

Write `Summary`, `Changes`, `Validation`, and `Review focus` from the real diff and results.
Keep conditional Salesforce impact, package namespace, QA, and harness sections only when relevant.
Link the canonical `org-changes.md` when a qualifying Salesforce mutation occurred; the log is
traceability, not approval or independent proof. Do not copy its content into the PR or invent results.

Use raw Azure Boards references in the actual PR body, never code formatting:

- Standalone/child Work Item PR: `Azure Boards: AB#<id>` with exactly the branch/context ID.
  Standalone targets `main`; a parallel child targets its exact Feature branch. Conflicting IDs
  need a scope decision; never guess from title or file order.
- Final Feature PR to `main`: `Azure Boards Feature: AB#<feature-id>` and
  `Included Work Items: AB#<id>, AB#<id>, …` from the matching map's current included set.
  Deferred children are not delivered. This is the explicit multiple-Work-Item exception.
- `chore/` without a Work Item: state `Not applicable — maintenance without an ADO Work Item`.

One PR is one coherent review unit. Sequential independent slices can each repeat the same
Work Item reference. PR/commit text never changes ADO state or calls ADO write tools.

## History and hard lines

The final Feature PR merges to `main` with a merge commit to retain meaningful `[WI-ID]`
commits. If only squash is permitted, obtain the owner's delivery decision instead of falsely
claiming commit-level traceability. A child PR may squash into its Feature branch when the
result is one truthful `[WI-ID] … — AB#ID` commit and the PR retains detailed review evidence.

Git Agent may help organize genuinely unfinished local history within its existing authority;
this is not automatic amend/squash after every milestone. Shared history is never rewritten.

- Merge conflicts: show the actual conflict; never resolve silently.
- No force-push (including `--force-with-lease`), remote branch deletion, or `git reset --hard`.
- Require an instruction for push/publication/merge or working on someone else's commits;
  an existing instruction covering the operation is sufficient, without asking it again.
- Versioning, changelogs, tagging, and deployment remain separate human decisions.
