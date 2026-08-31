# Ways of Working

This is the route map for people using the workspace after installation. It helps you choose the
right entry point for the work in front of you — a feature, a diagnosed defect, a
managed-package dependency, or a configuration-only change — and tells you what the agent will
produce, what stays your decision, and how you know a path is done.

> This document is a guide for people using the workspace. It is not an execution instruction
> for agents. Agent behavior is defined by the repository's prompts, skills, role contracts,
> and safety controls.

The guide describes the entry points that exist today and does not replace their contracts:
where a detail is governed elsewhere, this page tells you what to expect and links to the
authoritative source. If you have not installed the workspace yet, start with
[SETUP.md](../SETUP.md).

## How the workspace divides responsibility

| Human owns | Agent helps with |
|---|---|
| Business intent and acceptance criteria | Evidence collection and structured design |
| Vendor guarantees not established by evidence | Repository review and read-only non-production org review |
| Approval of scope, designs, and Knowledge | Drafting, comparison, and traceable artifacts |
| Merge and release decisions; confirmation of each exact real deploy | Repository edits and in-scope Salesforce CLI execution within the Developer role |

Four points hold across every path:

- The Developer may deploy or mutate an org with direct Salesforce CLI. Every exact real deploy
  first requires your chat confirmation of its target and bounded scope; data and other
  non-deploy mutations do not use that deploy-specific gate.
- Structured org review remains read-only through the guarded Salesforce facade; direct CLI
  execution is a separate Developer capability and may target production when the task requires it.
- You decide whether a proposed design, scope, or Knowledge approval proceeds.
- Durable work belongs in repository artifacts (`work-items/`, `output/`, `.ai/knowledge/`),
  not in chat memory. A conversation is not a record.

## Choose your path

| Situation | Start here | Why |
|---|---|---|
| New feature or material change | [Default delivery work](#playbook-1--default-delivery-work) | Design and evidence first |
| Small diagnosed defect | [Bounded bug fix](#playbook-2--bounded-bug-fix) | Existing express lane |
| Any change touching or depending on managed-package components | [Managed-package namespace overlay](#playbook-3--managed-package-namespace-work) | Ownership and package evidence are mandatory |
| Customer-owned declarative change with no code | [Configuration-only work](#playbook-4--configuration-only-work) | Keep scope proportional while preserving design and evidence |

Two routing rules:

1. If you are unsure whether a change is truly small, use the default path.
2. If more than one row applies, use the default path plus the relevant overlay. Do not choose
   the smallest label to avoid design.

## Playbook 1 — Default delivery work

### When to use it

Use this path for:

- a new feature;
- a material behavior change;
- a change spanning multiple components;
- a request whose implementation is not yet diagnosed;
- any work where acceptance criteria, ownership, or package impact still need to be designed.

### When not to use it

If a written diagnosis already exists and the fix is small, bounded, and customer-owned, the
[bounded bug fix](#playbook-2--bounded-bug-fix) lane is shorter. When in doubt, stay here.

### Starting request

From an Azure DevOps work item:

```text
/fetch-ado-item itemId=242850
```

From a written requirement:

```text
/solution-design <describe the requested outcome and constraints>
```

### What the agent will do

1. From an ADO item, `/fetch-ado-item` first persists the requirement snapshot in
   `work-items/<id>-<slug>/ado-context.md` — source-faithful ADO text kept separate from an
   explicitly unapproved AI understanding — and stops with `git-agent: start work item <ID>`.
2. The git-agent verifies clean, synchronized `main`, creates the `work-item/<id>-<slug>`
   branch, stages only the exact intake artifact, and commits it locally with the item's raw
   `AB#<id>` reference (once pushed, Azure Boards links the commit natively — no manual Branch
   link is required). It does not push and returns `/solution-design itemId=<ID>`. This keeps
   intake, design, and implementation on one item-scoped branch while preserving intake as its
   own reviewable commit.
3. On `/solution-design`, the designer reads the persisted context (or your written
   requirement), gathers Knowledge, repository, and allowed org evidence, and persists the
   design in `work-items/<id>-<slug>/design.md`, naming its requirement baseline (context
   path + ADO revision) for ADO-backed work.
4. You resolve business questions, vendor guarantees, and unapproved choices it surfaces.
5. A reviewer can challenge the persisted design with `/check-against-principles`.
6. After you accept the design, the developer implements against it and keeps `tasks.md` and
   `decisions.md` current. It validates proportionally and, when a real deployment is in scope,
   tells you that changes will be deployed to the selected org, identifies target and scope, and
   asks for confirmation for that exact invocation. After any qualifying org mutation returns a
   result, it writes one sanitized entry to the canonical `org-changes.md`. A dry run is never
   described as deployed, and an org-change entry is never a QA result or release approval.
7. Verification follows the design; the test-strategist agent is the entry point when a QA
   coverage decision is needed. When the item is being handed to a QA engineer,
   `/prepare-qa-test-plan itemId=<ID>` writes `work-items/<id>-<slug>/qa-test-plan.md` — a
   human-executable handoff (feature orientation plus Test Cases with expected results) that
   works the same for custom, managed-package, and mixed changes. It can draft before
   implementation and refresh against the finished code; it asks you only the few facts the
   evidence cannot establish (entry points, personas, vendor guarantees, safe test data).
   Skip it for work no tester picks up — Knowledge maintenance, investigations, harness-only
   changes; nothing creates it automatically, and QA execution results (PASS/FAIL, runs,
   screenshots) stay in Azure Test Plans, never in the repository.
8. The git-agent can prepare later commits and PR work. It asks before every push; after a push
   it actually completes successfully, it returns a suggested title, the fully completed
   repository PR template for copying, and a direct GitHub creation link when the remote can be
   identified. It does not need GitHub CLI and does not create the PR. Merge and release decisions
   remain yours; the Developer's real deploy still requires your exact-invocation confirmation.
9. Changes to the workspace itself — prompts, skills, instructions, scripts, schemas, tests,
   docs, tracked configuration — go through the **workspace-maintainer** agent, not a
   delivery agent. Files that define permissions or external capability (the safety
   hook/role guard, agent definitions, MCP and VS Code configuration) additionally stop for
   your explicit confirmation on the edit itself; you can also just make such changes
   directly yourself.

### What you decide

- whether the requirement and acceptance criteria are correct;
- whether business meaning and vendor guarantees are established;
- whether the proposed scope and trade-offs are acceptable;
- whether the design is ready for implementation;
- whether a PR is ready to merge and deploy.

### Expected artifacts

- `work-items/<id>-<slug>/ado-context.md` — the ADO requirement snapshot (ADO-backed work
  only; absent for a written requirement);
- `work-items/<id>-<slug>/design.md` — the accepted intent;
- `work-items/<id>-<slug>/tasks.md` — the execution checklist;
- `work-items/<id>-<slug>/decisions.md` — deviations recorded during implementation;
- `work-items/<id>-<slug>/qa-test-plan.md` — the QA handoff, only when the item goes to a
  tester;
- scoped repository changes with verification evidence;
- a PR prepared for your review, when you ask for one.

See [work-items/README.md](../work-items/README.md) for what each durable file means.

### Done here means

- scope and design are persisted and accepted;
- the implementation matches the design, or deviations are recorded in `decisions.md`;
- planned verification has an explicit result;
- every qualifying org mutation has one canonical sanitized `org-changes.md` entry;
- unresolved gaps are visible, not hidden;
- you have what you need to decide merge and deployment.

"The agent finished" is not automatically "deployed" or "released". A deploy is proven only by
its CLI result; release remains a separate decision.

### Common pitfalls

- starting implementation from a chat-only requirement without a persisted design;
- treating an ADO item as approved technical scope;
- silently accepting an unverified package assumption;
- letting `decisions.md` lag behind the implementation;
- reading a local repository edit as a change already made in an org.

### Delivering a multi-Story Feature (optional overlay)

Most Stories stay on the default path even when ADO shows a Feature or Epic parent — a parent
relation used for reporting adds nothing locally and is deliberately ignored. Use this overlay
only when one ADO Feature is genuinely being delivered through several of its child Stories and
you want each Story designed with the shared Feature context in view.

For the human Git/ADO procedure — including remote-first checkpoints, parallel Stories, and the
combined Feature-branch mode — see [Delivery Process](delivery-process.md).

Prepare the Feature once, explicitly:

```text
/prepare-delivery-feature itemId=5000
```

This persists two files in the Feature's own flat folder — `ado-context.md` (the Feature
requirement snapshot) and `delivery-map.md` (which direct children are included in the active
delivery, in what order) — and nothing else. No child folders are created, no Stories are
fetched, and nothing else changes. To activate only a subset, name it:
`/prepare-delivery-feature itemId=5000 include=5001,5003`.

Preparation ends with two explicit choices — you select the delivery container; nothing is
inferred from the ADO parent relation:

- **Independent child delivery** (the default): deliver each Story exactly as in the default
  path, in any order, one at a time:

  ```text
  /fetch-ado-item itemId=5001
  git-agent: start work item 5001
  /solution-design itemId=5001
  # implement, test, QA plan if needed, PR AB#5001
  ```

- **Combined Feature delivery**: `git-agent: start feature 5000` creates
  `feature/5000-<slug>`, and included Stories land on that one branch as explicit
  `[WI-<id>] … — AB#<id>` commits (`git-agent: commit work item <ID>`), with optional
  parallel `work-item/<id>` child branches targeting the Feature branch. One final Feature PR
  to `main` links the Feature and its included children and merges as a merge commit. See
  [Delivery Process](delivery-process.md) for the full procedure.

When a Story is listed as included in exactly one prepared map, its Solution Design reads the
local Feature context and records that baseline in the Story's `design.md`; the Story's own
acceptance criteria stay authoritative, and design, decisions, and QA remain per Story. Neither
mode creates a Feature design or Feature QA plan. Rerun prepare only when the Feature's scope or
your active slice changes; there is no per-Story re-preparation.

If several Stories must branch in parallel before the prepared Feature context is present on
`main`, stop at Git bootstrap and choose the coordination strategy explicitly. The git-agent does
not duplicate an unmerged Feature map across unrelated Story branches; the default is sequential
delivery after the first Story/context commit lands.

Two things this overlay is not: it is not Feature Knowledge (`/author-feature` and
`.ai/knowledge/features/` curate governed product meaning — a delivery map is short-lived
coordination, and neither implies the other), and it is not `/feature-health` (the explicit,
higher-cost Feature/BRD-to-Story coverage review, which you run separately when a Feature is
release-critical, ambiguous, or BRD-backed — never triggered by preparation or Story work).

## Playbook 2 — Bounded bug fix

The express lane for a defect that is already diagnosed.

### When to use it

Use it only when all of these are true:

- a written diagnosis already exists;
- expected and actual behavior are known;
- the target component is named;
- the smallest coherent fix is narrow;
- package ownership and namespace impact are understood and recorded.

### When not to use it

Route to the [default path](#playbook-1--default-delivery-work) when:

- the root cause is unknown;
- the fix requires an architectural choice;
- several components or behaviors are changing;
- acceptance criteria are unclear;
- the request is really a feature or a refactor;
- the target is package-owned.

### Starting request

```text
/adhoc-fix component=Flow:Case_Routing org=my_review_sbx
Diagnosis: <expected behavior, actual behavior, and the defective element>
```

(The component and org alias above are fictional; use your own diagnosed component and a
configured non-production review alias.)

### What the agent will do

- confirm the bounded entry conditions hold;
- retrieve and read the current org source through the appropriate evidence or CLI lane;
- check relevant Knowledge and dependencies;
- make the smallest coherent repository edit in `force-app/`;
- verify what can be verified locally;
- write a fix note under `output/documentation/adhoc-fixes/`;
- ask for single-use chat confirmation if a real deploy is needed, then deploy, verify it, and
  link the canonical durable org-change entry from the ignored fix note.

### What you decide

- confirm the diagnosis and component ownership;
- decide whether the express lane is still appropriate as facts emerge;
- review the exact change;
- confirm the exact target and scope when the agent proposes a real deployment;
- decide whether the finding should become durable Knowledge.

### Done here means

The bounded repository fix and its fix note are ready for review. If a real deploy was confirmed
and executed, the outcome must include org verification and one durable sanitized org-change
entry; otherwise no deployment occurred.

### Common pitfalls

- using the express lane to skip design for a broad change;
- expanding scope with drive-by refactors;
- treating namespace or package ownership as a substitute for evidence and impact analysis;
- claiming success before deployment and org verification are proven.

## Playbook 3 — Managed-package namespace work

This is an **overlay** on the default path, not a separate shortcut. It adds evidence and
ownership obligations; it removes nothing.

### When it applies

Apply the overlay whenever a requested change:

- touches a namespaced component;
- depends on a namespaced object, field, API, event, or extension point;
- changes customer-owned metadata whose behavior relies on the installed package;
- makes a claim about package ownership, version, or vendor behavior.

### Starting request

The preferred entry point is still the normal design path, with the dependency named:

```text
/solution-design Add subscriber-owned automation for <outcome>. The design depends on
<Namespace>__<Component>; verify ownership, package version, and the supported extension point.
```

For a narrow fact-finding question, `/search-knowledge` and `/investigate-object` are read-only
starting points — but an investigation report is an observation, not an approved design and not
citable Knowledge by itself.

### What the workspace will do

- establish component ownership and the installed-package context;
- consult effective Knowledge and the available evidence sources;
- keep package impact explicit in the design, in its own right — not buried in a paragraph;
- record the actual ownership and impact of every changed surface without applying a
  namespace-based deny;
- stop, or expose the gap, when required package behavior or vendor guarantees cannot be
  established from evidence.

### What you decide

- supply or validate business meaning;
- provide vendor guarantees when governed evidence cannot establish them;
- accept the proposed extension boundary;
- decide whether an evidence gap blocks the work;
- own escalation to the vendor where necessary.

### Done here means

Ownership, the package dependency, evidence limitations, and the customer-owned extension
boundary are visible in the persisted design and carried through implementation and review.

### Common pitfalls

- treating the namespace prefix as proof of supported behavior;
- attempting to edit package-owned metadata;
- relying on model knowledge instead of repository and org evidence;
- hiding package impact inside a generic design paragraph;
- turning an observation into a vendor guarantee.

## Playbook 4 — Configuration-only work

"Configuration" means three different things. Sort yours first:

1. **Salesforce declarative metadata** in customer-owned `force-app` source — a Flow, permission
   set, layout, or Custom Metadata Type definition. **This playbook applies.**
2. **Configuration/reference records stored as org data** — statuses, settings, routing tables.
   The workspace can investigate them read-only through the governed lane; the Developer may
   also perform an explicitly scoped record mutation through Salesforce CLI when the task asks
   for it, without the metadata-deploy confirmation gate, and must log the result durably.
3. **Harness/local configuration** — `config/`, environment variables, MCP setup, VS Code
   settings. This playbook does not authorize those changes; use the relevant setup or
   maintenance procedure instead.

### When to use it

Use it for a bounded, customer-owned declarative metadata change with no Apex/LWC code and a
clear requested outcome.

It is still design-first when behavior, ownership, package dependency, access, or rollback is
material. "No code" does not mean "no risk."

### Starting request

Through the existing design entry point, stated as a requirement:

```text
/solution-design Update the customer-owned Flow <FlowName> to <outcome>. Keep the change
configuration-only, verify package dependencies and permissions, and include rollback and
activation steps.
```

For read-only reference-data discovery:

```text
/investigate-config-records objectApiName=Routing_Setting__c org=my_review_sbx
```

The second command produces an observation report. It does not authorize or perform any org
data change. (Object name and alias are fictional; the object must be on the review allowlist.)

### What the agent will do

- confirm ownership and the current source and evidence;
- keep scope proportional to a declarative change;
- record behavioral, access, package, activation, verification, and rollback implications;
- edit only authorized repository metadata, after design acceptance;
- when requested, execute bounded deployments or record mutations through the Developer lane and
  persist one sanitized post-action org-change entry.

### What you decide

- confirm the desired business behavior and the affected users;
- decide activation timing and any data or configuration migration steps;
- approve access and permission implications;
- confirm each exact real metadata deployment proposed by the Developer;
- verify the result in your intended non-production and release process.

### Done here means

The repository metadata change and the design's verification and rollback information are ready
for release review. Any executed org-data or deployment step is separated and linked through the
canonical org-change log.

### Common pitfalls

- assuming declarative means harmless;
- mixing a metadata change with a live org-record write;
- forgetting activation order or rollback;
- editing package-owned configuration surfaces;
- treating local `config/harness.local.json` as a deliverable.

## How a design, its implementation, and review stay aligned

The slash prompts and the Designer agent are entry surfaces; the step-by-step Solution Design
procedure lives in one place, the solution-design skill. What you should expect in the
artifacts:

- **`design.md` connects requirements to solutions and verification.** Its
  `Acceptance criteria coverage` matrix gives every acceptance criterion (or human-provided
  requirement outcome) a row naming its solution, its planned verification, and an honest
  status — `Covered`, `Explicit no-change` with a reason, or `Open`. Its
  `Planned change surface` table declares which logical components the work intends to
  create, modify, or remove, and which package dependencies stay read-only.
- **Development records material deviations, append-only, in `decisions.md`** — planned vs
  actual surface, the reason, and any verification/rollback/QA impact. The design is not
  rewritten to match the code.
- **Implementation review compares all three with the exact diff** and reports a
  `Scope alignment` classification (`ALIGNED`, `EXPLAINED DELTA`, `UNEXPLAINED DELTA`,
  `INCOMPLETE`) before its normal verdict. Tests, fixtures, and manifests that only support a
  planned component are not flagged as scope creep — but an explained delta is reviewable,
  not automatically approved: every package and safety rule still applies.
- **On a shared Feature branch, name the exact review subject.** One Story's review never
  infers its commits from the whole branch. Supply them explicitly, for example:

  ```text
  /check-against-principles itemId=5001 scope=implementation commits=a1b2c3d,e4f5a6b
  ```

  (or a contiguous `base=<ref> head=<ref>` range). Without exact attribution the review
  returns `INCOMPLETE` rather than guessing.

## Feature Knowledge

Two kinds of governed Knowledge live in this workspace, and they answer different questions:

- **Artifact Knowledge** holds governed technical facts about individual components.
- **Feature Knowledge** groups human-curated product meaning — what a feature is, its
  vocabulary, and its topology across many artifacts.

You curate the feature boundary and the business meaning; source collectors cannot derive them.
Technical claims do not become authoritative by appearing in a Feature document — they still
need the appropriate Artifact Knowledge or evidence behind them. Approval of Feature Knowledge
is an explicit human action through the existing digest-pinned lane.

Entry points:

- `/author-feature <feature-name-or-slug>` — interactive authoring of one Feature document;
- `/feature-health itemId=<Feature ID>` — the ADO Feature/BRD-to-Story coverage check run
  before Solution Design; this is a delivery gate, not Feature Knowledge approval.

Use Feature Knowledge when you are onboarding to a feature that spans many artifacts, explaining
feature topology and vocabulary, preserving business meaning that collectors cannot derive, or
reviewing impact across a curated feature boundary. For the governing detail, see
[knowledge-one-file-contract.md](knowledge-one-file-contract.md).

## Where work is recorded

| Artifact | Human meaning |
|---|---|
| `work-items/<id>-<slug>/ado-context.md` | Source-faithful ADO requirement snapshot plus clearly unapproved AI understanding (ADO-backed work) |
| `work-items/<id>-<slug>/design.md` | Accepted intent, scope, trade-offs, verification, and rollback |
| `work-items/<id>-<slug>/tasks.md` | Current execution checklist |
| `work-items/<id>-<slug>/decisions.md` | Append-only deviations and rulings |
| `work-items/<id>-<slug>/org-changes.md` | Optional append-only operational history of qualifying Salesforce mutations; an agent report, not approval/evidence |
| `work-items/<feature-id>-<slug>/delivery-map.md` | Explicit membership and order of an actively prepared ADO Feature's delivery — coordination only (Feature folders only) |
| `docs/org-changes/**` | Standalone org-change history only when no Work Item or prepared Feature applies |
| `output/**` | Draft and review artifacts — not automatically authoritative |
| `.ai/knowledge/**` | Governed Knowledge, written only through its existing lanes |

See [work-items/README.md](../work-items/README.md) for the work-item files and
[grounding-architecture.md](grounding-architecture.md) for the evidence boundary. Chat is not
durable state; if it matters, it belongs in one of these artifacts.

## What agents cannot do for you

- approve their own Knowledge or your business decisions;
- invent vendor guarantees or package internals;
- run a real deployment without your fresh confirmation of that exact target and scope;
- treat a mutation log, CLI result, or dry run as release approval, QA evidence, Knowledge, or
  proof that the org still has that state;
- silently merge, release, or resolve ownership decisions;
- convert incomplete evidence into certainty.

If an outcome seems to require one of these, the missing piece is a human decision or a human
action — supply it, or stop the work.

## Quick reference

| Need | Entry point |
|---|---|
| Start from an ADO item | `/fetch-ado-item itemId=<ID>`, then `git-agent: start work item <ID>`, then `/solution-design itemId=<ID>` |
| Deliver one ADO Feature through several child Stories | `/prepare-delivery-feature itemId=<Feature ID>` once, then choose: independent per-Story delivery, or `git-agent: start feature <Feature ID>` for one combined Feature branch |
| Navigate an ADO Epic to a child Feature | `/fetch-ado-item itemId=<Epic ID>`, then choose one emitted `/prepare-delivery-feature itemId=<ID>` command |
| Start from a written requirement | `/solution-design <requirement>` |
| Review a persisted design or implementation | `/check-against-principles itemId=<ID> scope=design` (or `scope=implementation`) |
| Apply a small diagnosed fix | `/adhoc-fix component=<Type:Name> org=<alias>` plus the diagnosis |
| Search governed Artifact Knowledge | `/search-knowledge keyword=<term>` (other filters: `text=`, `subject=`, `anchor=`, `error=`) |
| Investigate an allowlisted object | `/investigate-object objectApiName=<API name>` |
| Investigate reference/config records | `/investigate-config-records objectApiName=<API name> org=<alias>` |
| Author Feature Knowledge | `/author-feature <slug-or-name>` |
| Assess feature coverage | `/feature-health itemId=<Feature ID>` |
| Prepare routine Git work or push with a copyable PR handoff | `git-agent` custom agent |

This table lists the entry points behind the playbooks above, not the whole catalog — the
Copilot slash menu shows the full current set of public prompts.
