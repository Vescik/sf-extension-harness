# Harness evaluations

The deterministic suite proves hook decisions, role path boundaries, frontmatter/wiring contracts,
schema fixtures, and workspace safety configuration without contacting Salesforce or Azure DevOps.

Run:

```bash
python3 scripts/validate_harness.py
python3 -m unittest discover -s tests -v
python3 scripts/run_evals.py
```

`safety-scenarios.yaml` is executable in CI. `agent-scenarios.yaml` is the forward-test checklist
for VS Code because model/tool resolution and handoff rendering require the Copilot host. Record
results in the pull request; a textual answer that merely contains the expected words is not a
pass. Sanitized fixtures intentionally include complete and partial responses so incomplete
evidence behavior can be tested without real business data.

## Handoff quality trials

The bounded [handoff-quality fixtures](fixtures/handoff-quality/) contain three synthetic
input documents and three independent evaluator oracles. They test the meaning of a
design, the Developer's task lifecycle, and continuation from durable files. They are not
production Work Items or approved Knowledge. No heading count or keyword score proves
that a design is implementable.

| Case | Agent input | Evaluator only |
| --- | --- | --- |
| G1: small formula | [g01-input.md](fixtures/handoff-quality/g01-input.md) | [g01-oracle.md](fixtures/handoff-quality/g01-oracle.md) |
| G2: Flow and bulk Apex | [g02-input.md](fixtures/handoff-quality/g02-input.md) | [g02-oracle.md](fixtures/handoff-quality/g02-oracle.md) |
| G3: resume and supersede | [g03-input.md](fixtures/handoff-quality/g03-input.md) | [g03-oracle.md](fixtures/handoff-quality/g03-oracle.md) |

Before a trial, the operator records the tested revision, instruction variant, model,
host/extension versions, available tools and evidence limits. Use an isolated disposable
repository for each case and variant, with the tested harness instructions and only the
case input and required synthetic source context. Exclude all evaluator oracle files from
the agent-visible workspace, search roots and conversation. If that separation is not
achieved, label the trial non-blind. The oracle must be fixed before the run, not rewritten
to agree with the generated result.

The operator creates the case branch `chore/handoff-pilot-g01` (or `g02`/`g03`) and uses the
full `work-items/pilot-g01/design.md` path (or corresponding case) as the work identity.
These are human-written requirements. Do not invent a numeric ADO ID or force ADO intake.
Start without an active live-org target. The operator's Designer request identifies the
input and output design path and limits discovery to supplied synthetic repository facts.
The later Developer request explicitly authorizes implementation of that identified design
in the disposable repository. Neither request authorizes live Salesforce/ADO calls,
deployment, publication, or production Knowledge writes.

Run the Designer in the supported VS Code Local host, then start a fresh Developer
conversation with the persisted requirement/design, applicable decisions and repository.
Do not supply the Designer transcript or evaluator oracle. The Developer creates or
reconciles tasks before implementation. G3 starts from its supplied in-progress artifacts;
it must not be reset to a fresh design. Pause and resume at least one revised run in
another fresh conversation to inspect partial progress and pending verification. When a
baseline host is available, compare baseline and revised instructions with the same input,
model and host in independent disposable workspaces.

An independent evaluator reads the oracle, actual artifacts, scoped diff and bounded
transcript. Record each mandatory expectation as PASS, FAIL or NOT OBSERVED, with concrete
evidence. A missing behavioral observation leaves the trial incomplete. Acceptance requires
zero invented material business/failure-policy decisions, zero unsupported completion
claims, a usable outcome/basis/completion condition for every active material task, and the
case-specific outcomes. G1 must remain compact; G3 must preserve decision history. Count
clarification turns and rework for comparison, without discouraging necessary questions.
Run the weak-task, premature-checkbox and unresolved-policy negative scenarios plus the
compact referenced-task positive control in `agent-scenarios.yaml`.

G2 requires authored Apex tests and review of their assertions and Flow wiring. It does
not assume a local Apex runtime. Without an authorized Salesforce environment, report Apex
tests as NOT RUN and leave execution-dependent delivery tasks unchecked. Static inspection
can assess the contract and intended bulk behavior; it cannot establish transaction,
limit, deployed Flow or live-org behavior. Do not deploy merely to finish a synthetic trial.

Store dated, sanitized evidence in the existing `harness-lab/pilots/` area outside the
production repository artifacts. Distinguish local checks, agent behavior, VS Code host,
CI and live-org evidence. A Codex-only rehearsal does not certify VS Code rendering or
tool resolution. One observed run per case is limited evidence for that model/host;
rerun failed or inconclusive cases after a targeted correction. Preparing these fixtures
or passing deterministic CI does not mean the trials ran or passed.
