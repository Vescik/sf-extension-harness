# Delivery Process

This is the human operating procedure for delivering Azure DevOps Work Items through GitHub. It
defines when work becomes active, when it must be recoverable remotely, how often to synchronize,
and how to choose between independent Work Item delivery and a combined Feature branch.

> This document guides people. It does not change agent behavior. Repository prompts, skills,
> role contracts, and safety controls remain authoritative for agents. Steps marked
> **Human-managed in the current workspace version** are not automated by the current Git Agent.

For choosing a workspace playbook or prompt, use [Ways of Working](ways-of-working.md). For the
meaning of files under `work-items/`, see [work-items/README.md](../work-items/README.md).

## Lifecycle at a glance

```text
Fetch intake
  → decide to start
  → In Design + remote branch
  → first design checkpoint + Draft PR
  → implementation checkpoints
  → synchronize + verify
  → ready PR
  → human merge
  → ADO update and branch cleanup
```

Fetching is not the same as starting delivery:

- `/fetch-ado-item itemId=<ID>` persists a requirement snapshot. Fetch-only work may stop there.
- Work becomes active when Solution Design, solution investigation, test planning, or repository
  changes begin. At that point the Work Item enters the team's `In Design` stage.
- Once `In Design` begins, no design or implementation may exist only on an unpushed local branch.

If the target ADO project uses a different state name, the owner must identify its equivalent
before using this procedure. Agents do not change ADO state automatically.

## Remote-first rules

1. Start active work from the latest authoritative remote base.
2. Push the delivery branch as soon as `In Design` begins.
3. The bootstrap commit (`[WI-<ID>] add work item context — AB#<ID>`, or
   `[FEATURE-<ID>] add delivery context — AB#<ID>`) carries a link-only raw `AB#<ID>`: once
   pushed, the Azure Boards–GitHub integration links the commit to the Work Item natively.
   A formal Branch link in the ADO Development section is optional, not required by this
   process — attach one manually only if your team wants it.
4. Open a Draft PR after the first committed work beyond intake.
5. Put the matching raw `AB#` reference(s) in the PR description — exactly one for a Work Item
   PR; the Feature plus its included children for a final Feature PR. This links the PR when
   the Azure Boards–GitHub integration is configured.
6. Push every coherent checkpoint and before pause, handoff, risky synchronization, or the end of
   a work session.
7. Fetch and compare with the correct remote base at the start of each work session and before
   final review.
8. Never force-push shared history or let an agent resolve a conflict silently.

Remote-first does not mean push on every save. Do not publish broken generated output,
credentials, local configuration, or an incoherent half-change merely to satisfy a cadence.

## Branch and traceability conventions

The branch identifies the delivery container; the commit identifies the implementation owner.

| Purpose | Branch | Normal PR target | PR ADO reference |
|---|---|---|---|
| Concrete Work Item (Story, PBI, Task, Bug, approved enabler) | `work-item/<item-id>-<slug>` | `main`, or its Feature branch for a parallel child | `AB#<item ID>` |
| Prepared Feature, combined delivery | `feature/<feature-id>-<slug>` | `main` | `AB#<Feature ID>` plus included children |
| Maintenance without ADO | `chore/<short-description>` | `main` | Not applicable |

`work-item/` delivers one concrete ADO Work Item directly; there is no separate `fix/` kind —
a Bug's type stays visible in its `ado-context.md`. `feature/` is reserved for an ADO Feature
that was explicitly prepared with `/prepare-delivery-feature` and explicitly selected for
combined delivery; a parent relation alone never creates a Feature branch.

Commit delivery work as:

```text
[WI-<work-item-id>] short imperative description — AB#<work-item-id>
```

Feature coordination commits use `[FEATURE-<feature-id>] … — AB#<feature-id>`. The raw `AB#`
gives ADO its native commit link once pushed. Do not use `Fixes`, `Resolves`, or `Closes` to
transition ADO state. ADO state, merge, deployment, and release remain human decisions.

## How often to push and synchronize

### Push checkpoints

Push at minimum after:

- creating and committing the intake branch;
- the first persisted design baseline;
- accepting or reconciling a design;
- each independently understandable implementation slice;
- a material decision or QA-plan update;
- a successful verification milestone;
- conflict resolution and rerun of affected checks;
- preparing a handoff or changing who owns the work;
- ending the work session or leaving meaningful work overnight.

Do not keep more than one working session of meaningful work unpushed. Prefer small, meaningful
commits over `wip`, `fix`, and `fix2`. Once shared, correct history with a new commit; never rewrite
it with a force-push.

### Synchronization checkpoints

Run `git fetch origin` at the start of every session and before final review. Then compare against
the declared base:

- a normal Work Item branch synchronizes from `origin/main`;
- a parallel child Work Item branch synchronizes from
  `origin/feature/<feature-id>-<slug>`;
- the Feature branch synchronizes from `origin/main`.

After a branch has been pushed, merge the remote base into it when synchronization is required.
If a conflict occurs, stop, expose the conflicting files, obtain the business/technical decision,
then rerun validation affected by both the base update and the resolution.

## Procedure 1 — One User Story or Bug

```text
main
  └── work-item/5001-story-name → Draft PR → Ready PR → main
```

A Bug uses the same `work-item/` namespace.

### 1. Intake

1. Run `/fetch-ado-item itemId=5001`.
2. Review the persisted Description, Acceptance Criteria, source revision, completeness, and
   visibly unapproved AI understanding.
3. Stop if the result is a Feature/Epic rather than a concrete delivery item.
4. If nobody is starting work, stop here. Fetching alone requires no delivery branch.

### 2. Start `In Design`

1. Confirm the Work Item is ready to start and set `In Design` through the team's human ADO
   process.
2. Fetch GitHub state and prove local `main` matches `origin/main`.
3. Ask the Git Agent: `start work item 5001`.
4. Verify it created `work-item/5001-<slug>` and committed only the intended intake files as
   `[WI-5001] add work item context — AB#5001`.
5. Approve and perform the push. The pushed `AB#5001` commit gives ADO its native commit link;
   a manual Branch link in the Development section is optional.

The current Git Agent intentionally stops before push until a human approves it.

### 3. Design and open an early Draft PR

1. Run `/solution-design itemId=5001` on the matching branch.
2. Resolve material owner questions and commit the first coherent `design.md` baseline.
3. Push that checkpoint.
4. Use the Git Agent's completed PR template and compare link to open a Draft PR to `main`.
5. Confirm the PR includes exactly `AB#5001` and ADO shows the PR association.
6. Keep open questions and `Not verified` validation visible; do not wait for implementation to
   make work discoverable.

### 4. Implement in checkpoints

For each coherent slice:

1. fetch and inspect remote branch/base changes;
2. synchronize from `origin/main` when the base affects the work;
3. implement against the accepted design;
4. update tasks and append decisions when scope or implementation changes;
5. run proportional validation;
6. commit as `[WI-5001] <imperative description> — AB#5001`;
7. push;
8. update the Draft PR when scope, risk, validation, or review focus changed.

### 5. Prepare, review, and merge

1. Fetch and synchronize with the latest `origin/main`.
2. If ADO has a newer source revision, return to Solution Design and reconcile before proceeding.
3. Confirm AC coverage, recorded deviations, actual validation results, and QA handoff when needed.
4. Push the final synchronization and validation checkpoint.
5. Mark the PR ready only when its description matches the actual diff.
6. Wait for `PR CI / Gate` and any required human review.
7. A human decides whether to merge.
8. Confirm the merged `main`, update ADO manually, and delete local/remote delivery branches when
   safe. Keep the Work Item folder as durable history.

## Selecting a multi-Story Feature mode

Most Stories remain independent even when ADO gives them a Feature or Epic parent. A reporting
relationship alone does not justify a Feature branch.

After `/prepare-delivery-feature itemId=<Feature ID>`, it ends with the two explicit choices —
`git-agent: start feature <Feature ID>` for combined delivery on one Feature branch, or
`/fetch-ado-item itemId=<first-included-ID>` for independent child delivery. Select one mode
before child development:

| Question | Independent delivery | Combined Feature delivery |
|---|---|---|
| Can each Story be reviewed and merged safely by itself? | Yes | No or materially unsafe |
| Can incomplete child behavior exist safely on `main`? | Yes | No |
| Is combined behavior the real acceptance boundary? | Not necessarily | Yes |
| Must several Stories build a shared foundation before any works? | Usually no | Often yes |
| Must the Feature release atomically? | No | Yes |
| Default choice | **Yes** | Opt-in only |

Do not switch modes casually after child PRs exist. Retargeting several PRs or copying commits
requires an explicit owner decision and migration plan.

## Procedure 2 — Independent Stories, sequentially

Use this lowest-complexity mode when later Stories can inherit earlier work after it reaches
`main`.

```text
main
  ├── work-item/5001-first-story  → PR → merge
  ├── work-item/5002-second-story (from updated main) → PR → merge
  └── work-item/5003-third-story  (from updated main) → PR → merge
```

1. Prepare Feature 5000 only when its shared context is genuinely useful.
2. Confirm the included Stories and delivery order in `delivery-map.md`.
3. Deliver Story 5001 using Procedure 1.
4. Merge it to `main` before starting dependent Story 5002.
5. Synchronize local `main` from GitHub.
6. Start Story 5002 from that new `main`; do not cherry-pick Story 5001 into it.
7. Repeat for Story 5003.

If prepared Feature context is not yet on `main`, the first Story may carry the exact Feature
context/map through its existing intake bootstrap. Start later Stories after that PR merges.

## Procedure 3 — Independent Stories, in parallel

Use only when every Story is independently mergeable and concurrent changes do not create an
unsafe shared-writer problem.

```text
main
  ├── work-item/5001-first-story  → PR to main
  ├── work-item/5002-second-story → PR to main
  └── work-item/5003-third-story  → PR to main
```

Before branching:

1. If all Stories need prepared Feature context, land the Feature `ado-context.md` and
   `delivery-map.md` through a separately reviewed context-only PR to `main` first. Never copy an
   unmerged map into several branches.
2. Confirm each Story satisfies and validates its own ACs independently.
3. Identify shared Salesforce components/configuration and assign one active writer per shared
   surface until that writer's PR merges.
4. Start all branches from the same confirmed `origin/main` baseline.

During work:

- each Story has its own remote branch, Draft PR, design, validation, QA handoff, and `AB#Story`;
- after a sibling PR merges, all open branches fetch and assess the changed `main`;
- branches touching affected surfaces synchronize promptly, rerun relevant checks, and push;
- no Story absorbs sibling ACs merely to avoid waiting;
- if coupling becomes material, pause and select sequential delivery, a prerequisite/enabler, or
  combined Feature delivery explicitly.

## Procedure 4 — Combined Feature delivery on a Feature branch

Use when the Feature is genuinely coupled and child Work Items should integrate before any code
lands on `main`. Sequential direct delivery on the Feature branch is the default; child branches
are the optional concurrency escape hatch.

```text
main
  └── feature/5000-feature-name
        ├── [WI-5001] ... — AB#5001        (sequential direct commits, the default)
        ├── [WI-5002] ... — AB#5002
        └── work-item/5003-third-story → PR to feature/5000   (optional parallel child)

feature/5000-feature-name → final PR to main (merge commit)
```

### 1. Bootstrap the Feature branch

1. Run `/prepare-delivery-feature itemId=5000` and verify included/deferred children and order.
2. Explicitly choose combined delivery: `git-agent: start feature 5000`.
3. The Git Agent verifies the prepared map, requires local `main` to equal confirmed
   `origin/main`, creates `feature/5000-<slug>`, and commits only the Feature `ado-context.md`
   and `delivery-map.md` as `[FEATURE-5000] add delivery context — AB#5000`.
4. Approve and perform the push. The pushed `AB#5000` commit gives ADO its native commit link;
   a manual Branch link is optional.
5. Do not create Feature-level `design.md`, tasks, decisions, or QA plan.

### 2. Deliver each child Work Item

Sequential-direct (default), for Story 5001:

1. fetch its ADO context (`/fetch-ado-item itemId=5001`) — only the child currently being
   started, never every included Story up front;
2. design on the Feature branch (`/solution-design itemId=5001` is valid there because the
   prepared map includes 5001);
3. implement and test;
4. `git-agent: commit work item 5001` — the agent verifies map membership and single-item
   scope, then commits `[WI-5001] … — AB#5001`;
5. push and open/update the Draft Feature PR to `main`.

Optional parallel child, for Story 5003: explicitly ask for a child branch; the Git Agent
creates `work-item/5003-<slug>` from the confirmed remote Feature branch, and its Draft PR
targets `feature/5000-<slug>` with exactly `AB#5003`. A child PR links its Story, never the
parent Feature instead.

### 3. Integrate child work

- Child branches synchronize from the remote Feature branch, not directly from `main`.
- Synchronize the Feature branch from `main` before the first child, after relevant mainline
  changes, before combined testing, and before the final PR.
- After a child merges, other open child branches fetch the updated Feature branch and assess
  whether to synchronize before continuing.
- Use one active writer for each shared component. Later children inherit merged foundation work
  from the Feature base.
- Require the triggered CI to pass before each child merge, even if GitHub rulesets currently
  protect only `main`. In that case CI compliance is team policy, not an enforced merge block.
- A child PR may be squash-merged into the Feature branch when that produces one truthful
  `[WI-<ID>] … — AB#<ID>` commit and the child PR remains as review evidence.

### 4. Final Feature PR

After all included child work is on the Feature branch:

1. confirm every included Work Item is present and deferred ones remain outside scope;
2. synchronize the Feature branch with latest `origin/main`;
3. run combined integration and regression validation;
4. confirm Story-level QA evidence where required without inventing a Feature QA repository file;
5. open the final PR from `feature/5000-<slug>` to `main`;
6. link `Azure Boards Feature: AB#5000` and `Included Work Items: AB#5001, AB#5002, AB#5003` —
   the child IDs come mechanically from the map's current `included` set; multiple `AB#`
   references are the explicit Feature-PR exception;
7. focus the PR on integration behavior, combined risks, conflict decisions, rollback, and final
   verification rather than repeating every child narrative;
8. wait for `PR CI / Gate` and required review;
9. a human merges **as a merge commit**, preserving the `[WI-<ID>]` commits, updates ADO, and
   removes Feature/child branches when safe. Do not squash the final Feature PR while Work Item
   commits carry delivery traceability.

Open this final PR near integration readiness. Opening it at bootstrap causes noisy CI reruns after
every child merge; the remote Feature branch and linked child Draft PRs already provide early
visibility.

## Work discovered in another Story's apparent scope

A file does not permanently belong to one Story. Decide by acceptance scope and coherent delivery:

| Discovery | Owner | Action |
|---|---|---|
| Small change required for current AC | current Story | implement and record later reuse implication |
| Shared helper naturally needed by current Story | current Story unless independently valuable | implement once; later Stories inherit it |
| Change independently satisfies another Story's AC | other Story | stop scope creep; deliver separately |
| Current Story cannot proceed without another | prerequisite Story/enabler | pause current Story; deliver prerequisite first |
| Foundation serves several Stories and belongs to none | explicit technical/enabler Work Item | obtain owner-approved Work Item before coding |
| Same shared component edited concurrently | one designated active writer | others pause that surface and synchronize after merge |
| Ownership remains unclear | human owner | stop; do not let a model choose by title or file history |

### Deliver a prerequisite first

1. Bring the blocked Story to a clean pushed checkpoint and explain the blocker in its Draft PR.
2. Do not leave the only copy in a stash or cherry-pick incomplete work into the prerequisite.
3. Use a separate Git worktree for the prerequisite if both checkouts must remain accessible; do
   not repeatedly switch one dirty worktree between branches.
4. Deliver the prerequisite to the current authoritative base (`main` or the Feature branch).
5. Return to the blocked Story, fetch and merge the updated base.
6. Reconcile its design when the prerequisite changed behavior or AC coverage.
7. Rerun affected checks and push before continuing.

Use a technical/enabler Work Item only when the shared foundation is independently reviewable and
does not naturally belong to an existing Story. It receives its own ADO identity, proportional
design, branch, PR, and validation.

## Pause, handoff, resume, and recovery

### Pause or end a session

- reach a coherent checkpoint;
- run checks appropriate to its state;
- commit and push;
- update the Draft PR with blockers and `Not verified` items;
- leave branch, base, Work Item, next action, and latest validation understandable without chat;
- never leave meaningful work available only in a local stash or untracked file overnight.

### Handoff

The remote branch and Draft PR are the handoff vehicle. Durable state lives in `design.md`,
tasks/decisions, validation evidence, and PR text. The recipient fetches, verifies the declared
base and ADO revision, synchronizes, and reruns proportional validation before editing.

### Resume

1. Fetch origin and confirm branch/PR remote heads.
2. Compare with the correct base.
3. Inspect new ADO revisions and prepared Feature-map changes.
4. Synchronize and reconcile before continuing.
5. Push the resulting checkpoint.

### Failed push or diverged remote

Stop and report local/remote commit evidence. Never force-push. Determine whether another person
updated the branch, coordinate ownership, then merge safely. A failed or unverified push is not a
successful sync and must not produce a claimed PR link.

## CI, review, and merge

Current CI is diff-aware:

- every PR emits `PR CI / Gate`;
- pure `force-app/**` changes run Salesforce-specific CI without the full harness;
- pure `work-items/**` changes run neither heavy lane;
- workspace/control-plane changes run the full harness;
- conditional skipped lanes are expected when the classifier says they are unnecessary.

Only report checks actually run. Green CI proves repository controls, not business approval,
deployment, or release readiness. Merge remains a human decision.

## Worked examples

### One Story

```text
/fetch-ado-item itemId=5001
ADO: set In Design
git-agent: start work item 5001      → work-item/5001-<slug>, [WI-5001] … — AB#5001
approve push (AB# commit links natively in ADO)
/solution-design itemId=5001
commit + push design → open Draft PR to main with AB#5001
implement + validate + checkpoint pushes
sync from main → PR CI / Gate → human merge
```

### Feature with independent Stories

```text
/prepare-delivery-feature itemId=5000
5001 → branch/PR/main → merge
5002 → create from updated main → branch/PR/main → merge
5003 → create from updated main → branch/PR/main → merge
```

For safe parallel work, land shared Feature context first, create all branches from the same
`origin/main`, and synchronize affected branches after each sibling merge.

### Feature with combined delivery

```text
/prepare-delivery-feature itemId=5000
git-agent: start feature 5000        → feature/5000-<slug>, [FEATURE-5000] … — AB#5000 (push)
/fetch-ado-item itemId=5001 → /solution-design → develop → git-agent: commit work item 5001 → push
/fetch-ado-item itemId=5002 → /solution-design → develop → git-agent: commit work item 5002 → push
optional parallel: work-item/5003-<slug> from remote feature/5000 → Draft PR to feature/5000 with AB#5003
combined verification
feature/5000-<slug> → final PR to main: AB#5000 + included AB#5001, AB#5002, AB#5003 (merge commit)
```

## Developer checklists

### Start

- [ ] Correct concrete Work Item and current ADO revision confirmed
- [ ] Delivery mode and authoritative base selected
- [ ] Remote base fetched and local baseline current
- [ ] ADO moved to `In Design` when active work begins
- [ ] Correct branch created and intake committed with its `AB#<ID>` reference
- [ ] Branch pushed (the pushed AB# commit links natively; manual Branch link optional)
- [ ] Draft PR opened after first non-intake checkpoint
- [ ] PR contains the correct raw `AB#` reference(s) for its delivery container

### End or handoff

- [ ] Work is at a coherent checkpoint
- [ ] Proportional checks and their real results recorded
- [ ] Commits pushed; no meaningful local-only stash/untracked work
- [ ] Draft PR describes current scope, blockers, validation, and next action
- [ ] Branch compared with its correct base
- [ ] New ADO/Feature revisions reconciled or visibly blocked
- [ ] No force-push, duplicated commit, silent conflict decision, or mixed Work Item scope

## Current automation limitations

The Git Agent currently automates the safe local bootstraps (`start work item`,
`start feature` for a prepared Feature, an explicitly requested parallel child from the
confirmed remote Feature branch), exact-path intake staging/commit, explicit Work Item commit
attribution (`commit work item <ID>`), approved push, and copyable PR handoff. It does not:

- change ADO state;
- add a formal GitHub branch link in ADO (optional, human, not required by this process);
- choose or change a Feature delivery mode — the human selects combined vs independent;
- fetch ADO or edit `ado-context.md`/`delivery-map.md`;
- create a PR automatically;
- merge, deploy, release, force-push, or silently resolve conflicts.

Those steps remain human-managed in the current workspace version. Automating them would require a
separate runtime change and validation; this document alone enables nothing.
