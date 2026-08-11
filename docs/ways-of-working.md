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
| Deployment, merge, release, and any production action | Repository edits within the selected role |

Four points hold across every path:

- Agents do not deploy. They edit repository files; getting a change into an org is your action.
- Org review is read-only and non-production, through the guarded Salesforce facade.
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
   explicitly unapproved AI understanding — and stops with the next command
   (`/solution-design itemId=<ID>`). Intake and design are deliberately separate steps.
2. On `/solution-design`, the designer reads the persisted context (or your written
   requirement), gathers Knowledge, repository, and allowed org evidence, and persists the
   design in `work-items/<id>-<slug>/design.md`, naming its requirement baseline (context
   path + ADO revision) for ADO-backed work.
3. You resolve business questions, vendor guarantees, and unapproved choices it surfaces.
4. A reviewer can challenge the persisted design with `/check-against-principles`.
5. After you accept the design, the developer implements against it and keeps `tasks.md` and
   `decisions.md` current.
6. Verification follows the design; the test-strategist agent is the entry point when a QA
   coverage decision is needed. When the item is being handed to a QA engineer,
   `/prepare-qa-test-plan itemId=<ID>` writes `work-items/<id>-<slug>/qa-test-plan.md` — a
   human-executable handoff (feature orientation plus Test Cases with expected results) that
   works the same for custom, managed-package, and mixed changes. It can draft before
   implementation and refresh against the finished code; it asks you only the few facts the
   evidence cannot establish (entry points, personas, vendor guarantees, safe test data).
   Skip it for work no tester picks up — Knowledge maintenance, investigations, harness-only
   changes; nothing creates it automatically, and QA execution results (PASS/FAIL, runs,
   screenshots) stay in Azure Test Plans, never in the repository.
7. The git-agent can prepare routine branch, commit, and PR work; push, merge, release, and
   deployment remain yours under the repository's current rules.

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
- unresolved gaps are visible, not hidden;
- you have what you need to decide merge and deployment.

"The agent finished" is not "deployed" or "released" — those are separate human actions.

### Common pitfalls

- starting implementation from a chat-only requirement without a persisted design;
- treating an ADO item as approved technical scope;
- silently accepting an unverified package assumption;
- letting `decisions.md` lag behind the implementation;
- reading a local repository edit as a change already made in an org.

## Playbook 2 — Bounded bug fix

The express lane for a defect that is already diagnosed.

### When to use it

Use it only when all of these are true:

- a written diagnosis already exists;
- expected and actual behavior are known;
- the target component is named;
- the smallest coherent fix is narrow;
- the target is customer-owned metadata, not managed-package internals.

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
- retrieve and read the current non-production source through the allowed read-only lane;
- check relevant Knowledge and dependencies;
- make the smallest coherent repository edit in `force-app/`;
- verify what can be verified locally;
- write a fix note under `output/documentation/adhoc-fixes/`;
- hand you an explicit deployment and verification recommendation.

### What you decide

- confirm the diagnosis and component ownership;
- decide whether the express lane is still appropriate as facts emerge;
- review the exact change;
- perform or authorize deployment outside the agent lane;
- decide whether the finding should become durable Knowledge.

### Done here means

The bounded repository fix and its fix note are ready for your review. It does not mean the
org is fixed — deployment and org verification are yours.

### Common pitfalls

- using the express lane to skip design for a broad change;
- expanding scope with drive-by refactors;
- editing managed-package internals;
- claiming success before human deployment and org verification.

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
- consult effective Knowledge and allowed non-production evidence;
- keep package impact explicit in the design, in its own right — not buried in a paragraph;
- place implementation only in subscriber-owned extension surfaces;
- stop, or expose the gap, when package internals, vendor guarantees, or a supported extension
  point cannot be established from evidence.

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
   The workspace can investigate them read-only through the governed lane, but agents do not
   write records to an org.
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
- never deploy, and never mutate configuration records in an org.

### What you decide

- confirm the desired business behavior and the affected users;
- decide activation timing and any data or configuration migration steps;
- approve access and permission implications;
- perform deployment and any manual org-data changes;
- verify the result in your intended non-production and release process.

### Done here means

The repository metadata change and the design's verification and rollback information are ready
for your release action, with org-data steps separated out and named as yours.

### Common pitfalls

- assuming declarative means harmless;
- mixing a metadata change with a live org-record write;
- forgetting activation order or rollback;
- editing package-owned configuration surfaces;
- treating local `config/harness.local.json` as a deliverable.

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
| `output/**` | Draft and review artifacts — not automatically authoritative |
| `.ai/knowledge/**` | Governed Knowledge, written only through its existing lanes |

See [work-items/README.md](../work-items/README.md) for the work-item files and
[grounding-architecture.md](grounding-architecture.md) for the evidence boundary. Chat is not
durable state; if it matters, it belongs in one of these artifacts.

## What agents cannot do for you

- approve their own Knowledge or your business decisions;
- invent vendor guarantees or package internals;
- deploy or mutate Salesforce orgs;
- operate against production;
- silently merge, release, or resolve ownership decisions;
- convert incomplete evidence into certainty.

If an outcome seems to require one of these, the missing piece is a human decision or a human
action — supply it, or stop the work.

## Quick reference

| Need | Entry point |
|---|---|
| Start from an ADO item | `/fetch-ado-item itemId=<ID>` (persists the requirement context), then `/solution-design itemId=<ID>` |
| Start from a written requirement | `/solution-design <requirement>` |
| Review a persisted design or implementation | `/check-against-principles itemId=<ID> scope=design` (or `scope=implementation`) |
| Apply a small diagnosed fix | `/adhoc-fix component=<Type:Name> org=<alias>` plus the diagnosis |
| Search governed Artifact Knowledge | `/search-knowledge keyword=<term>` (other filters: `text=`, `subject=`, `anchor=`, `error=`) |
| Investigate an allowlisted object | `/investigate-object objectApiName=<API name>` |
| Investigate reference/config records | `/investigate-config-records objectApiName=<API name> org=<alias>` |
| Author Feature Knowledge | `/author-feature <slug-or-name>` |
| Assess feature coverage | `/feature-health itemId=<Feature ID>` |
| Prepare routine Git work | `git-agent` custom agent |

This table lists the entry points behind the playbooks above, not the whole catalog — the
Copilot slash menu shows the full current set of public prompts.
