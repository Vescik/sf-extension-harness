---
name: git-workflow
description: Shared Git and GitHub CLI workflow for all roles, with commit-message validation and explicitly requested publication, merge, and destructive actions.
user-invocable: false
---

# Git Workflow

Apply the [writing standard](../../../.ai/contracts/writing-standard.md).
All eight roles can use all Git and `gh`/`gh.exe` commands. Git Agent is optional assistance,
not a required handoff. Hooks do not limit branches, paths, working directories, staging,
commit options, remotes, repositories, or PR operations. Salesforce/ADO configuration does
not gate Git. The only Git-specific validation is the commit message.

## Scope and authorization

Preserve unrelated staged, unstaged, and untracked work. Inspect the actual diff before
committing; include only the requested result or changes the human explicitly asks to commit.
Choose the staging method that fits that scope, including partial staging or `git add -A`.
Active authors can commit coherent milestones after proportional verification without a
separate commit request. A review request stays a review; available Git commands do not
instruct Reviewer to change source. Knowledge authoring and approval keep their own lifecycle.
Editor permissions and Salesforce/ADO access controls are unchanged.

Push, PR creation/update, merge, and destructive Git operations require an explicit human
instruction covering the operation. This includes `reset --hard`, `clean -fd`, force push,
shared-history rewriting, and remote deletion. Existing authorization is sufficient; do not
ask again for steps it already covers. A publication request does not authorize merge.
One instruction can cover both publication and merge. A push-only request does not create a PR.
Completing work or passing checks is not a publication instruction. Ordinary local conflict
resolution follows the requested scope; report conflicts that need a human decision.
Native host approval may still appear independently of the repository hooks.

## Branches and local commits

Inspect repository state and choose or reuse a branch suitable for the requested work.
These names are conventions, not requirements:

- `work-item/<work-item-id>-<slug>` for one concrete delivery item.
- `feature/<feature-id>-<slug>` for combined Feature delivery selected by the human.
- `chore/<short-description>` for maintenance or documentation without a Work Item.

Other branches, including `main`, are permitted. No branch name, ADO fetch, context file,
delivery map, synchronized base, or index/working-tree equality is a Git prerequisite.
Use actual requirement context when the delivery task needs it; never invent an ADO ID.
A parent relation alone does not select combined Feature delivery. Feature membership is a
planning decision, not a Git gate. `start work item <ID>` and `start feature <Feature ID>`
remain optional Git Agent entry points. Intake returns `/solution-design itemId=<ID>` when
appropriate; a Git action does not start a new lifecycle phase.

Review the staged result, commit it, and verify the resulting SHA and remaining changes.
Report actual verification and whether the result is local or published. Inspect a failed or
unknown outcome before retrying. Do not reset or stash unrelated work to make a commit pass.

## Commit message

Use a nonempty descriptive subject in one of these forms:

```text
[chore] Update workspace configuration
[docs] Describe deployment procedure
[WI-123] Add account validation — AB#123
[FEATURE-456] Integrate billing changes — AB#456
```

For `[WI-<work-item-id>]` and `[FEATURE-<feature-id>]`, the subject's `AB#` number must match
the prefix number, with no conflicting ID in that subject. `[chore]` and `[docs]` need no ADO
reference. The validator checks the first line exactly as supplied, without stripping comments
or rewriting content. The body is unrestricted and may reference other Work Items. No ADO,
branch state, task files, or delivery maps are inspected. Write the actual result in English/STE;
an optional body explains why and actual verification.
Use configured identity and truthful dates. Preserve useful history unless rewriting it is
part of the explicit request. Do not use `Fixes`, `Resolves`, or `Closes` as ADO state-transition
instructions. A commit neither approves a design nor proves a deployment or test result.

The pre-tool hooks validate a supplied message when available. For final messages produced
by an editor, file, or Git itself, install the repository's `commit-msg` hook in each checkout:

```text
python3 scripts/install_git_message_hook.py
```

On Windows, use `python scripts/install_git_message_hook.py`. The installer copies a standalone
validator beside the local hook in Git metadata, so changing branches does not remove it.
Rerun the installer to refresh that copy after a validator update. Git's own hook-skipping
options retain their normal behavior; the agent must still produce a valid message. This is
not a server-side guarantee for every commit path.

If the installer preserves an existing hook or `core.hooksPath`, keep its checks. Copy
`scripts/git_workflow_policy.py` to the path returned by
`git rev-parse --git-path hooks/sf-harness-git-message-policy.py`, creating its parent directory
if needed. This keeps the validator in Git metadata even when the custom hook is tracked in
the worktree. Call that copy before final success (`python` on Windows):

```sh
validator=$(git rev-parse --git-path hooks/sf-harness-git-message-policy.py) || exit 1
python3 "$validator" --message-file "$1" || exit $?
```

## GitHub work

Use the user's configured CLI authentication without printing tokens. Resolve the intended
repository and PR from the request and actual state. Inspect its diff, head/base, current
checks, and reviews before acting. Search for an existing matching PR before creating one;
read remote state before retrying a timeout or uncertain result. Queued or auto-merge enabled
is not merged. Report the actual PR URL, head, status, and checks.

Use `.github/pull_request_template.md` for truthful descriptions. Write the body through the
editor to the ignored `.cache/github/pr-body.md` and pass `--body-file`; this transport file
is the Git Agent's existing narrow editor exception, never a source/Knowledge edit grant.
Preserve human edits. Prefer explicit `--repo`, `--head`, `--base`, and `--title` when creating
a PR and `--match-head-commit` when merging to avoid acting on a changed head. These are
workflow practices, not hook-enforced command restrictions. Ordinary publication defaults
to Draft unless Ready is requested. Respect repository requirements and the authorized scope.

Link the canonical `org-changes.md` when Salesforce mutations occurred. The log is
traceability, not approval or independent proof. Do not copy its content into the PR or invent results.
For Work Item PRs, use raw `Azure Boards: AB#<id>` references. For combined delivery, use
`Azure Boards Feature: AB#<feature-id>` and `Included Work Items: AB#<id>, …` from the agreed
scope. For maintenance without ADO, state that the reference is not applicable. These links
do not authorize ADO updates. Publication, merge, release, and deployment are separate actions.
