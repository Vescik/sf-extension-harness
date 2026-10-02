---
name: maintain-workspace
description: Bounded workspace control-plane maintenance — classify paths, inventory impact, edit behind the root-of-trust confirmation edge, validate, and commit the completed local result.
user-invocable: false
---

# Maintain the workspace

Apply the [shared execution contract](../../../.ai/contracts/execution-contract.md). The role
guard is the enforcement point; this skill is the procedure, never a substitute for the hook.

1. **Classify.** Sort every path the request touches: standard control plane (edit freely),
   root of trust (the guard/safety hook, ADO launcher, scope/tool policy and Wiki adapters, native Salesforce extension/package and private policy/session/job runtime, `.github/agents/**`, MCP/VS Code configuration,
   harness config, the workspace file — human confirmation required), or out of scope
   (Salesforce source, work items, governed Knowledge, local config, caches other than the
   exact PR transport path `.cache/github/pr-body.md`, `output/` —
   refuse and route). A mixed workspace/feature request is split; the Salesforce part goes
   to the Developer.
2. **Inventory impact.** Before editing, search for every consumer of the surface being
   changed: schemas, the executor, registrations, allowlists, validator pins, tests, evals,
   setup documents, and agent-facing instructions. A rename or count change usually has a
   pinned test; find it now, not after the red gate.
3. **State the change.** Say what behavior changes, what deliberately stays unchanged, and
   which validation is proportional. For a root-of-trust edit, name the exact capability or
   safety property widened, narrowed, added, or removed, and every affected file — before
   the tool call that triggers the confirmation.
4. **Edit proportionally.** The smallest coherent change. Do not add a runtime, cache, MCP
   server, state machine, background process, or generic command runner without an explicit
   owner decision — those are architecture changes, not maintenance.
5. **Use the safety edge.** The role guard returns `ask` on the actual root-of-trust edit;
   the human decides there. If declined, mutate nothing and continue read-only — never retry
   a variant of a declined edit.
6. **Validate.** Guard/agent/config changes run the full harness gate
   (`python scripts/validate_harness.py`, `python -m unittest discover -s tests`,
   `python scripts/run_evals.py`, plus `python -m py_compile` / `node --check` for edited
   files and `npm run prettier:verify` / `npm run lint` where relevant). Content-only
   changes use the documented proportional checks plus the pinned scenarios they touch.
   Report only results actually observed; a skipped or interrupted gate is reported as such.
7. **Commit and report.** Follow the [Git Workflow](../git-workflow/SKILL.md) to prepare/resume
   the proper `chore/` branch and stage/commit the completed permitted result after verification,
   without a separate commit request or Git Agent handoff. Preserve unrelated work. Report
   changed surfaces, actual validation, commit SHA, and residual risk. Root-of-trust approval
   remains on the edit. GitHub reads are available; push/PR publication/update and merge require
   an explicit instruction covering that operation. Do not deploy or touch org/ADO state.

No approval ledger, work record, or recurring maintenance queue exists in this lane; git
history and the PR are the review trail.
