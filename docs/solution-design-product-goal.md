# Solution Design — product goal

Status: normative. This document states **why Solution Design exists and what "working" means**.
It stands above every plan and diagnosis for this workflow: a plan may change how
the goal is reached, but not the goal.

Scope test: **an element that does not serve §1 is out of scope.** That test is the reason this
document exists — without it, "more control" reads as "better product".

---

## 1. The goal

> Given a concrete ADO work item or a written description, the agent delivers a design grounded
> in the available Knowledge and org evidence. It specifies enough behavior for another agent
> to implement without inventing material choices, and checks the design against applicable
> constraints, recorded limitations, and organization principles before handing it over.

For ADO-backed work the requirement arrives as a durable snapshot: `/fetch-ado-item` persists
`work-items/<id>-<slug>/ado-context.md` first. The design names that path as its requirement
baseline and maps the source ACs to the proposed solution and verification. A reviewer compares
against source criteria, not the design's own paraphrase. A noticed ADO/design difference may
be optional information; it never forces redesign or stops the requested work by itself.

When a human has explicitly prepared the item's parent ADO Feature for multi-Story delivery
(`/prepare-delivery-feature`) and exactly one local delivery map includes the item, the design
also reads that prepared Feature context and records it as a second, coordination baseline. This
is optional broader context resolved locally: it never replaces the Story's acceptance criteria
as the requirement authority, and an ordinary ADO parent relation without a prepared map changes
nothing about the design.

Three obligations sit inside that sentence, and all three are load-bearing:

1. **Deliver a design.** Once the request's concrete identity and scope are established, produce
   a useful draft even when some evidence or choices remain unavailable. Keep those gaps visible;
   a draft is not a claim that all dependent work is executable. Preserve the skill's entry routing.
2. **Ground it in what exists.** Reuse before creation, and both stated against measured reality —
   Knowledge entries, the object contract, installed package facts — not against recollection.
3. **Check its own work.** Perform the solution-design skill's one bounded final self-check against
   the proposed behavior, managed-package constraints, recorded limitations and applicable rules.
   Correct what can be resolved in the same turn and expose the remaining material choices.

---

## 2. Who it serves, and what they get

| Reader | What they need from the output |
|---|---|
| The named human approver | One document they can read end to end, whose unknowns are visible before they approve, not after |
| The developer implementing it | An unambiguous behavioral contract for the artifacts to build, and observable completion per acceptance criterion |
| The reviewer challenging it | The decisions and their alternatives, plus what evidence each rests on |
| The next agent touching this work | Persisted state that reconstructs the design without the chat transcript |

Keep the main document focused on behavior, rationale and material evidence. Internal tool
details belong only where they help inspect a claim; they do not require a new state artifact.

---

## 3. What a good design looks like here

- Every in-scope acceptance criterion maps to an artefact, an explicit no-change decision, or a
  named open question — and to a planned verification.
- Every material component or interacting group has the behavior needed for implementation,
  following the [Solution Design contract](../.github/skills/solution-design/SKILL.md#behavior-to-implement).
  A name and a generic test statement are insufficient. Private implementation details remain
  the Developer's choice when they preserve that behavior.
- Every claim about existing state is labelled: measured, or unverified. An assumption is written
  down with its source gap, consequence, and dependent work. Missing domain documents do not prove
  the absence of constraints or prevent a useful draft.
- Ceremony is proportional to risk. A single formula field does not earn the process a data
  migration earns.
- The document is honest about what was not established. "We could not determine X, so the design
  branches" is a good design. "X is fine" without grounding is not.

---

## 4. Construction principles

1. **Useful drafting and honest execution are separate.** A missing fact or unresolved choice
   becomes explicit design content. Resolve material choices before dependent implementation;
   independent work can continue. Role boundaries, input routing, and existing operational
   safety controls remain in force.
2. **Procedures have one owner.** The solution-design skill owns discovery, behavioral content,
   and the bounded self-check. Development owns executable tasks and decision history; review
   owns independent findings. Use the existing AC matrix and Planned change surface. No design
   runtime, computed-coverage service, new readiness status, or approval ledger is required.
3. **Evidence is an annotation on the design, not a precondition for writing it.** Missing evidence
   changes a claim's label; it does not prevent the claim from being proposed and reviewed.
4. **Measure before asking a human.** A fact a governed read surface can return — package
   ownership, whether a field exists, an installed version — is read, not elicited. Humans are
   asked about business meaning, vendor guarantees and risk acceptance.
5. **Proportional depth.** Address the relevant behavior and constraints for the actual change.
   A broad artifact category alone does not justify more ceremony. Do not add mandatory empty
   sections or duplicate architecture in the Developer's checklist.
6. **Structural checks are not quality guarantees.** A deterministic checker verifies the
   *structure* of coverage, never the *correctness* of the design. Review and observed fresh-agent
   trials assess semantics within their stated evidence limits. A `Covered` row names a solution
   and planned verification; it does not prove technical completeness, acceptance, implementation,
   or test success. No extra mandatory review invocation is added to each work item.

---

## 5. Hard boundaries

These hold regardless of any plan:

- no org mutation from the design role; Salesforce and ADO access is read-only;
- acceptance and authorization come from the human, never a model's own verdict or a commit.
  Apply the [shared handoff contract](../.ai/contracts/execution-contract.md#handoff-and-continuation):
  an explicit request to implement an identified persisted design authorizes that bounded work;
  acceptance alone does not start implementation. PR review, publication, deployment confirmation,
  and Knowledge approval keep their separate rules;
- model prose is not evidence, and an unsupported human assertion does not establish package
  behaviour, schema, deployed state or absence;
- an assumption never establishes package behavior or closes a material evidence gap; namespace
  and ownership alone do not add a prohibition beyond the current managed-package rules;
- an unresolved material business or policy choice is not an equivalent internal coding detail.
  A vague answer does not select between unresolved alternatives;
- intent, progress and deviations reconstruct from the existing repository files. Handoff prose
  points to them. Those files do not manufacture authorization or replace the direct human
  instruction; do not create a separate approval record or digest mechanism.

---

## 6. How to tell it is working

Observable, without a baseline to compare against:

- **Deliverability** — a degraded session (sources unavailable) still produces a document with its
  gaps stamped on it, within a small, bounded number of calls.
- **Proportionality** — a one-field change produces a compact design, not a full ceremony.
- **Grounding** — every subject named in the acceptance criteria has a recorded lookup outcome
  before a plan item references it; items without one are visibly labelled.
- **Implementability** — a fresh Developer can derive tasks from the persisted design without
  inventing material behavior. A genuine gap is identified with its affected work instead.
- **Termination** — the bounded self-check ends with a corrected design and named remaining
  choices. It does not start an open-ended review loop.
- **Honesty** — what could not be established appears in the document, and no verification is
  claimed that was not run.

A failure of any of these is a product defect, even if every test passes.

---

## 7. Precedence

```text
solution-design-product-goal.md      (this document — why, and what "good" means)
    └── plans                        (how, in what order, at what cost)
            └── diagnoses/discovery  (what is broken today, and why)
```

A plan that cannot trace an element to §1 should drop that element rather than justify it. A
diagnosis explains the present; it does not set the target. Where an implementation approach and
this document disagree, preserve this goal while keeping the existing role and safety boundaries.
